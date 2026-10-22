"""AWS implementations of the store and blob store (milestone 4), plus reading secrets from SSM.

Selected with STRESSKIT_BACKEND=aws. The API code does not change: these classes have the
same methods as InMemoryStore and LocalBlobStore. boto3 is imported here only, so the local
demo runs without it (install with `pip install -e ".[aws]"`).

DynamoDB single-table layout. Every partition key starts with the tenant, so a query built
from the token's tenant can never reach another tenant's items:

    PK                                SK                       what
    TENANT#<t>#DEVICE#<device_id>     META                     the device
    TENANT#<t>#DEVICE#<device_id>     RESULT#<window_start>    one result per minute
    TENANT#<t>#UPLOAD#<upload_id>     META                     the upload
    TENANT#<t>#IDEM#<key>             META                     idempotency record (24 h TTL)

Each item keeps the model as JSON in `doc`, so the stored shape is exactly the API's shape.
"""

from __future__ import annotations

import json
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from .models import Device, Upload, WindowResult

IDEMPOTENCY_TTL_S = 24 * 3600


def _client_kwargs(region: str) -> dict[str, Any]:
    # Retries with back-off for throttling; standard mode is the AWS-recommended default.
    return {"region_name": region, "config": Config(retries={"mode": "standard"})}


class DynamoStore:
    def __init__(self, table_name: str, region: str, resource: Any = None) -> None:
        dynamodb = resource or boto3.resource("dynamodb", **_client_kwargs(region))
        self.table = dynamodb.Table(table_name)

    @staticmethod
    def _pk(tenant_id: str, kind: str, ident: str) -> str:
        return f"TENANT#{tenant_id}#{kind}#{ident}"

    def _get_doc(self, pk: str) -> dict | None:
        item = self.table.get_item(Key={"PK": pk, "SK": "META"}).get("Item")
        return json.loads(item["doc"]) if item else None

    # --- devices ------------------------------------------------------------------------

    def put_device(self, tenant_id: str, device: Device) -> bool:
        try:
            self.table.put_item(
                Item={
                    "PK": self._pk(tenant_id, "DEVICE", device.device_id),
                    "SK": "META",
                    "doc": device.model_dump_json(),
                },
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get_device(self, tenant_id: str, device_id: str) -> Device | None:
        doc = self._get_doc(self._pk(tenant_id, "DEVICE", device_id))
        return Device.model_validate(doc) if doc else None

    def update_device(self, tenant_id: str, device: Device) -> None:
        pk = self._pk(tenant_id, "DEVICE", device.device_id)
        self.table.put_item(Item={"PK": pk, "SK": "META", "doc": device.model_dump_json()})

    # --- uploads ------------------------------------------------------------------------

    def put_upload(self, tenant_id: str, upload: Upload) -> None:
        pk = self._pk(tenant_id, "UPLOAD", upload.upload_id)
        self.table.put_item(Item={"PK": pk, "SK": "META", "doc": upload.model_dump_json()})

    def get_upload(self, tenant_id: str, upload_id: str) -> Upload | None:
        doc = self._get_doc(self._pk(tenant_id, "UPLOAD", upload_id))
        return Upload.model_validate(doc) if doc else None

    # --- results ------------------------------------------------------------------------

    def put_results(self, tenant_id: str, results: list[WindowResult]) -> None:
        with self.table.batch_writer(overwrite_by_pkeys=["PK", "SK"]) as batch:
            for r in results:
                # Keyed by window start, so reprocessing overwrites instead of duplicating.
                batch.put_item(
                    Item={
                        "PK": self._pk(tenant_id, "DEVICE", r.device_id),
                        "SK": f"RESULT#{r.window_start.isoformat()}",
                        "doc": r.model_dump_json(),
                    }
                )

    def list_results(self, tenant_id: str, device_id: str, limit: int) -> list[WindowResult]:
        """The latest `limit` windows, oldest first (same as InMemoryStore)."""
        resp = self.table.query(
            KeyConditionExpression=Key("PK").eq(self._pk(tenant_id, "DEVICE", device_id))
            & Key("SK").begins_with("RESULT#"),
            ScanIndexForward=False,
            Limit=limit,
        )
        return [WindowResult.model_validate_json(i["doc"]) for i in reversed(resp["Items"])]

    # --- idempotency --------------------------------------------------------------------

    def get_idempotent(self, tenant_id: str, key: str) -> tuple[str, dict] | None:
        pk = self._pk(tenant_id, "IDEM", key)
        item = self.table.get_item(Key={"PK": pk, "SK": "META"}).get("Item")
        # DynamoDB deletes expired items within a day or two, not on the second: check here.
        if not item or int(item["expires_at"]) < time.time():
            return None
        doc = json.loads(item["doc"])
        return doc["fingerprint"], doc["body"]

    def put_idempotent(self, tenant_id: str, key: str, fingerprint: str, body: dict) -> None:
        item = {
            "PK": self._pk(tenant_id, "IDEM", key),
            "SK": "META",
            "doc": json.dumps({"fingerprint": fingerprint, "body": body}),
            "expires_at": int(time.time()) + IDEMPOTENCY_TTL_S,
        }
        try:
            # Keep the first record if two requests with the same key race.
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(PK) OR expires_at < :now",
                ExpressionAttributeValues={":now": int(time.time())},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise


class S3BlobStore:
    """Raw recordings in S3. The phone uploads with a pre-signed PUT URL; the API never sees
    the bytes. Checking that a file arrived uses ListBucket, so the API's role does not need
    permission to read recordings (only the worker can)."""

    def __init__(self, bucket: str, region: str, client: Any = None) -> None:
        self.bucket = bucket
        self.s3 = client or boto3.client(
            "s3",
            region_name=region,
            config=Config(signature_version="s3v4", retries={"mode": "standard"}),
        )

    def presign_put(self, key: str, base_url: str, ttl_s: int) -> tuple[str, int]:
        expires = int(time.time()) + ttl_s
        url = self.s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": "application/json"},
            ExpiresIn=ttl_s,
        )
        return url, expires

    def exists(self, key: str) -> bool:
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=key, MaxKeys=1)
        return any(o["Key"] == key for o in resp.get("Contents", []))

    def size(self, key: str) -> int:
        return self.s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]

    def read(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def write(self, key: str, data: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/json")


def load_ssm_secrets(prefix: str, region: str) -> dict[str, str]:
    """Read SecureString parameters <prefix>/jwt-secret and <prefix>/clients (a JSON map)."""
    ssm = boto3.client("ssm", **_client_kwargs(region))
    names = [f"{prefix}/jwt-secret", f"{prefix}/clients"]
    resp = ssm.get_parameters(Names=names, WithDecryption=True)
    if resp["InvalidParameters"]:
        raise RuntimeError(f"Missing SSM parameters: {', '.join(resp['InvalidParameters'])}")
    values = {p["Name"].rsplit("/", 1)[1]: p["Value"] for p in resp["Parameters"]}
    return {"jwt_secret": values["jwt-secret"], "clients": values["clients"]}
