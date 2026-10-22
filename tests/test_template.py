"""Milestone 4: checks on infra/template.yaml (SK-21, SK-22, SK-23, SK-29).

cfn-lint (in CI) checks the template is valid CloudFormation; these tests check it says what
the backlog promises: private storage, least privilege, pay-per-use, and everything tagged.
"""

from pathlib import Path

import pytest
import yaml

TEMPLATE = Path(__file__).resolve().parents[1] / "infra" / "template.yaml"


@pytest.fixture(scope="module")
def resources() -> dict:
    return yaml.safe_load(TEMPLATE.read_text())["Resources"]


def statements(role: dict) -> list[dict]:
    return [s for p in role["Properties"]["Policies"] for s in p["PolicyDocument"]["Statement"]]


def actions(role: dict) -> set[str]:
    out: set[str] = set()
    for s in statements(role):
        out |= {s["Action"]} if isinstance(s["Action"], str) else set(s["Action"])
    return out


def test_bucket_is_private_encrypted_and_https_only(resources):
    bucket = resources["RawBucket"]["Properties"]
    assert all(bucket["PublicAccessBlockConfiguration"].values())
    assert bucket["BucketEncryption"]["ServerSideEncryptionConfiguration"]
    deny = resources["RawBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"][0]
    assert deny["Effect"] == "Deny" and deny["Condition"]["Bool"]["aws:SecureTransport"] == "false"


def test_raw_recordings_expire(resources):
    rule = resources["RawBucket"]["Properties"]["LifecycleConfiguration"]["Rules"][0]
    assert rule["Status"] == "Enabled" and rule["ExpirationInDays"] == {"Ref": "RawRetentionDays"}
    # D15: files are ~100 KB, under S3's 128 KB minimum for cheaper tiers, so no transitions.
    assert "Transitions" not in rule


def test_table_is_on_demand_with_ttl_and_backups(resources):
    table = resources["Table"]["Properties"]
    assert table["BillingMode"] == "PAY_PER_REQUEST"
    assert table["TimeToLiveSpecification"] == {"AttributeName": "expires_at", "Enabled": True}
    assert table["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert [k["AttributeName"] for k in table["KeySchema"]] == ["PK", "SK"]


def test_no_wildcard_actions_or_resources(resources):
    for name in ("ApiRole", "WorkerRole"):
        for s in statements(resources[name]):
            assert "*" not in str(s["Action"]), name
            assert s["Resource"] != "*", name


def test_api_cannot_read_recordings_and_worker_cannot_read_secrets(resources):
    api, worker = actions(resources["ApiRole"]), actions(resources["WorkerRole"])
    assert "s3:GetObject" not in api
    assert {"s3:PutObject", "s3:ListBucket", "ssm:GetParameters"} <= api
    assert not any(a.startswith("ssm:") for a in worker)
    assert "s3:PutObject" not in worker and "s3:GetObject" in worker
    assert not any(a.startswith(("dynamodb:Delete", "dynamodb:Scan")) for a in api | worker)


def test_no_always_on_compute(resources):
    # SK-29: nothing that bills by the hour. Lambda and API Gateway come in milestone 5.
    hourly = ("AWS::EC2::", "AWS::RDS::", "AWS::ElastiCache::", "AWS::EKS::", "AWS::ECS::")
    assert not [r for r in resources.values() if r["Type"].startswith(hourly)]


def test_every_resource_that_takes_tags_is_tagged(resources):
    for name, r in resources.items():
        if r["Type"] == "AWS::S3::BucketPolicy":
            continue  # bucket policies cannot be tagged
        tags = {t["Key"]: t["Value"] for t in r["Properties"]["Tags"]}
        assert tags.get("project") == "stresskit-demo", name
