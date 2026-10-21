"""Mock wearable: generates PPG + 3-axis accelerometer recordings.

PPG (photoplethysmography) is the green-light pulse sensor on the back of a watch: each
heartbeat makes a bump. ACC is the accelerometer in g; at rest it reads about 1 g (gravity).

Scenarios:
    calm      resting, heart rate about 68 bpm      -> not_stressed
    stressed  sitting still, heart rate about 105   -> stressed
    moving    walking, accelerometer shakes         -> na (motion)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

SCENARIOS = {
    "calm": {"hr_bpm": 68.0, "acc_noise_g": 0.02},
    "stressed": {"hr_bpm": 105.0, "acc_noise_g": 0.02},
    "moving": {"hr_bpm": 85.0, "acc_noise_g": 0.35},
}


@dataclass
class Recording:
    sample_rate_hz: int
    ppg: list[float]
    acc: list[list[float]]

    @property
    def duration_s(self) -> int:
        return len(self.ppg) // self.sample_rate_hz

    def to_json(self) -> dict:
        return {"sample_rate_hz": self.sample_rate_hz, "ppg": self.ppg, "acc": self.acc}


def generate(scenario: str, minutes: int = 2, fs: int = 25, seed: int | None = None) -> Recording:
    if scenario not in SCENARIOS:
        raise ValueError(f"scenario must be one of {sorted(SCENARIOS)}")
    p = SCENARIOS[scenario]
    rng = random.Random(seed)
    beat_hz = p["hr_bpm"] / 60.0
    ppg, acc = [], []
    phase = 0.0
    for i in range(minutes * 60 * fs):
        # Small beat-to-beat variation so the pulse is not a perfect sine wave.
        phase += 2 * math.pi * beat_hz * (1 + rng.gauss(0, 0.02)) / fs
        pulse = math.sin(phase) + 0.25 * math.sin(2 * phase + 0.6)
        ppg.append(round(pulse + rng.gauss(0, 0.05), 4))
        n = p["acc_noise_g"]
        step = 0.4 * math.sin(2 * math.pi * 1.8 * i / fs) if scenario == "moving" else 0.0
        acc.append(
            [
                round(rng.gauss(0, n), 4),
                round(rng.gauss(0, n), 4),
                round(1.0 + step + rng.gauss(0, n), 4),
            ]
        )
    return Recording(fs, ppg, acc)
