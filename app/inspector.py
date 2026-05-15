"""Right-side panel that shows the currently selected element and lets
the user edit its content / style without leaving the page view."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .dialogs import color_picker_button
from .edit_mode import ImageElementItem, TextElementItem
from .font_registry import (
    FontDef, get_font, list_fonts,
    pick_default_for_span_aware as pick_default_for_span,
)
from .i18n import tr
from .text_edit import replace_span, sample_background_color


class ElementInspectorPanel(QWidget):
    """A side panel bound to a viewer's `EditController`."""

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.controller = viewer.edit_controller
        self._current: Optional[object] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)

        self.title = QLabel("元素")
        self.title.setStyleSheet(
            "font-weight: bold; font-size: 14px; color: rgb(0, 90, 180);"
        )
        outer.addWidget(self.title)

        self.subtitle = QLabel("在编辑模式下点击元素以查看属性。")
        self.subtitle.setWordWrap(True)
        self.subtitle.setStyleSheet("color: #666; font-size: 11px;")
        outer.addWidget(self.subtitle)

        self.stack = QStackedWidget()
        outer.addWidget(self.stack, 1)

        self._build_empty()
        self._build_text()
        self._build_image()
        self.stack.setCurrentWidget(self.empty_page)

        self.controller.element_selected.connect(self.show_element)
        self.controller.activeChanged.connect(self._on_active_changed)

    # ------------------------------------------------------------------
    # Page builders
    # ------------------------------------------------------------------
    def _build_empty(self) -> None:
        self.empty_page = QWidget()
        v = QVBoxLayout(self.empty_page)
        msg = QLabel(
            "内容编辑模式会把每段文字和每张图片显示为可编辑元素。\n\n"
            "• 单击元素选中\n"
            "• 已选中元素再次单击可就地编辑文字\n"
            "• 拖动元素移动；拖角点/边手柄缩放\n"
            "• Del 删除；双击也可进入就地编辑"
        )
        msg.setWordWrap(True)
        msg.setStyleSheet("color: #666;")
        v.addWidget(msg)
        v.addStretch(1)
        self.stack.addWidget(self.empty_page)

    def _build_text(self) -> None:
        self.text_page = QWidget()
        f = QFormLayout(self.text_page)
        self.txt_edit = QPlainTextEdit()
        self.txt_edit.setMaximumHeight(140)
        self.txt_edit.setPlaceholderText("修改文字内容")
        f.addRow("文字：", self.txt_edit)

        # Single dropdown listing every available font (base-14 plus
        # everything in app/fonts/).  Each item stores the FontDef key.
        self.txt_font = QComboBox()
        for fdef in list_fonts():
            self.txt_font.addItem(fdef.display, fdef.key)
        self.txt_font.setMaxVisibleItems(20)
        f.addRow("字体：", self.txt_font)

        self.txt_size = QDoubleSpinBox()
        self.txt_size.setRange(4, 400)
        self.txt_size.setSingleStep(0.5)
        f.addRow("字号：", self.txt_size)

        self.txt_color_btn, self.txt_color_state = color_picker_button(QColor(0, 0, 0))
        f.addRow("颜色：", self.txt_color_btn)

        self.txt_position = QLabel()
        self.txt_position.setStyleSheet("color: #666; font-family: monospace;")
        f.addRow("位置：", self.txt_position)

        self.txt_apply = QPushButton("应用")
        self.txt_apply.setStyleSheet(
            "QPushButton { background: rgb(0,120,215); color: white; "
            "padding: 6px; font-weight: bold; border-radius: 3px; }"
            "QPushButton:hover { background: rgb(30,140,225); }"
        )
        self.txt_apply.clicked.connect(self._apply_text)
        f.addRow(self.txt_apply)

        self.txt_delete = QPushButton("删除元素")
        self.txt_delete.setStyleSheet("color: #c33; padding: 4px;")
        self.txt_delete.clicked.connect(self._delete_current)
        f.addRow(self.txt_delete)

        self.stack.addWidget(self.text_page)

    def _build_image(self) -> None:
        self.image_page = QWidget()
        f = QFormLayout(self.image_page)
        self.img_xref = QLabel()
        f.addRow("Xref：", self.img_xref)
        self.img_position = QLabel()
        self.img_position.setStyleSheet("color: #666; font-family: monospace;")
        f.addRow("位置：", self.img_position)
        info = QLabel("拖动元素移动位置；用角点/边手柄缩放。")
        info.setWordWrap(True)
        info.setStyleSheet("color: #666;")
        f.addRow(info)
        self.img_delete = QPushButton("删除元素")
        self.img_delete.setStyleSheet("color: #c33; padding: 4px;")
        self.img_delete.clicked.connect(self._delete_current)
        f.addRow(self.img_delete)
        self.stack.addWidget(self.image_page)

    # ------------------------------------------------------------------
    # Public hooks
    # ------------------------------------------------------------------
    def _on_active_changed(self, active: bool) -> None:
        if active:
            self.subtitle.setText(tr("点击页面上的元素查看属性。"))
        else:
            self._current = None
            self.stack.setCurrentWidget(self.empty_page)
            self.subtitle.setText(tr("开启内容编辑模式后此面板可用。"))

    def show_element(self, element) -> None:
        self._current = element
        if isinstance(element, TextElementItem):
            self._show_text(element)
        elif isinstance(element, ImageElementItem):
            self._show_image(element)

    # ------------------------------------------------------------------
    # Text page
    # ------------------------------------------------------------------
    def _show_text(self, element: TextElementItem) -> None:
        span = element.span
        self.title.setText(tr("文字段"))
        self.subtitle.setText(tr(
            "在此修改文字与样式后点击「应用」；也可以再次点击元素就地编辑。"
        ))
        self.txt_edit.blockSignals(True)
        self.txt_edit.setPlainText(span.text)
        self.txt_edit.blockSignals(False)
        # Pick a sensible default in the dropdown based on the detected
        # span font.  The "_aware" variant ALSO considers the span's
        # text — Chinese content with an unknown PSName escalates to
        # a bundled CJK face instead of falling to Helvetica.
        default_key = pick_default_for_span(
            span.font, span.text,
            bold=span.is_bold, italic=span.is_italic,
        )
        idx = self.txt_font.findData(default_key)
        self.txt_font.setCurrentIndex(idx if idx >= 0 else 0)
        self.txt_size.setValue(float(span.size))
        r, g, b = span.color_rgb
        c = QColor(int(r * 255), int(g * 255), int(b * 255))
        self.txt_color_state[0] = c
        self.txt_color_btn.setStyleSheet(
            f"background-color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});"
            " min-width: 80px;"
        )
        self.txt_color_btn.setText(c.name())
        self.txt_position.setText(
            f"({span.rect.x0:.0f}, {span.rect.y0:.0f}) → "
            f"({span.rect.x1:.0f}, {span.rect.y1:.0f})"
        )
        self.stack.setCurrentWidget(self.text_page)

    def _resolved_font(self) -> FontDef:
        key = self.txt_font.currentData()
        f = get_font(key) if key else None
        return f or list_fonts()[0]

    def _apply_text(self) -> None:
        if not isinstance(self._current, TextElementItem):
            return
        element: TextElementItem = self._current
        new_text = self.txt_edit.toPlainText()
        fdef = self._resolved_font()
        alias = fdef.base14_alias or "helv"
        font_file = fdef.file
        size = self.txt_size.value()
        qc = self.txt_color_state[0]
        text_color = (qc.redF(), qc.greenF(), qc.blueF())
        doc = self.viewer.doc
        page = doc.page(element.span.page_index)
        bg = sample_background_color(page, element.span.rect)
        doc.push_undo()
        try:
            replace_span(
                page, element.span, new_text,
                font_alias=alias, font_file=font_file,
                font_size=size,
                text_color=text_color, background=bg,
            )
        except Exception as exc:
            self.subtitle.setText(tr("应用失败：") + str(exc))
            return
        doc.mark_dirty()
        doc.pageContentChanged.emit(element.span.page_index)
        self.controller.refresh_page(element.span.page_index)
        # The element we held a reference to is gone — clear inspector.
        self._current = None
        self.stack.setCurrentWidget(self.empty_page)
        self.subtitle.setText(tr("已应用。点击其他元素继续编辑。"))

    # ------------------------------------------------------------------
    # Image page
    # ------------------------------------------------------------------
    def _show_image(self, element: ImageElementItem) -> None:
        img = element.image
        self.title.setText(tr("图片"))
        self.subtitle.setText(tr("拖动元素移动；用角点/边手柄缩放。"))
        self.img_xref.setText(str(img.xref))
        self.img_position.setText(
            f"({img.rect.x0:.0f}, {img.rect.y0:.0f}) → "
            f"({img.rect.x1:.0f}, {img.rect.y1:.0f})"
        )
        self.stack.setCurrentWidget(self.image_page)

    # ------------------------------------------------------------------
    # Shared
    # ------------------------------------------------------------------
    def _delete_current(self) -> None:
        if self._current is None:
            return
        try:
            self._current.commit_delete()
        except Exception as exc:
            self.subtitle.setText(tr("删除失败：") + str(exc))
            return
        self._current = None
        self.stack.setCurrentWidget(self.empty_page)
        self.subtitle.setText(tr("已删除。点击其他元素。"))
