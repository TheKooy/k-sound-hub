from ksound_hub.audio.pipewire_v2_final import PipeWireAudioEngine
from ksound_hub.models import AppSettings


def _engine_for_native_state_test() -> PipeWireAudioEngine:
    engine = object.__new__(PipeWireAudioEngine)
    engine._find_channel = lambda settings, key: next(  # type: ignore[attr-defined]
        (channel for channel in settings.channels if channel.key == key),
        None,
    )
    engine._native_micro_source_for_channel = lambda _channel: "test_micro_source"  # type: ignore[attr-defined]
    engine._channel_send_gain_for_micro = lambda _settings, _key: 0.25  # type: ignore[attr-defined]
    return engine


def test_native_micro_state_includes_glass_micro_injection_sends() -> None:
    settings = AppSettings.default()
    settings.glass_micro_injection_channels = ["game", "chat", "invalid"]
    settings.glass_micro_injection_volume = 150

    text = PipeWireAudioEngine._render_native_micro_state_text(
        _engine_for_native_state_test(),
        settings,
    )

    assert "source\ttest_micro_source" in text
    assert "send\tchat\t1\tchat.monitor\t1.5000" in text
    assert "send\tgame\t1\tgame.monitor\t1.5000" in text
    assert "invalid" not in text


def test_native_micro_state_deduplicates_linked_and_injected_sends() -> None:
    settings = AppSettings.default()
    settings.glass_micro_injection_channels = ["chat"]
    settings.glass_micro_injection_volume = 150

    micro = next(channel for channel in settings.channels if channel.key == "micro")
    micro.linked_channels = ["chat"]

    text = PipeWireAudioEngine._render_native_micro_state_text(
        _engine_for_native_state_test(),
        settings,
    )

    assert text.count("send\tchat\t1\tchat.monitor\t1.5000") == 1
