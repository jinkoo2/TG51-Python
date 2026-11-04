"""Launch the TG-51 window."""

from __future__ import annotations

import sys

from .app_settings import ensure_settings_file, load_settings


def main() -> None:
    from PyQt5.QtWidgets import QApplication

    from .gui import MainWindow, themed_font

    ensure_settings_file()
    app = QApplication(sys.argv)
    app.setFont(themed_font(app.font(), load_settings()))
    window = MainWindow()
    window.resize(1100, 720)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
