from ksound_hub.ui.widgets import _meter_visual_level


def test_meter_visual_level_boosts_low_signals():
    assert _meter_visual_level(0.0) == 0.0
    assert _meter_visual_level(1.0) == 1.0

    low = _meter_visual_level(0.08)
    mid = _meter_visual_level(0.25)
    high = _meter_visual_level(0.64)

    assert low > 0.08
    assert mid > 0.25
    assert high > 0.64
    assert 0.0 < low < mid < high <= 1.0
