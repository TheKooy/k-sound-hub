from __future__ import annotations

from ksound_hub.models import EqProfile


def test_default_eq_profile_uses_ten_bands():
    profile = EqProfile.default()

    assert len(profile.bands) == 10
    assert [band.frequency for band in profile.bands] == [
        32.0,
        64.0,
        125.0,
        250.0,
        500.0,
        1000.0,
        2000.0,
        4000.0,
        8000.0,
        16000.0,
    ]


def test_old_eight_band_profile_is_upgraded_to_ten_bands():
    profile = EqProfile.from_dict(
        {
            "name": "Old custom",
            "bands": [
                {"frequency": 60.0, "gain_db": -1.0, "q": 1.0},
                {"frequency": 170.0, "gain_db": 0.0, "q": 1.0},
                {"frequency": 310.0, "gain_db": 1.0, "q": 1.0},
                {"frequency": 600.0, "gain_db": 2.0, "q": 1.0},
                {"frequency": 1000.0, "gain_db": 1.5, "q": 1.0},
                {"frequency": 3000.0, "gain_db": 0.5, "q": 1.0},
                {"frequency": 6000.0, "gain_db": -0.5, "q": 1.0},
                {"frequency": 12000.0, "gain_db": -1.0, "q": 1.0},
            ],
        }
    )

    assert profile.name == "Old custom"
    assert len(profile.bands) == 10
    assert profile.bands[0].frequency == 32.0
    assert profile.bands[-1].frequency == 16000.0
    assert all((band.gain_db * 2).is_integer() for band in profile.bands)


def test_custom_ten_band_frequencies_are_preserved():
    profile = EqProfile.from_dict(
        {
            "name": "Custom frequencies",
            "bands": [
                {"frequency": 40.0, "gain_db": 0.5, "q": 1.0},
                {"frequency": 80.0, "gain_db": 1.0, "q": 1.0},
                {"frequency": 160.0, "gain_db": 1.5, "q": 1.0},
                {"frequency": 320.0, "gain_db": 2.0, "q": 1.0},
                {"frequency": 640.0, "gain_db": 2.5, "q": 1.0},
                {"frequency": 1280.0, "gain_db": 3.0, "q": 1.0},
                {"frequency": 2560.0, "gain_db": 2.5, "q": 1.0},
                {"frequency": 5120.0, "gain_db": 2.0, "q": 1.0},
                {"frequency": 10240.0, "gain_db": 1.5, "q": 1.0},
                {"frequency": 18000.0, "gain_db": 1.0, "q": 1.0},
            ],
        }
    )

    assert [band.frequency for band in profile.bands] == [
        40.0,
        80.0,
        160.0,
        320.0,
        640.0,
        1280.0,
        2560.0,
        5120.0,
        10240.0,
        18000.0,
    ]
    assert profile.bands[0].gain_db == 0.5
