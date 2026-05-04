import json

from ksound_hub.audio.pipewire import (
    PlaybackTarget,
    SinkInputBlock,
    _build_eq_slot_signature,
    _build_eq_slot_status,
    _build_stream_display_name,
    _resolved_channel_node_volume,
)
from ksound_hub.models import EqBand, EqProfile


def test_resolved_channel_node_volume():
    assert _resolved_channel_node_volume(120, node_type="sink", node_name="all") == 120
    assert _resolved_channel_node_volume(120, node_type="sink", node_name="retour") == 180
    assert _resolved_channel_node_volume(120, node_type="source", node_name="alsa_input.usb-test") == 100
    assert _resolved_channel_node_volume(-10, node_type="sink", node_name="all") == 0


def test_build_stream_display_name_filters_internal_streams():
    firefox = SinkInputBlock(
        sink_input_id=91,
        media_name="YouTube",
        app_name="Firefox",
        binary_name="firefox",
    )
    internal = SinkInputBlock(
        sink_input_id=92,
        media_name="K-Sound Hub Return Mic Playback",
        app_name="",
        binary_name="",
    )

    assert _build_stream_display_name(firefox) == "Firefox — YouTube"
    assert _build_stream_display_name(internal) is None


def test_build_eq_slot_signature_and_status():
    profile = EqProfile(name="Cinema", bands=[EqBand(frequency=1000.0, gain_db=1.5, q=0.8)])
    target = PlaybackTarget(label="System default", sink_name="alsa_output.test")

    signature = json.loads(_build_eq_slot_signature("media", profile, target))
    status = _build_eq_slot_status(profile_name="Cinema", target_label="System default", muted=False, volume=85)

    assert signature["key"] == "media"
    assert signature["target_label"] == "System default"
    assert signature["target_sink"] == "alsa_output.test"
    assert signature["profile"]["name"] == "Cinema"
    assert status == "active (Cinema → System default) • vol 85%"
