from types import SimpleNamespace

from ksound_hub.audio.pipewire_v2_final import PipeWireAudioEngine
from ksound_hub.models import AppSettings, ChannelConfig


def test_channel_config_stereo_width_roundtrip_and_clamp() -> None:
    channel = ChannelConfig.from_dict({"key": "game", "name": "GAME", "stereo_width": 137})
    assert channel.stereo_width == 100
    assert channel.to_dict()["stereo_width"] == 100

    channel = ChannelConfig.from_dict({"key": "game", "name": "GAME", "stereo_width": -20})
    assert channel.stereo_width == 0


def test_native_playback_state_includes_stereo_width() -> None:
    settings = AppSettings.default()
    game = next(channel for channel in settings.channels if channel.key == "game")
    game.primary_target = "alsa_output.test"
    game.stereo_width = 75

    engine = object.__new__(PipeWireAudioEngine)
    engine._find_channel = lambda loaded, key: next((channel for channel in loaded.channels if channel.key == key), None)  # type: ignore[attr-defined]
    engine._resolve_playback_target = lambda _channel: SimpleNamespace(label="alsa_output.test", sink_name="alsa_output.test")  # type: ignore[attr-defined]

    text = PipeWireAudioEngine._render_state_text(engine, settings)
    assert "channel\tgame\t1\t0\t100\talsa_output.test\talsa_output.test\t" in text
    assert "\t75\n" in text
