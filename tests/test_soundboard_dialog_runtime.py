from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_soundboard_dialog_constructs_after_route_controls():
    from PySide6.QtWidgets import QApplication

    from ksound_hub.ui.soundboard_dialog import SoundboardDialog

    app = QApplication.instance() or QApplication([])
    state = {"monitor_to_mic_out": True, "send_to_micro": False}

    def provider():
        return dict(state)

    def changed(route_key: str, enabled: bool) -> bool:
        state[route_key] = bool(enabled)
        return True

    dialog = SoundboardDialog(route_state_provider=provider, route_state_changed=changed)
    try:
        assert dialog.windowTitle()
        assert hasattr(dialog, "status_label")
        assert hasattr(dialog, "volume_bar")
        assert hasattr(dialog, "global_volume_slider")
        assert dialog.volume_bar.objectName() == "soundboardVolumeBar"
        assert dialog.global_volume_slider.minimumWidth() >= 240
        assert hasattr(dialog, "monitor_to_mic_out_check")
        assert hasattr(dialog, "send_to_micro_check")
        assert hasattr(dialog, "_load_monitor_to_mic_out")
        assert hasattr(dialog, "_load_send_to_micro")
        assert hasattr(dialog, "refresh_route_controls")
        assert not hasattr(dialog, "output_target_combo")
        assert dialog.monitor_to_mic_out_check.isChecked() is True
        dialog.send_to_micro_check.setChecked(True)
        assert state["send_to_micro"] is True
    finally:
        dialog.close()
        dialog.deleteLater()
