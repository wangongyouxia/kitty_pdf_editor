"""Entry point for the PDF editor."""

from __future__ import annotations

import os
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtWidgets import QApplication

from app.dialogs import _resource_path
from app.i18n import install_dialog_translation, load_lang
from app.main_window import MainWindow


def main() -> int:
    # Enable high-DPI pixmaps for crisp page rendering.
    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setOrganizationName("LocalTools")
    app.setApplicationName("PDFEditor")
    load_lang()
    install_dialog_translation()
    for rel in ("app/cat.ico", "app/cat.png"):
        p = _resource_path(rel)
        if os.path.isfile(p):
            app.setWindowIcon(QIcon(p))
            break

    win = MainWindow()
    win.show()

    # Open file from CLI: pdf_editor.exe path/to/file.pdf
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if args:
        win.open_document(args[0])

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
