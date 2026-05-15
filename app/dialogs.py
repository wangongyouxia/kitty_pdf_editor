"""Reusable dialogs for the PDF editor."""

from __future__ import annotations

from typing import Optional

import os
from .i18n import apply_language, tr
from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QSize, Qt
from PyQt6.QtGui import QColor, QImage, QIntValidator, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


def color_picker_button(initial_qcolor) -> tuple[QPushButton, list]:
    """Return a button that opens a colour picker; carries selected color in list."""
    btn = QPushButton()
    state = [initial_qcolor]

    def refresh():
        btn.setStyleSheet(
            f"background-color: rgba({state[0].red()},{state[0].green()},{state[0].blue()},{state[0].alpha()}); min-width: 80px;"
        )
        btn.setText(state[0].name())

    def choose():
        c = QColorDialog.getColor(state[0], None, "选择颜色",
                                   options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if c.isValid():
            state[0] = c
            refresh()

    btn.clicked.connect(choose)
    refresh()
    return btn, state


class WatermarkDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("水印")
        layout = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(["文字", "图片"])
        self.text = QLineEdit("DRAFT")
        self.image_path = QLineEdit()
        browse = QPushButton("浏览…")
        img_row = QWidget()
        h = QHBoxLayout(img_row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.image_path)
        h.addWidget(browse)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.05, 1.0)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(0.25)
        self.size = QDoubleSpinBox()
        self.size.setRange(8, 400)
        self.size.setValue(60)
        self.rotation = QSpinBox()
        self.rotation.setRange(0, 360)
        self.rotation.setSingleStep(45)
        self.rotation.setValue(45)
        self.scope = QLineEdit()
        self.scope.setPlaceholderText("全部页（或 1-3,5,7-9）")
        layout.addRow("类型：", self.mode)
        layout.addRow("文字：", self.text)
        layout.addRow("图片：", img_row)
        layout.addRow("不透明度：", self.opacity)
        layout.addRow("字号：", self.size)
        layout.addRow("旋转（文字）：", self.rotation)
        layout.addRow("页面：", self.scope)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "选择图片", "",
                                                "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
            if p:
                self.image_path.setText(p)

        browse.clicked.connect(pick)

    def values(self) -> dict:
        return {
            "mode": self.mode.currentText(),
            "text": self.text.text(),
            "image_path": self.image_path.text(),
            "opacity": self.opacity.value(),
            "size": self.size.value(),
            "rotation": self.rotation.value(),
            "scope": self.scope.text().strip(),
        }


class PageNumbersDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加页码")
        layout = QFormLayout(self)
        self.position = QComboBox()
        self.position.addItems([
            "bottom-center", "bottom-left", "bottom-right",
            "top-center", "top-left", "top-right",
        ])
        self.fmt = QLineEdit("{page} / {total}")
        self.size = QDoubleSpinBox()
        self.size.setRange(6, 36)
        self.size.setValue(10)
        self.start_at = QSpinBox()
        self.start_at.setRange(1, 10000)
        self.start_at.setValue(1)
        layout.addRow("位置：", self.position)
        layout.addRow("格式：", self.fmt)
        layout.addRow("字号：", self.size)
        layout.addRow("起始页码：", self.start_at)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)


class HeaderFooterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("页眉 / 页脚")
        layout = QFormLayout(self)
        self.header = QLineEdit()
        self.footer = QLineEdit()
        self.size = QDoubleSpinBox()
        self.size.setRange(6, 36)
        self.size.setValue(10)
        layout.addRow("页眉：", self.header)
        layout.addRow("页脚：", self.footer)
        layout.addRow("字号：", self.size)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)


class SplitDialog(QDialog):
    def __init__(self, max_pages: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("拆分 PDF")
        self.max_pages = max_pages
        layout = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItems(["每 N 页拆分", "自定义范围"])
        self.n = QSpinBox()
        self.n.setRange(1, max_pages)
        self.n.setValue(1)
        self.ranges = QLineEdit("1-{}".format(max_pages))
        self.ranges.setPlaceholderText("例如 1-3,5,7-{}".format(max_pages))
        layout.addRow("方式：", self.mode)
        layout.addRow("N：", self.n)
        layout.addRow("范围：", self.ranges)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)


class EncryptDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("加密 PDF")
        layout = QFormLayout(self)
        self.user_pw = QLineEdit()
        self.user_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.owner_pw = QLineEdit()
        self.owner_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.allow_print = QCheckBox("允许打印")
        self.allow_print.setChecked(True)
        self.allow_copy = QCheckBox("允许复制文字")
        self.allow_copy.setChecked(True)
        self.allow_modify = QCheckBox("允许修改")
        self.allow_modify.setChecked(False)
        self.allow_annot = QCheckBox("允许添加注解")
        self.allow_annot.setChecked(True)
        layout.addRow("用户密码：", self.user_pw)
        layout.addRow("所有者密码：", self.owner_pw)
        layout.addRow(self.allow_print)
        layout.addRow(self.allow_copy)
        layout.addRow(self.allow_modify)
        layout.addRow(self.allow_annot)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)


class MetadataDialog(QDialog):
    def __init__(self, metadata: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("文档属性")
        layout = QFormLayout(self)
        self.title = QLineEdit(metadata.get("title", "") or "")
        self.author = QLineEdit(metadata.get("author", "") or "")
        self.subject = QLineEdit(metadata.get("subject", "") or "")
        self.keywords = QLineEdit(metadata.get("keywords", "") or "")
        self.creator = QLineEdit(metadata.get("creator", "") or "")
        self.producer = QLineEdit(metadata.get("producer", "") or "")
        for label, widget in [("标题", self.title), ("作者", self.author),
                               ("主题", self.subject), ("关键词", self.keywords),
                               ("创建程序", self.creator), ("生成程序", self.producer)]:
            layout.addRow(label + "：", widget)
        info = QLabel(
            f"格式：{metadata.get('format', '')}\n"
            f"加密：{metadata.get('encryption', 'None')}\n"
            f"创建时间：{metadata.get('creationDate', '')}\n"
            f"修改时间：{metadata.get('modDate', '')}"
        )
        info.setStyleSheet("color: #666;")
        layout.addRow(info)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> dict:
        return {
            "title": self.title.text(),
            "author": self.author.text(),
            "subject": self.subject.text(),
            "keywords": self.keywords.text(),
            "creator": self.creator.text(),
            "producer": self.producer.text(),
        }


class FormFieldsDialog(QDialog):
    def __init__(self, fields: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("表单字段")
        self.resize(520, 420)
        layout = QVBoxLayout(self)
        self.list = QListWidget(self)
        self._editors: dict[int, QLineEdit] = {}
        for idx, f in enumerate(fields):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(4, 2, 4, 2)
            h.addWidget(QLabel(f"第 {f['page']+1} 页"))
            h.addWidget(QLabel(f["name"] or "（未命名）"))
            h.addWidget(QLabel(f["type"]))
            edit = QLineEdit(str(f["value"] or ""))
            self._editors[idx] = edit
            h.addWidget(edit, 1)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        layout.addWidget(self.list)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self.fields = fields

    def values(self) -> dict[int, str]:
        return {i: e.text() for i, e in self._editors.items()}


class InsertPagesDialog(QDialog):
    def __init__(self, current_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("从 PDF 插入页面")
        layout = QFormLayout(self)
        self.path = QLineEdit()
        browse = QPushButton("浏览…")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.path)
        h.addWidget(browse)
        self.ranges = QLineEdit("all")
        self.ranges.setPlaceholderText("'all' 或例如 1-3,5")
        self.at = QSpinBox()
        self.at.setRange(0, current_count)
        self.at.setValue(current_count)
        layout.addRow("PDF 文件：", row)
        layout.addRow("页面：", self.ranges)
        layout.addRow("插入到（0=开头）：", self.at)
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

        def pick():
            p, _ = QFileDialog.getOpenFileName(self, "选择 PDF", "", "PDF (*.pdf)")
            if p:
                self.path.setText(p)
        browse.clicked.connect(pick)


class EditTextDialog(QDialog):
    """Inline editor for an existing PDF text span.

    Shows the original text read-only and lets the user supply a
    replacement string plus font / colour overrides. The OK result is
    available via `values()`.
    """

    FAMILIES = [
        ("无衬线（Helvetica）", "helv"),
        ("衬线（Times）", "tiro"),
        ("等宽（Courier）", "cour"),
    ]

    def __init__(self, span, suggested_alias: str, suggested_bg, parent=None):
        super().__init__(parent)
        from PyQt6.QtGui import QColor  # avoid top-level dep cycle in header
        self.setWindowTitle("编辑文字")
        self.resize(520, 360)
        layout = QFormLayout(self)

        self.orig = QTextEdit()
        self.orig.setReadOnly(True)
        self.orig.setPlainText(span.text)
        self.orig.setMaximumHeight(80)
        layout.addRow("原文：", self.orig)

        self.new = QTextEdit()
        self.new.setPlainText(span.text)
        layout.addRow("新文字：", self.new)

        # Font family
        self.family = QComboBox()
        for label, alias in self.FAMILIES:
            self.family.addItem(label, alias)
        # Pick the suggested alias' family
        base = suggested_alias[:2] if len(suggested_alias) >= 2 else "he"
        if base == "co":
            self.family.setCurrentIndex(2)
        elif base == "ti":
            self.family.setCurrentIndex(1)
        else:
            self.family.setCurrentIndex(0)
        layout.addRow("字体：", self.family)

        # Bold / Italic
        style_row = QWidget()
        srh = QHBoxLayout(style_row)
        srh.setContentsMargins(0, 0, 0, 0)
        self.bold = QCheckBox("粗体")
        self.italic = QCheckBox("斜体")
        self.bold.setChecked(suggested_alias[-2:] in ("bo", "bi"))
        self.italic.setChecked(suggested_alias[-2:] in ("it", "bi"))
        srh.addWidget(self.bold)
        srh.addWidget(self.italic)
        srh.addStretch(1)
        layout.addRow("样式：", style_row)

        # Size
        self.size = QDoubleSpinBox()
        self.size.setRange(4.0, 144.0)
        self.size.setSingleStep(0.5)
        self.size.setValue(float(span.size))
        layout.addRow("字号：", self.size)

        # Text colour
        r, g, b = span.color_rgb
        text_qc = QColor(int(r * 255), int(g * 255), int(b * 255))
        self.text_color_btn, self.text_color_state = color_picker_button(text_qc)
        layout.addRow("文字颜色：", self.text_color_btn)

        # Background colour
        br, bg_, bb = suggested_bg
        bg_qc = QColor(int(br * 255), int(bg_ * 255), int(bb * 255))
        self.bg_color_btn, self.bg_color_state = color_picker_button(bg_qc)
        layout.addRow("背景遮盖：", self.bg_color_btn)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> dict:
        family_alias = self.family.currentData()
        bold = self.bold.isChecked()
        italic = self.italic.isChecked()
        # Build alias from family + style
        base = family_alias[:2]  # he / ti / co
        if bold and italic:
            suffix = "bi"
        elif bold:
            suffix = "bo"
        elif italic:
            suffix = "it"
        else:
            suffix = "lv" if base == "he" else ("ro" if base == "ti" else "ur")
        if base == "he":
            alias = "helv" if suffix == "lv" else f"he{suffix}"
        elif base == "ti":
            alias = "tiro" if suffix == "ro" else f"ti{suffix}"
        else:
            alias = "cour" if suffix == "ur" else f"co{suffix}"

        def qc_to_rgb(qc):
            return (qc.redF(), qc.greenF(), qc.blueF())

        return {
            "text": self.new.toPlainText(),
            "font_alias": alias,
            "font_size": self.size.value(),
            "text_color": qc_to_rgb(self.text_color_state[0]),
            "background": qc_to_rgb(self.bg_color_state[0]),
        }


class SignatureCanvas(QWidget):
    """A small drawing surface for the user to sketch a signature with
    the mouse.  Strokes are stored on a transparent QImage so the
    resulting PNG can be inserted as an image annotation on the page.
    """

    def __init__(self, parent=None, *, width: int = 500, height: int = 170):
        super().__init__(parent)
        self._default_size = QSize(width, height)
        self.setMinimumSize(width, height)
        self.setStyleSheet(
            "background-color: white; border: 1px dashed rgb(150,150,150);"
        )
        self._image = QImage(width, height, QImage.Format.Format_ARGB32)
        self._image.fill(Qt.GlobalColor.transparent)
        self._drawing = False
        self._last_pt: QPoint = QPoint()
        self._pen_color = QColor(0, 0, 0)
        self._pen_width = 3

    def set_pen_width(self, width: int) -> None:
        self._pen_width = max(1, int(width))

    def set_pen_color(self, color: QColor) -> None:
        self._pen_color = QColor(color)

    def is_empty(self) -> bool:
        # Cheap check: scan a 32-step grid for any non-transparent pixel.
        w, h = self._image.width(), self._image.height()
        if w == 0 or h == 0:
            return True
        step_x = max(1, w // 32)
        step_y = max(1, h // 32)
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                if self._image.pixelColor(x, y).alpha() != 0:
                    return False
        return True

    def clear(self) -> None:
        self._image.fill(Qt.GlobalColor.transparent)
        self.update()

    def resizeEvent(self, event) -> None:
        if event.size().width() > self._image.width() or event.size().height() > self._image.height():
            new_img = QImage(max(event.size().width(), self._image.width()),
                              max(event.size().height(), self._image.height()),
                              QImage.Format.Format_ARGB32)
            new_img.fill(Qt.GlobalColor.transparent)
            painter = QPainter(new_img)
            painter.drawImage(0, 0, self._image)
            painter.end()
            self._image = new_img
        super().resizeEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = True
            self._last_pt = event.position().toPoint()

    def mouseMoveEvent(self, event) -> None:
        if not self._drawing:
            return
        painter = QPainter(self._image)
        pen = QPen(self._pen_color, self._pen_width,
                   Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cur = event.position().toPoint()
        painter.drawLine(self._last_pt, cur)
        painter.end()
        self._last_pt = cur
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drawing = False

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.drawImage(0, 0, self._image)

    def to_png_bytes(self) -> bytes:
        # Crop to the actual drawn area to avoid huge transparent borders.
        cropped = self._cropped_image()
        if cropped is None:
            return b""
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        cropped.save(buf, "PNG")
        ba: QByteArray = buf.data()
        return bytes(ba)

    def _cropped_image(self):
        img = self._image
        w, h = img.width(), img.height()
        x0, y0, x1, y1 = w, h, 0, 0
        found = False
        # Sample stride for speed
        step = max(1, w // 200, h // 200)
        for y in range(0, h, step):
            for x in range(0, w, step):
                if img.pixelColor(x, y).alpha() != 0:
                    found = True
                    x0 = min(x0, x)
                    y0 = min(y0, y)
                    x1 = max(x1, x)
                    y1 = max(y1, y)
        if not found:
            return None
        pad = 6
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(w - 1, x1 + pad); y1 = min(h - 1, y1 + pad)
        return img.copy(x0, y0, x1 - x0 + 1, y1 - y0 + 1)


class SignatureDialog(QDialog):
    """Compose a signature: either hand-draw it or load an image file.

    On success, `image_bytes()` returns PNG bytes ready to insert via
    `Page.insert_image(rect, stream=bytes)`.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("插入签名")
        self.resize(580, 360)
        self._result_bytes: bytes = b""

        outer = QVBoxLayout(self)
        tabs = QTabWidget()
        outer.addWidget(tabs)

        # --- Draw tab ---
        draw_tab = QWidget()
        dl = QVBoxLayout(draw_tab)
        dl.addWidget(QLabel("在下方用鼠标画签名："))
        self.canvas = SignatureCanvas(width=540, height=170)
        dl.addWidget(self.canvas)
        row = QHBoxLayout()
        row.addWidget(QLabel("笔粗："))
        self.width_slider = QSlider(Qt.Orientation.Horizontal)
        self.width_slider.setRange(1, 12)
        self.width_slider.setValue(3)
        self.width_slider.valueChanged.connect(self.canvas.set_pen_width)
        row.addWidget(self.width_slider, 1)
        color_btn = QPushButton()
        color_state = [QColor(0, 0, 0)]
        color_btn.setStyleSheet("background-color: black; min-width: 60px;")

        def pick_color():
            c = QColorDialog.getColor(color_state[0], self, "选择签名颜色")
            if c.isValid():
                color_state[0] = c
                color_btn.setStyleSheet(
                    f"background-color: rgb({c.red()},{c.green()},{c.blue()}); min-width: 60px;"
                )
                self.canvas.set_pen_color(c)

        color_btn.clicked.connect(pick_color)
        row.addWidget(QLabel(" 颜色："))
        row.addWidget(color_btn)
        clear_btn = QPushButton("清除")
        clear_btn.clicked.connect(self.canvas.clear)
        row.addWidget(clear_btn)
        dl.addLayout(row)
        tabs.addTab(draw_tab, "手绘签名")

        # --- Load file tab ---
        file_tab = QWidget()
        fl = QVBoxLayout(file_tab)
        fl.addWidget(QLabel("从图片文件加载签名（建议为透明背景的 PNG）："))
        row2 = QHBoxLayout()
        self.path_label = QLabel("（未选择）")
        self.path_label.setStyleSheet("color: #666;")
        row2.addWidget(self.path_label, 1)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse)
        row2.addWidget(browse_btn)
        fl.addLayout(row2)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(
            "background-color: white; border: 1px dashed rgb(150,150,150); min-height: 150px;"
        )
        fl.addWidget(self.preview, 1)
        tabs.addTab(file_tab, "从文件加载")

        self._tabs = tabs
        self._file_path: str | None = None

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("插入")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

    def _browse(self) -> None:
        p, _ = QFileDialog.getOpenFileName(
            self, "选择签名图片", "",
            "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not p:
            return
        self._file_path = p
        self.path_label.setText(p)
        self.path_label.setStyleSheet("color: #222;")
        pix = QPixmap(p)
        if not pix.isNull():
            self.preview.setPixmap(pix.scaled(
                500, 150,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def _on_accept(self) -> None:
        if self._tabs.currentIndex() == 0:
            data = self.canvas.to_png_bytes()
            if not data:
                QMessageBox.warning(self, "签名", "请先在画布上画签名。")
                return
            self._result_bytes = data
        else:
            if not self._file_path:
                QMessageBox.warning(self, "签名", "请选择签名图片文件。")
                return
            try:
                with open(self._file_path, "rb") as f:
                    self._result_bytes = f.read()
            except Exception as exc:
                QMessageBox.critical(self, "签名", f"读取文件失败：{exc}")
                return
        self.accept()

    def image_bytes(self) -> bytes:
        return self._result_bytes


def _bundled_path(rel: str) -> str:
    """Read-only path of a resource shipped *inside* the app.

    In a PyInstaller onefile build the resources are unpacked into a
    temp directory referenced by `sys._MEIPASS`.  That dir is wiped on
    exit, so it must only be used for files we DON'T need to persist.
    """
    import sys as _sys
    base = getattr(_sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, rel)
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", rel))


def _user_path(rel: str) -> str:
    """Writable path for files the user customises at runtime.

    For frozen builds we use a folder next to the executable so the
    image survives across launches even though `_MEIPASS` is wiped.
    """
    import sys as _sys
    if getattr(_sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(_sys.executable))
        return os.path.normpath(os.path.join(exe_dir, rel))
    return _bundled_path(rel)


def _resource_path(rel: str) -> str:
    """Read-first lookup: prefer the user-customised file, fall back to
    whatever was bundled.  Returns the *user* path when neither exists
    so callers can show "save it here" hints.
    """
    user = _user_path(rel)
    if os.path.isfile(user):
        return user
    bundled = _bundled_path(rel)
    if os.path.isfile(bundled):
        return bundled
    return user


class DonateDialog(QDialog):
    """Pop-up shown when the user clicks the donate button.

    Displays the bundled `app/donate.png` QR image.  No customisation
    UI — the image is baked in at build time.
    """

    DEFAULT_REL = "app/donate.png"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("支持作者")
        self.setMinimumSize(420, 560)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        self.title_label = QLabel("如果这个工具帮到了你，欢迎请作者喝杯咖啡 ☕")
        self.title_label.setStyleSheet("font-size: 13px; color: #333;")
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.title_label)

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumHeight(440)
        self.image_label.setStyleSheet(
            "border: 1px dashed rgb(180, 180, 180); background: white;"
        )
        outer.addWidget(self.image_label, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        outer.addLayout(row)

        self._load_image()

    def _load_image(self) -> None:
        path = _resource_path(self.DEFAULT_REL)
        if not os.path.isfile(path):
            self.image_label.setText("（未打包收款码图片）")
            self.image_label.setStyleSheet(
                "border: 1px dashed rgb(180, 180, 180); background: white;"
                " color: #999; font-size: 14px;"
            )
            return
        pix = QPixmap(path)
        if pix.isNull():
            self.image_label.setText("（图片无法解码）")
            return
        target = self.image_label.size()
        if target.width() <= 0:
            target = QSize(400, 540)
        scaled = pix.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)


def parse_page_ranges(s: str, max_pages: int) -> list[int]:
    """Parse '1-3,5,7-9' into 0-based indices. 'all' -> all pages."""
    s = (s or "").strip().lower()
    if not s or s == "all":
        return list(range(max_pages))
    result: list[int] = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            for i in range(start, end + 1):
                if 1 <= i <= max_pages:
                    result.append(i - 1)
        else:
            try:
                i = int(part)
                if 1 <= i <= max_pages:
                    result.append(i - 1)
            except ValueError:
                continue
    # dedupe preserving order
    seen = set()
    out = []
    for i in result:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
