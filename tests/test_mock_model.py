import pytest

from stresskit_api import mock_model
from stresskit_sim import SCENARIOS, generate


@pytest.mark.parametrize("scenario", ["calm", "stressed"])
def test_heart_rate_is_close_to_simulated(scenario):
    rec = generate(scenario, minutes=1, seed=7)
    hr = mock_model.heart_rate_bpm(rec.ppg, rec.sample_rate_hz)
    assert abs(hr - SCENARIOS[scenario]["hr_bpm"]) <= 5


def test_partial_window_is_ignored():
    rec = generate("calm", minutes=2, seed=3)
    cut = rec.sample_rate_hz * 90
    assert len(mock_model.analyse(rec.ppg[:cut], rec.acc[:cut], rec.sample_rate_hz)) == 1


def test_flat_ppg_is_poor_signal():
    fs = 25
    out = mock_model.analyse([0.0] * fs * 60, [[0, 0, 1.0]] * fs * 60, fs)
    assert out[0].label == "na"
    assert out[0].signal_quality == "poor_signal"
