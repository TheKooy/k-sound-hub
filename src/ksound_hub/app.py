from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .config import APP_NAME, ORG_DOMAIN, ORG_NAME
from .settings_store import SettingsStore
from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setOrganizationDomain(ORG_DOMAIN)

    store = SettingsStore()
    window = MainWindow(store)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
