"""A deliberately simple stand-in for the stress model.

It runs per 60-second window:
1. Motion check: if the accelerometer magnitude varies a lot, PPG is unreliable, so the
   window is `na` with signal_quality "motion". Real wearables do the same gating.
2. Heart rate from PPG: count pulse peaks in the window.
3. Label: heart rate above 90 bpm is `stressed`.

A real model would use heart-rate variability (HRV), skin temperature, EDA and a trained
classifier. The contract (one label per window, with signal quality and model version) is
what matters for the system design; the model can change behind it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

MODEL_VERSION = "mock-hr-threshold-0.1"
WINDOW_S = 60
MOTION_STD_G = 0.15
STRESS_HR_BPM = 90.0
MIN_HR_BPM, MAX_HR_BPM = 40.0, 180.0


@dataclass(frozen=True)
class WindowOutput:
    index: int
    label: str
    heart_rate_bpm: float | None
    signal_quality: str


def _std(xs: Sequence[float]) -> float:
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / len(xs))


def heart_rate_bpm(ppg: Sequence[float], fs: int) -> float:
    """Count local maxima above the mean, at least 1/3 s apart (caps at 180 bpm)."""
    mean = sum(ppg) / len(ppg)
    threshold = mean + 0.3 * _std(ppg)
    refractory = max(1, int(fs / 3))
    peaks, last = 0, -refractory
    for i in range(1, len(ppg) - 1):
        if ppg[i] > threshold and ppg[i] > ppg[i - 1] and ppg[i] >= ppg[i + 1]:
            if i - last >= refractory:
                peaks += 1
                last = i
    return peaks * 60.0 * fs / len(ppg)


def analyse(ppg: Sequence[float], acc: Sequence[Sequence[float]], fs: int) -> list[WindowOutput]:
    n = fs * WINDOW_S
    outputs = []
    for w in range(min(len(ppg), len(acc)) // n):
        ppg_w = ppg[w * n : (w + 1) * n]
        mag = [math.sqrt(x * x + y * y + z * z) for x, y, z in acc[w * n : (w + 1) * n]]
        if _std(mag) > MOTION_STD_G:
            outputs.append(WindowOutput(w, "na", None, "motion"))
            continue
        hr = round(heart_rate_bpm(ppg_w, fs), 1)
        if not MIN_HR_BPM <= hr <= MAX_HR_BPM:
            outputs.append(WindowOutput(w, "na", None, "poor_signal"))
            continue
        label = "stressed" if hr > STRESS_HR_BPM else "not_stressed"
        outputs.append(WindowOutput(w, label, hr, "good"))
    return outputs
