from ksound_hub.audio.pipewire import (
    _clamp_int,
    _parse_loopback_module_ids_from_short_modules,
    _parse_short_audio_nodes,
    _parse_sink_input_blocks,
)


def test_parse_short_audio_nodes():
    lines = [
        "42 all module-null-sink.c s16le 2ch 48000Hz SUSPENDED",
        "43 game module-null-sink.c s16le 2ch 48000Hz RUNNING",
    ]

    nodes = _parse_short_audio_nodes(lines, "sink")

    assert [node.name for node in nodes] == ["all", "game"]
    assert [node.kind for node in nodes] == ["sink", "sink"]
    assert [node.state for node in nodes] == ["SUSPENDED", "RUNNING"]


def test_parse_loopback_module_ids_from_short_modules():
    lines = [
        "536870925 module-loopback source=retour.monitor sink=alsa_output.usb-Generic_USB_Audio-00.HiFi__SPDIF__sink latency_msec=20 sink_input_properties=media.name=K-Sound Hub Return Mic Playback",
        "536870926 module-loopback source=micro sink=retour latency_msec=20 sink_input_properties=media.name=K-Sound Hub Return Mic Capture",
        "536870927 module-null-sink sink_name=ignore_me",
    ]

    by_route = _parse_loopback_module_ids_from_short_modules(
        lines,
        source_name="micro",
        sink_name="retour",
    )
    by_media = _parse_loopback_module_ids_from_short_modules(
        lines,
        media_name="K-Sound Hub Return Mic Playback",
    )

    assert by_route == ["536870926"]
    assert by_media == ["536870925"]


def test_parse_sink_input_blocks_and_clamp():
    lines = [
        "Sink Input #91",
        '    application.name = "Firefox"',
        '    media.name = "YouTube"',
        '    application.process.binary = "firefox"',
        "    Mute: no",
        "Sink Input #92",
        '    media.name = "K-Sound Hub Return Mic Playback"',
        "    Mute: yes",
    ]

    blocks = _parse_sink_input_blocks(lines)

    assert [block.sink_input_id for block in blocks] == [91, 92]
    assert blocks[0].app_name == "Firefox"
    assert blocks[0].media_name == "YouTube"
    assert blocks[0].binary_name == "firefox"
    assert blocks[0].muted is False
    assert blocks[1].media_name == "K-Sound Hub Return Mic Playback"
    assert blocks[1].muted is True

    assert _clamp_int(-5, 0, 150) == 0
    assert _clamp_int(77, 0, 150) == 77
    assert _clamp_int(999, 0, 150) == 150
