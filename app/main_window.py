"""Main application window that wires up the PDF editor."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

import fitz
from PyQt6.QtCore import QSettings, QStandardPaths, Qt
from PyQt6.QtGui import QAction, QActionGroup, QColor, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QWidget,
)

from .dialogs import (
    DonateDialog,
    EncryptDialog,
    FormFieldsDialog,
    HeaderFooterDialog,
    InsertPagesDialog,
    MetadataDialog,
    PageNumbersDialog,
    SignatureDialog,
    SplitDialog,
    WatermarkDialog,
    parse_page_ranges,
)
from .document import PdfDocument
from .i18n import apply_language, get_lang, set_lang, tr
from .inspector import ElementInspectorPanel
from .operations import (
    add_header_footer,
    add_image_watermark,
    add_page_numbers,
    add_text_watermark,
    apply_redactions,
    crop_page,
    delete_pages,
    duplicate_pages,
    export_html,
    export_page_images,
    export_text,
    extract_all_images,
    extract_pages_to,
    flatten_form,
    insert_blank_page,
    list_form_fields,
    merge_pdfs,
    reorder_pages,
    rotate_pages,
    save_decrypted,
    save_encrypted,
    save_optimized,
    search_document,
    split_pdf,
)
from .panels import OutlinePanel, SearchPanel, ThumbnailPanel
from .tools import Tool
from .viewer import PdfView


RECENT_LIMIT = 8
APP_NAME = "PDFEditor"
ORG_NAME = "LocalTools"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF 编辑器")
        self.resize(1280, 860)
        # Application icon (cat) — bundled via PyInstaller spec
        from .dialogs import _resource_path
        for rel in ("app/cat.ico", "app/cat.png"):
            p = _resource_path(rel)
            if os.path.isfile(p):
                self.setWindowIcon(QIcon(p))
                break

        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.doc = PdfDocument(self)
        self.viewer = PdfView(self.doc, self)
        self.setCentralWidget(self.viewer)

        # Panels
        self.thumbs = ThumbnailPanel(self.doc, self)
        self.outline = OutlinePanel(self.doc, self)
        self.search = SearchPanel(self)

        self._build_docks()
        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()

        # Signals
        self.doc.documentReplaced.connect(self._refresh_title)
        self.doc.dirtyChanged.connect(self._refresh_title)
        self.viewer.zoomChanged.connect(self._on_zoom_changed)
        self.viewer.statusMessage.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.viewer.pageHovered.connect(self._on_page_hovered)
        self.viewer.pageClicked.connect(self._on_page_clicked)
        self.viewer.annotationsModified.connect(self._on_annotations_modified)

        self.thumbs.pageSelected.connect(self.viewer.go_to_page)
        self.thumbs.pageDeleteRequested.connect(self._on_delete_pages)
        self.thumbs.pageRotateRequested.connect(self._on_rotate_pages)
        self.thumbs.pageDuplicateRequested.connect(self._on_duplicate_pages)
        self.thumbs.pageInsertBlankRequested.connect(self._on_insert_blank)
        self.thumbs.pageExtractRequested.connect(self._on_extract_pages)
        self.thumbs.pagesReordered.connect(self._on_pages_reordered)

        self.outline.locationSelected.connect(self.viewer.go_to_page)

        self.search.searchRequested.connect(self._on_search)
        self.search.clearRequested.connect(self.viewer.clear_search_overlay)
        self.search.resultActivated.connect(self._on_search_result)

        self._refresh_title()
        self._update_action_state()

        # Apply persisted language preference last so freshly-built menus
        # / toolbars / docks pick it up.
        apply_language(self)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_docks(self) -> None:
        self.thumb_dock = QDockWidget("页面缩略图", self)
        self.thumb_dock.setWidget(self.thumbs)
        self.thumb_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumb_dock)

        side = QTabWidget(self)
        side.addTab(self.outline, "大纲")
        side.addTab(self.search, "查找")
        self.side_dock = QDockWidget("导航", self)
        self.side_dock.setWidget(side)
        self.side_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.side_dock)

        # Inspector panel for content-edit mode (right side, hidden by default)
        self.inspector = ElementInspectorPanel(self.viewer)
        self.inspector_dock = QDockWidget("元素属性", self)
        self.inspector_dock.setWidget(self.inspector)
        self.inspector_dock.setAllowedAreas(
            Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.inspector_dock.setVisible(False)

    def _build_actions(self) -> None:
        def act(text, slot=None, *, shortcut=None, checkable=False, tip=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if tip:
                a.setStatusTip(tip)
            a.setCheckable(checkable)
            if slot:
                a.triggered.connect(slot)
            return a

        # File
        self.a_new = act("新建空白 PDF(&N)", self.new_document, shortcut="Ctrl+N")
        self.a_open = act("打开(&O)…", self.open_document, shortcut="Ctrl+O")
        self.a_save = act("保存(&S)", self.save_document, shortcut="Ctrl+S")
        self.a_save_as = act("另存为(&A)…", self.save_document_as, shortcut="Ctrl+Shift+S")
        self.a_close = act("关闭(&C)", self.close_document, shortcut="Ctrl+W")
        self.a_props = act("文档属性(&P)…", self.show_properties)
        self.a_exit = act("退出(&X)", self.close, shortcut="Ctrl+Q")

        # Edit
        self.a_undo = act("撤销(&U)", self.undo, shortcut="Ctrl+Z")
        self.a_redo = act("重做(&R)", self.redo, shortcut="Ctrl+Y")
        self.a_find = act("查找(&F)…", self.focus_search, shortcut="Ctrl+F")
        self.a_edit_mode = act("✎  内容编辑", self._toggle_edit_mode,
                                shortcut="Ctrl+E", checkable=True,
                                tip="将页面中每个文字段与图片显示为可编辑元素 (Ctrl+E)")

        # View
        self.a_zoom_in = act("放大(&I)", self.viewer.zoom_in, shortcut="Ctrl+=")
        self.a_zoom_out = act("缩小(&O)", self.viewer.zoom_out, shortcut="Ctrl+-")
        self.a_zoom_reset = act("实际大小(&S)", lambda: self.viewer.set_zoom(1.0), shortcut="Ctrl+0")
        self.a_fit_width = act("适合宽度(&W)", self.viewer.fit_width)
        self.a_fit_page = act("适合页面(&P)", self.viewer.fit_page)
        self.a_toggle_thumbs = act("显示缩略图", self.thumb_dock.setVisible, checkable=True)
        self.a_toggle_thumbs.setChecked(True)
        self.a_toggle_side = act("显示导航", self.side_dock.setVisible, checkable=True)
        self.a_toggle_side.setChecked(True)
        self.thumb_dock.visibilityChanged.connect(self.a_toggle_thumbs.setChecked)
        self.side_dock.visibilityChanged.connect(self.a_toggle_side.setChecked)
        self.a_fullscreen = act("全屏(&F)", self._toggle_fullscreen, shortcut="F11", checkable=True)

        # Navigation
        self.a_first = act("第一页", lambda: self.viewer.go_to_page(0), shortcut="Ctrl+Home")
        self.a_prev = act("上一页", lambda: self.viewer.go_to_page(self.viewer.current_page_index() - 1), shortcut="PgUp")
        self.a_next = act("下一页", lambda: self.viewer.go_to_page(self.viewer.current_page_index() + 1), shortcut="PgDown")
        self.a_last = act("最后一页", lambda: self.viewer.go_to_page(self.doc.page_count - 1), shortcut="Ctrl+End")
        self.a_goto = act("跳转到页(&G)…", self._goto_page, shortcut="Ctrl+G")

        # Page ops
        self.a_insert_blank = act("插入空白页(&B)…", lambda: self._on_insert_blank(self.viewer.current_page_index() + 1))
        self.a_insert_from = act("从 PDF 插入页…", self._insert_from_pdf)
        self.a_delete_pages = act("删除当前页", lambda: self._on_delete_pages([self.viewer.current_page_index()]), shortcut="Ctrl+Del")
        self.a_dup = act("复制当前页", lambda: self._on_duplicate_pages([self.viewer.current_page_index()]))
        self.a_rot_cw = act("顺时针旋转页面", lambda: self._on_rotate_pages([self.viewer.current_page_index()], 90))
        self.a_rot_ccw = act("逆时针旋转页面", lambda: self._on_rotate_pages([self.viewer.current_page_index()], -90))
        self.a_rot_180 = act("旋转 180°", lambda: self._on_rotate_pages([self.viewer.current_page_index()], 180))
        self.a_extract = act("提取页面…", self._extract_pages_dialog)
        self.a_crop = act("裁剪到选区…", self._crop_dialog)

        # Tools (mutually exclusive)
        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        self.tool_actions: dict[Tool, QAction] = {}

        def tool_action(text: str, tool: Tool, *, shortcut: Optional[str] = None):
            a = QAction(text, self)
            a.setCheckable(True)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.triggered.connect(lambda checked, t=tool: self._set_tool(t))
            self.tool_group.addAction(a)
            self.tool_actions[tool] = a
            return a

        self.t_select = tool_action("选择 / 平移", Tool.SELECT, shortcut="V")
        self.t_hand = tool_action("手型", Tool.HAND, shortcut="H")
        self.t_text = tool_action("添加文字", Tool.TEXT, shortcut="T")
        self.t_edit_text = tool_action("编辑已有文字", Tool.EDIT_TEXT, shortcut="Shift+E")
        self.t_highlight = tool_action("高亮", Tool.HIGHLIGHT, shortcut="Ctrl+H")
        self.t_underline = tool_action("下划线", Tool.UNDERLINE)
        self.t_strike = tool_action("删除线", Tool.STRIKEOUT)
        self.t_squiggly = tool_action("波浪线", Tool.SQUIGGLY)
        self.t_note = tool_action("便笺", Tool.NOTE, shortcut="N")
        self.t_freetext = tool_action("自由文字框", Tool.FREETEXT)
        self.t_rect = tool_action("矩形", Tool.RECT, shortcut="R")
        self.t_ellipse = tool_action("椭圆", Tool.ELLIPSE)
        self.t_line = tool_action("直线", Tool.LINE, shortcut="L")
        self.t_arrow = tool_action("箭头", Tool.ARROW)
        self.t_ink = tool_action("自由绘制", Tool.INK, shortcut="P")
        self.t_eraser = tool_action("橡皮擦（删除注解）", Tool.ERASER, shortcut="E")
        self.t_redact = tool_action("标记密涂", Tool.REDACT)
        self.t_image = tool_action("插入图片", Tool.IMAGE)
        self.t_link = tool_action("添加链接", Tool.LINK)
        self.t_signature = tool_action("放置签名（先用菜单加载签名）", Tool.SIGNATURE)
        self.t_select.setChecked(True)

        self.a_apply_redact = act("应用已标记密涂", self._apply_redactions)
        self.a_insert_signature = act("✍  插入签名…", self._insert_signature_dialog,
                                       shortcut="Ctrl+Shift+G",
                                       tip="手绘或从文件加载签名后单击放置到页面")

        # Document operations
        self.a_merge = act("合并 PDF(&M)…", self._merge_dialog)
        self.a_split = act("拆分 PDF(&S)…", self._split_dialog)
        self.a_watermark = act("添加水印(&W)…", self._watermark_dialog)
        self.a_page_nums = act("添加页码(&P)…", self._page_numbers_dialog)
        self.a_hdr_ftr = act("添加页眉/页脚(&H)…", self._header_footer_dialog)
        self.a_optimize = act("优化/压缩(&O)", self._optimize)
        self.a_encrypt = act("加密(&E)…", self._encrypt_dialog)
        self.a_decrypt = act("移除加密(&R)", self._decrypt)

        # Forms
        self.a_form_list = act("编辑表单字段…", self._form_dialog)
        self.a_form_flatten = act("扁平化表单", self._flatten_form)

        # Export
        self.a_export_text = act("导出文本(&T)…", self._export_text)
        self.a_export_html = act("导出 HTML(&H)…", self._export_html)
        self.a_export_images = act("导出页面图片(&I)…", self._export_images)
        self.a_extract_images = act("提取嵌入图片(&E)…", self._extract_images)

        # Help
        self.a_about = act("关于(&A)", self._about)
        self.a_show_font_log = act(
            "查看字体诊断日志(&D)…", self._show_font_log,
            tip="显示最近的拖拽/编辑操作分别选用了哪个字体（用于排查字体替换问题）",
        )

    def _build_menus(self) -> None:
        mb = self.menuBar()
        # Style the menubar so the prominent Edit Content action stands out.
        mb.setStyleSheet(
            "QMenuBar::item { padding: 4px 12px; }"
            "QMenuBar::item:checked {"
            "  background: rgb(0, 120, 215); color: white;"
            "  border-radius: 3px;"
            "}"
        )

        # Corner-widget: a row with [Switch to English] + [❤ Support author].
        corner = QWidget(self)
        crow = QHBoxLayout(corner)
        crow.setContentsMargins(0, 0, 4, 0)
        crow.setSpacing(4)

        self.lang_btn = QPushButton(
            "Switch to English" if get_lang() == "zh" else "切换为中文",
            self,
        )
        self.lang_btn.setFlat(True)
        self.lang_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lang_btn.setStyleSheet(
            "QPushButton {"
            "  color: rgb(0, 110, 200); padding: 4px 10px; border: none;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(0, 110, 200, 30);"
            "  border-radius: 4px;"
            "}"
        )
        self.lang_btn.clicked.connect(self._toggle_language)
        crow.addWidget(self.lang_btn)

        self.donate_btn = QPushButton("❤  支持作者", self)
        self.donate_btn.setFlat(True)
        self.donate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.donate_btn.setStyleSheet(
            "QPushButton {"
            "  color: rgb(220, 50, 70); font-weight: bold;"
            "  padding: 4px 12px; border: none;"
            "}"
            "QPushButton:hover {"
            "  background: rgba(220, 50, 70, 30);"
            "  border-radius: 4px;"
            "}"
        )
        self.donate_btn.clicked.connect(self._show_donate)
        crow.addWidget(self.donate_btn)

        mb.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        m_file = mb.addMenu("文件(&F)")
        m_file.addAction(self.a_new)
        m_file.addAction(self.a_open)
        self.menu_recent = m_file.addMenu("最近打开(&R)")
        self._refresh_recent_menu()
        m_file.addSeparator()
        m_file.addAction(self.a_save)
        m_file.addAction(self.a_save_as)
        m_file.addAction(self.a_close)
        m_file.addSeparator()
        m_file.addAction(self.a_props)
        m_file.addSeparator()
        m_file.addAction(self.a_exit)

        # Prominent top-level Edit Content action right after File.
        mb.addAction(self.a_edit_mode)

        m_edit = mb.addMenu("编辑(&E)")
        m_edit.addAction(self.a_undo)
        m_edit.addAction(self.a_redo)
        m_edit.addSeparator()
        m_edit.addAction(self.a_edit_mode)
        m_edit.addSeparator()
        m_edit.addAction(self.a_find)

        m_view = mb.addMenu("查看(&V)")
        m_view.addAction(self.a_zoom_in)
        m_view.addAction(self.a_zoom_out)
        m_view.addAction(self.a_zoom_reset)
        m_view.addSeparator()
        m_view.addAction(self.a_fit_width)
        m_view.addAction(self.a_fit_page)
        m_view.addSeparator()
        m_view.addAction(self.a_toggle_thumbs)
        m_view.addAction(self.a_toggle_side)
        m_view.addAction(self.a_fullscreen)

        m_nav = mb.addMenu("导航(&N)")
        m_nav.addAction(self.a_first)
        m_nav.addAction(self.a_prev)
        m_nav.addAction(self.a_next)
        m_nav.addAction(self.a_last)
        m_nav.addSeparator()
        m_nav.addAction(self.a_goto)

        m_page = mb.addMenu("页面(&P)")
        m_page.addAction(self.a_insert_blank)
        m_page.addAction(self.a_insert_from)
        m_page.addSeparator()
        m_page.addAction(self.a_dup)
        m_page.addAction(self.a_delete_pages)
        m_page.addSeparator()
        m_page.addAction(self.a_rot_cw)
        m_page.addAction(self.a_rot_ccw)
        m_page.addAction(self.a_rot_180)
        m_page.addSeparator()
        m_page.addAction(self.a_extract)
        m_page.addAction(self.a_crop)

        m_tools = mb.addMenu("工具(&T)")
        m_tools.addAction(self.t_select)
        m_tools.addAction(self.t_hand)
        m_tools.addSeparator()
        m_tools.addAction(self.t_text)
        m_tools.addAction(self.t_edit_text)
        m_tools.addAction(self.t_freetext)
        m_tools.addAction(self.t_note)
        m_tools.addAction(self.t_link)
        m_tools.addAction(self.t_image)
        m_tools.addAction(self.a_insert_signature)
        m_tools.addSeparator()
        m_tools.addAction(self.t_highlight)
        m_tools.addAction(self.t_underline)
        m_tools.addAction(self.t_strike)
        m_tools.addAction(self.t_squiggly)
        m_tools.addSeparator()
        m_tools.addAction(self.t_rect)
        m_tools.addAction(self.t_ellipse)
        m_tools.addAction(self.t_line)
        m_tools.addAction(self.t_arrow)
        m_tools.addAction(self.t_ink)
        m_tools.addSeparator()
        m_tools.addAction(self.t_eraser)
        m_tools.addAction(self.t_redact)
        m_tools.addAction(self.a_apply_redact)

        m_doc = mb.addMenu("文档(&D)")
        m_doc.addAction(self.a_merge)
        m_doc.addAction(self.a_split)
        m_doc.addSeparator()
        m_doc.addAction(self.a_watermark)
        m_doc.addAction(self.a_page_nums)
        m_doc.addAction(self.a_hdr_ftr)
        m_doc.addSeparator()
        m_doc.addAction(self.a_optimize)
        m_doc.addAction(self.a_encrypt)
        m_doc.addAction(self.a_decrypt)

        m_form = mb.addMenu("表单(&O)")
        m_form.addAction(self.a_form_list)
        m_form.addAction(self.a_form_flatten)

        m_export = mb.addMenu("导出(&X)")
        m_export.addAction(self.a_export_text)
        m_export.addAction(self.a_export_html)
        m_export.addAction(self.a_export_images)
        m_export.addAction(self.a_extract_images)

        m_help = mb.addMenu("帮助(&H)")
        m_help.addAction(self.a_show_font_log)
        m_help.addSeparator()
        m_help.addAction(self.a_about)

    def _build_toolbar(self) -> None:
        tb = QToolBar("主工具栏", self)
        tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)
        for a in [self.a_open, self.a_save, self.a_undo, self.a_redo]:
            tb.addAction(a)
        tb.addSeparator()
        tb.addAction(self.a_edit_mode)
        tb.addAction(self.a_insert_signature)
        tb.addSeparator()
        tb.addAction(self.a_zoom_out)
        self.zoom_combo = QComboBox(self)
        self.zoom_combo.setEditable(True)
        for z in ("50%", "75%", "100%", "125%", "150%", "200%", "300%", "适合宽度", "适合页面"):
            self.zoom_combo.addItem(z)
        self.zoom_combo.setCurrentText("100%")
        self.zoom_combo.activated.connect(self._on_zoom_combo)
        tb.addWidget(self.zoom_combo)
        tb.addAction(self.a_zoom_in)
        tb.addSeparator()
        tb.addAction(self.a_first)
        tb.addAction(self.a_prev)
        self.page_spin = QSpinBox(self)
        self.page_spin.setRange(1, 1)
        self.page_spin.editingFinished.connect(self._on_page_spin)
        tb.addWidget(self.page_spin)
        self.page_total = QLabel(" / 0", self)
        tb.addWidget(self.page_total)
        tb.addAction(self.a_next)
        tb.addAction(self.a_last)
        tb.addSeparator()

        tools_tb = QToolBar("工具", self)
        tools_tb.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tools_tb)
        for a in [self.t_select, self.t_hand, self.t_text, self.t_edit_text,
                   self.t_highlight, self.t_underline, self.t_strike,
                   self.t_note, self.t_freetext,
                   self.t_rect, self.t_ellipse, self.t_line, self.t_arrow,
                   self.t_ink, self.t_eraser, self.t_redact, self.t_image, self.t_link,
                   self.t_signature]:
            tools_tb.addAction(a)
        tools_tb.addSeparator()

        # Stroke colour
        self.stroke_btn = QLabel(" 描边 ")
        tools_tb.addWidget(self.stroke_btn)
        self.stroke_swatch = QLabel("        ")
        self.stroke_swatch.setStyleSheet(self._swatch_css(self.viewer.tool_settings.stroke_color))
        self.stroke_swatch.mousePressEvent = lambda _e: self._pick_color("stroke")
        tools_tb.addWidget(self.stroke_swatch)
        # Fill colour
        tools_tb.addWidget(QLabel(" 填充 "))
        self.fill_swatch = QLabel("        ")
        self.fill_swatch.setStyleSheet(self._swatch_css(self.viewer.tool_settings.fill_color))
        self.fill_swatch.mousePressEvent = lambda _e: self._pick_color("fill")
        tools_tb.addWidget(self.fill_swatch)
        # Highlight colour
        tools_tb.addWidget(QLabel(" 高亮 "))
        self.hi_swatch = QLabel("        ")
        self.hi_swatch.setStyleSheet(self._swatch_css(self.viewer.tool_settings.highlight_color))
        self.hi_swatch.mousePressEvent = lambda _e: self._pick_color("highlight")
        tools_tb.addWidget(self.hi_swatch)
        # Stroke width
        tools_tb.addWidget(QLabel(" 粗细 "))
        self.width_spin = QDoubleSpinBox(self)
        self.width_spin.setRange(0.25, 24.0)
        self.width_spin.setSingleStep(0.25)
        self.width_spin.setValue(self.viewer.tool_settings.stroke_width)
        self.width_spin.valueChanged.connect(lambda v: setattr(self.viewer.tool_settings, "stroke_width", float(v)))
        tools_tb.addWidget(self.width_spin)
        # Font size
        tools_tb.addWidget(QLabel(" 字号 "))
        self.font_spin = QDoubleSpinBox(self)
        self.font_spin.setRange(4.0, 144.0)
        self.font_spin.setSingleStep(1.0)
        self.font_spin.setValue(self.viewer.tool_settings.font_size)
        self.font_spin.valueChanged.connect(lambda v: setattr(self.viewer.tool_settings, "font_size", float(v)))
        tools_tb.addWidget(self.font_spin)

    def _swatch_css(self, c: QColor) -> str:
        return (f"background-color: rgba({c.red()},{c.green()},{c.blue()},{c.alpha()});"
                " border: 1px solid #444; min-width: 32px; min-height: 18px;")

    def _pick_color(self, which: str) -> None:
        settings = self.viewer.tool_settings
        current = {"stroke": settings.stroke_color, "fill": settings.fill_color,
                    "highlight": settings.highlight_color}[which]
        c = QColorDialog.getColor(current, self, "选择颜色",
                                   options=QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if not c.isValid():
            return
        if which == "stroke":
            settings.stroke_color = c
            self.stroke_swatch.setStyleSheet(self._swatch_css(c))
        elif which == "fill":
            settings.fill_color = c
            self.fill_swatch.setStyleSheet(self._swatch_css(c))
        elif which == "highlight":
            settings.highlight_color = c
            self.hi_swatch.setStyleSheet(self._swatch_css(c))

    def _build_statusbar(self) -> None:
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self.lbl_mouse = QLabel("")
        sb.addPermanentWidget(self.lbl_mouse)
        self.lbl_zoom = QLabel("100%")
        sb.addPermanentWidget(self.lbl_zoom)

    # ------------------------------------------------------------------
    # Title / state
    # ------------------------------------------------------------------
    def _refresh_title(self) -> None:
        if self.doc.path:
            name = os.path.basename(self.doc.path)
        else:
            name = tr("未命名")
        dirty = "*" if self.doc.dirty else ""
        opened = " — " + name if self.doc.is_open() else ""
        self.setWindowTitle(f"{tr('PDF 编辑器')}{opened}{dirty}")
        self._update_action_state()

    def _update_action_state(self) -> None:
        opened = self.doc.is_open()
        for a in [self.a_save, self.a_save_as, self.a_close, self.a_props,
                   self.a_undo, self.a_redo, self.a_find, self.a_edit_mode,
                   self.a_zoom_in, self.a_zoom_out, self.a_zoom_reset,
                   self.a_fit_width, self.a_fit_page, self.a_first, self.a_prev,
                   self.a_next, self.a_last, self.a_goto,
                   self.a_insert_blank, self.a_insert_from, self.a_delete_pages,
                   self.a_dup, self.a_rot_cw, self.a_rot_ccw, self.a_rot_180,
                   self.a_extract, self.a_crop, self.a_apply_redact,
                   self.a_insert_signature,
                   self.a_split, self.a_watermark, self.a_page_nums, self.a_hdr_ftr,
                   self.a_optimize, self.a_encrypt, self.a_decrypt,
                   self.a_form_list, self.a_form_flatten,
                   self.a_export_text, self.a_export_html, self.a_export_images,
                   self.a_extract_images]:
            a.setEnabled(opened)
        # Tools
        for a in self.tool_actions.values():
            a.setEnabled(opened)
        # Update spinbox range
        if opened:
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, max(1, self.doc.page_count))
            self.page_spin.blockSignals(False)
            self.page_total.setText(f" / {self.doc.page_count}")
        else:
            self.page_spin.setRange(1, 1)
            self.page_total.setText(" / 0")

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------
    def new_document(self) -> None:
        if not self._prompt_save():
            return
        self.doc.new_blank()
        self._auto_enable_edit_mode()

    def _auto_enable_edit_mode(self) -> None:
        """Default the freshly-opened document into Edit Content mode.

        Acts only when the user is NOT already in edit mode — clicking
        the toggle off then opening another doc still leaves it off
        within the same launch, but a fresh launch starts in edit mode.
        """
        if self.viewer.edit_controller.is_active():
            return
        # `setChecked` already emits `triggered`/`toggled`; calling the
        # slot ourselves on top would activate twice.  Just check it.
        self.a_edit_mode.blockSignals(True)
        self.a_edit_mode.setChecked(True)
        self.a_edit_mode.blockSignals(False)
        self._toggle_edit_mode(True)

    def open_document(self, path: Optional[str] = None) -> None:
        if not self._prompt_save():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, tr("打开 PDF"), "", "PDF (*.pdf)")
        if not path:
            return
        password = None
        if self.doc.needs_password(path):
            label = (f"Password for {os.path.basename(path)}:"
                     if get_lang() == "en"
                     else f"请输入 {os.path.basename(path)} 的密码：")
            password, ok = QInputDialog.getText(
                self, tr("密码"), label,
                QLineEdit.EchoMode.Password,
            )
            if not ok:
                return
        try:
            ok = self.doc.open(path, password=password)
        except Exception as exc:
            QMessageBox.critical(self, tr("打开失败"), str(exc))
            return
        if not ok:
            QMessageBox.warning(self, tr("打开失败"), tr("密码不正确。"))
            return
        self._add_recent(path)
        self._auto_enable_edit_mode()

    def save_document(self) -> None:
        if not self.doc.is_open():
            return
        if not self.doc.path:
            self.save_document_as()
            return
        try:
            self.doc.save()
            self.statusBar().showMessage(tr("已保存。"), 3000)
        except Exception as exc:
            QMessageBox.critical(self, tr("保存失败"), str(exc))

    def save_document_as(self) -> None:
        if not self.doc.is_open():
            return
        suggest = self.doc.path or "document.pdf"
        path, _ = QFileDialog.getSaveFileName(self, tr("另存为"), suggest, "PDF (*.pdf)")
        if not path:
            return
        try:
            self.doc.save(path)
            msg = f"Saved to {path}" if get_lang() == "en" else f"已保存到 {path}"
            self.statusBar().showMessage(msg, 3000)
            self._add_recent(path)
        except Exception as exc:
            QMessageBox.critical(self, tr("保存失败"), str(exc))

    def close_document(self) -> None:
        if not self._prompt_save():
            return
        if self.viewer.edit_controller.is_active():
            self.viewer.edit_controller.set_active(False)
            self.a_edit_mode.setChecked(False)
        self.doc.close()

    def show_properties(self) -> None:
        if not self.doc.is_open():
            return
        md = self.doc.metadata()
        dlg = MetadataDialog(md, self)
        if dlg.exec():
            self.doc.set_metadata({**md, **dlg.values()})

    def _prompt_save(self) -> bool:
        if not self.doc.dirty:
            return True
        choice = QMessageBox.question(
            self, tr("未保存的更改"),
            tr("文档有未保存的更改，是否在继续前保存？"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            self.save_document()
            if self.doc.dirty:  # save failed/cancelled
                return False
        return True

    # ------------------------------------------------------------------
    # Recent files
    # ------------------------------------------------------------------
    def _recent_files(self) -> list[str]:
        raw = self.settings.value("recent", []) or []
        if isinstance(raw, str):
            raw = [raw]
        return list(raw)

    def _add_recent(self, path: str) -> None:
        files = [p for p in self._recent_files() if p != path]
        files.insert(0, path)
        files = files[:RECENT_LIMIT]
        self.settings.setValue("recent", files)
        self._refresh_recent_menu()

    def _refresh_recent_menu(self) -> None:
        self.menu_recent.clear()
        files = self._recent_files()
        if not files:
            a = self.menu_recent.addAction(tr("（无最近打开）"))
            a.setEnabled(False)
            return
        for p in files:
            a = self.menu_recent.addAction(p)
            a.triggered.connect(lambda _checked=False, path=p: self.open_document(path))
        self.menu_recent.addSeparator()
        clr = self.menu_recent.addAction(tr("清空最近列表"))
        clr.triggered.connect(lambda: (self.settings.setValue("recent", []), self._refresh_recent_menu()))

    # ------------------------------------------------------------------
    # Undo / redo
    # ------------------------------------------------------------------
    def undo(self) -> None:
        if self.doc.can_undo():
            self.doc.undo()

    def redo(self) -> None:
        if self.doc.can_redo():
            self.doc.redo()

    # ------------------------------------------------------------------
    # View hooks
    # ------------------------------------------------------------------
    def _on_zoom_changed(self, zoom: float) -> None:
        pct = f"{int(round(zoom * 100))}%"
        self.lbl_zoom.setText(pct)
        self.zoom_combo.blockSignals(True)
        self.zoom_combo.setCurrentText(pct)
        self.zoom_combo.blockSignals(False)

    def _on_zoom_combo(self, _idx: int) -> None:
        text = self.zoom_combo.currentText().strip().lower()
        if text in ("fit width", "适合宽度"):
            self.viewer.fit_width()
        elif text in ("fit page", "适合页面"):
            self.viewer.fit_page()
        else:
            m = re.match(r"(\d+(?:\.\d+)?)\s*%?", text)
            if m:
                try:
                    self.viewer.set_zoom(float(m.group(1)) / 100.0)
                except ValueError:
                    pass

    def _on_page_hovered(self, idx: int) -> None:
        label = (f"page {idx + 1}" if get_lang() == "en"
                  else f"第 {idx + 1} 页")
        self.lbl_mouse.setText(label)

    def _on_page_clicked(self, idx: int) -> None:
        self.thumbs.select_page(idx)
        self.page_spin.blockSignals(True)
        self.page_spin.setValue(idx + 1)
        self.page_spin.blockSignals(False)

    def _on_page_spin(self) -> None:
        target = self.page_spin.value() - 1
        self.viewer.go_to_page(target)

    def _goto_page(self) -> None:
        if not self.doc.is_open():
            return
        n, ok = QInputDialog.getInt(self, tr("跳转到页"), tr("页码："), 1, 1, self.doc.page_count)
        if ok:
            self.viewer.go_to_page(n - 1)

    def _toggle_fullscreen(self, checked: bool) -> None:
        if checked:
            self.showFullScreen()
        else:
            self.showNormal()

    def _toggle_edit_mode(self, checked: bool) -> None:
        self.viewer.edit_controller.set_active(checked)
        self.inspector_dock.setVisible(checked)
        if checked:
            self.viewer.set_tool(Tool.SELECT)
            self.t_select.setChecked(True)
            self.a_edit_mode.setText(tr("◉  内容编辑（已开启）"))
            self.statusBar().showMessage(
                tr("内容编辑已开启：单击选中 · 再次单击就地编辑文字 · "
                    "拖动移动 · 角点缩放 · Del 删除"),
                10000,
            )
        else:
            self.a_edit_mode.setText(tr("✎  内容编辑"))
            self.statusBar().showMessage(tr("已关闭内容编辑"), 3000)

    def focus_search(self) -> None:
        self.side_dock.setVisible(True)
        self.search.edit.setFocus()
        self.search.edit.selectAll()

    # ------------------------------------------------------------------
    # Tool setting
    # ------------------------------------------------------------------
    def _set_tool(self, tool: Tool) -> None:
        self.viewer.set_tool(tool)
        if tool in self.tool_actions:
            self.tool_actions[tool].setChecked(True)

    # ------------------------------------------------------------------
    # Page operations
    # ------------------------------------------------------------------
    def _insert_signature_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = SignatureDialog(self)
        if not dlg.exec():
            return
        data = dlg.image_bytes()
        if not data:
            return
        self.viewer._pending_signature = data
        self._set_tool(Tool.SIGNATURE)
        self.statusBar().showMessage(
            tr("签名已就绪——在页面上单击放置（按 Esc 或切换其他工具取消）。"),
            8000,
        )

    def _on_insert_blank(self, at: int) -> None:
        if not self.doc.is_open():
            return
        w, ok = QInputDialog.getDouble(self, tr("插入空白页"), tr("宽度（pt）："), 595.0, 10.0, 5000.0, 1)
        if not ok:
            return
        h, ok = QInputDialog.getDouble(self, tr("插入空白页"), tr("高度（pt）："), 842.0, 10.0, 5000.0, 1)
        if not ok:
            return
        self.doc.push_undo()
        insert_blank_page(self.doc.doc, at, w, h)
        self.doc.mark_dirty()
        self.doc.pagesChanged.emit()
        self.viewer.go_to_page(at)

    def _on_delete_pages(self, indices: list[int]) -> None:
        if not self.doc.is_open() or not indices:
            return
        if self.doc.page_count - len(indices) < 1:
            QMessageBox.warning(self, tr("删除"), tr("无法删除全部页面。"))
            return
        confirm = (f"Delete {len(indices)} page(s)?" if get_lang() == "en"
                    else f"确定要删除 {len(indices)} 个页面吗？")
        if QMessageBox.question(self, tr("删除页面"), confirm) != QMessageBox.StandardButton.Yes:
            return
        self.doc.push_undo()
        delete_pages(self.doc.doc, indices)
        self.doc.mark_dirty()
        self.doc.pagesChanged.emit()

    def _on_duplicate_pages(self, indices: list[int]) -> None:
        if not self.doc.is_open() or not indices:
            return
        self.doc.push_undo()
        duplicate_pages(self.doc.doc, indices)
        self.doc.mark_dirty()
        self.doc.pagesChanged.emit()

    def _on_rotate_pages(self, indices: list[int], delta: int) -> None:
        if not self.doc.is_open() or not indices:
            return
        self.doc.push_undo()
        rotate_pages(self.doc.doc, indices, delta)
        self.doc.mark_dirty()
        self.doc.pagesChanged.emit()

    def _on_pages_reordered(self, new_order: list[int]) -> None:
        if not self.doc.is_open() or len(new_order) != self.doc.page_count:
            return
        # Avoid acting on identity orders
        if new_order == list(range(self.doc.page_count)):
            return
        try:
            self.doc.push_undo()
            new_doc = reorder_pages(self.doc.doc, new_order)
            self.doc.doc.close()
            self.doc.doc = new_doc
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "重排失败", str(exc))

    def _on_extract_pages(self, indices: list[int]) -> None:
        if not self.doc.is_open() or not indices:
            return
        path, _ = QFileDialog.getSaveFileName(self, "提取页面到", "extract.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            extract_pages_to(self.doc.doc, indices, path)
            self.statusBar().showMessage(f"已提取 {len(indices)} 页到 {path}", 5000)
        except Exception as exc:
            QMessageBox.critical(self, "提取失败", str(exc))

    def _extract_pages_dialog(self) -> None:
        if not self.doc.is_open():
            return
        text, ok = QInputDialog.getText(self, "提取页面", "页码范围（例如 1-3,5）：",
                                         text=f"1-{self.doc.page_count}")
        if not ok or not text:
            return
        indices = parse_page_ranges(text, self.doc.page_count)
        self._on_extract_pages(indices)

    def _crop_dialog(self) -> None:
        if not self.doc.is_open():
            return
        idx = self.viewer.current_page_index()
        page = self.doc.page(idx)
        r = page.rect
        text, ok = QInputDialog.getText(
            self, "裁剪", "新的裁剪框 'x0,y0,x1,y1'（PDF 点）：",
            text=f"{r.x0:.1f},{r.y0:.1f},{r.x1:.1f},{r.y1:.1f}",
        )
        if not ok or not text:
            return
        try:
            parts = [float(s.strip()) for s in text.split(",")]
            assert len(parts) == 4
            rect = fitz.Rect(*parts)
        except Exception:
            QMessageBox.warning(self, "裁剪", "无法解析裁剪矩形。")
            return
        self.doc.push_undo()
        crop_page(self.doc.doc, idx, rect)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(idx)

    def _insert_from_pdf(self) -> None:
        if not self.doc.is_open():
            return
        dlg = InsertPagesDialog(self.doc.page_count, self)
        if not dlg.exec():
            return
        src = dlg.path.text().strip()
        if not src or not os.path.isfile(src):
            QMessageBox.warning(self, "插入", "请选择有效的 PDF 文件。")
            return
        try:
            other = fitz.open(src)
        except Exception as exc:
            QMessageBox.critical(self, "插入", str(exc))
            return
        try:
            indices = parse_page_ranges(dlg.ranges.text(), other.page_count)
            if not indices:
                indices = list(range(other.page_count))
            self.doc.push_undo()
            at = dlg.at.value()
            # Insert in order so they end up contiguous
            for offset, src_idx in enumerate(indices):
                self.doc.doc.insert_pdf(
                    other,
                    from_page=src_idx,
                    to_page=src_idx,
                    start_at=at + offset,
                )
        finally:
            other.close()
        self.doc.mark_dirty()
        self.doc.pagesChanged.emit()

    # ------------------------------------------------------------------
    # Annotation hooks
    # ------------------------------------------------------------------
    def _on_annotations_modified(self, page_index: int) -> None:
        # Refresh thumb for that page
        self.thumbs.refresh_one(page_index)

    def _apply_redactions(self) -> None:
        if not self.doc.is_open():
            return
        if QMessageBox.question(self, "应用密涂",
                                "这将永久删除所有已标记密涂区域下的内容，是否继续？") != QMessageBox.StandardButton.Yes:
            return
        self.doc.push_undo()
        try:
            apply_redactions(self.doc.doc)
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "密涂失败", str(exc))

    # ------------------------------------------------------------------
    # Document operations
    # ------------------------------------------------------------------
    def _merge_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择要合并的 PDF",
                                                 "", "PDF (*.pdf)")
        if not files:
            return
        if self.doc.is_open() and self.doc.path and self.doc.path not in files:
            choice = QMessageBox.question(
                self, "合并", "是否将当前打开的文档放在最前？",
            )
            if choice == QMessageBox.StandardButton.Yes:
                files = [self.doc.path] + files
        out, _ = QFileDialog.getSaveFileName(self, "保存合并后的 PDF", "merged.pdf", "PDF (*.pdf)")
        if not out:
            return
        try:
            count = merge_pdfs(files, out)
            QMessageBox.information(self, "合并", f"已写入 {count} 页到 {out}。")
        except Exception as exc:
            QMessageBox.critical(self, "合并失败", str(exc))

    def _split_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = SplitDialog(self.doc.page_count, self)
        if not dlg.exec():
            return
        out_dir = QFileDialog.getExistingDirectory(self, "输出目录")
        if not out_dir:
            return
        basename = Path(self.doc.path or "document").stem
        if dlg.mode.currentText().startswith("每"):
            n = dlg.n.value()
            ranges = []
            for start in range(0, self.doc.page_count, n):
                ranges.append((start, min(start + n - 1, self.doc.page_count - 1)))
        else:
            ranges = []
            for chunk in dlg.ranges.text().split(","):
                chunk = chunk.strip()
                if not chunk:
                    continue
                if "-" in chunk:
                    a, b = chunk.split("-", 1)
                    ranges.append((max(0, int(a) - 1), min(self.doc.page_count - 1, int(b) - 1)))
                else:
                    p = int(chunk) - 1
                    ranges.append((p, p))
        try:
            written = split_pdf(self.doc.doc, out_dir, basename, ranges)
            QMessageBox.information(self, "拆分", f"已写入 {len(written)} 个文件。")
        except Exception as exc:
            QMessageBox.critical(self, "拆分失败", str(exc))

    def _watermark_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = WatermarkDialog(self)
        if not dlg.exec():
            return
        v = dlg.values()
        pages = parse_page_ranges(v["scope"], self.doc.page_count) if v["scope"] else None
        self.doc.push_undo()
        try:
            if v["mode"] in ("Text", "文字"):
                add_text_watermark(self.doc.doc, v["text"], opacity=v["opacity"],
                                    font_size=v["size"], rotate=v["rotation"],
                                    only_pages=pages)
            else:
                if not v["image_path"] or not os.path.isfile(v["image_path"]):
                    QMessageBox.warning(self, "水印", "请选择图片文件。")
                    return
                add_image_watermark(self.doc.doc, v["image_path"], opacity=v["opacity"],
                                     only_pages=pages)
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "水印失败", str(exc))

    def _page_numbers_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = PageNumbersDialog(self)
        if not dlg.exec():
            return
        self.doc.push_undo()
        try:
            add_page_numbers(
                self.doc.doc,
                position=dlg.position.currentText(),
                fmt=dlg.fmt.text() or "{page} / {total}",
                font_size=dlg.size.value(),
                start_at=dlg.start_at.value(),
            )
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "添加页码失败", str(exc))

    def _header_footer_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = HeaderFooterDialog(self)
        if not dlg.exec():
            return
        self.doc.push_undo()
        try:
            add_header_footer(
                self.doc.doc,
                header=dlg.header.text() or None,
                footer=dlg.footer.text() or None,
                font_size=dlg.size.value(),
            )
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "页眉页脚失败", str(exc))

    def _optimize(self) -> None:
        if not self.doc.is_open():
            return
        out, _ = QFileDialog.getSaveFileName(self, "另存优化文件", "optimized.pdf",
                                              "PDF (*.pdf)")
        if not out:
            return
        try:
            save_optimized(self.doc.doc, out)
            QMessageBox.information(self, "优化", f"已写入 {out}。")
        except Exception as exc:
            QMessageBox.critical(self, "优化失败", str(exc))

    def _encrypt_dialog(self) -> None:
        if not self.doc.is_open():
            return
        dlg = EncryptDialog(self)
        if not dlg.exec():
            return
        out, _ = QFileDialog.getSaveFileName(self, "另存加密文件", "encrypted.pdf", "PDF (*.pdf)")
        if not out:
            return
        try:
            save_encrypted(
                self.doc.doc, out,
                user_pw=dlg.user_pw.text(),
                owner_pw=dlg.owner_pw.text(),
                allow_print=dlg.allow_print.isChecked(),
                allow_copy=dlg.allow_copy.isChecked(),
                allow_modify=dlg.allow_modify.isChecked(),
                allow_annotate=dlg.allow_annot.isChecked(),
            )
            QMessageBox.information(self, "加密", f"已写入 {out}。")
        except Exception as exc:
            QMessageBox.critical(self, "加密失败", str(exc))

    def _decrypt(self) -> None:
        if not self.doc.is_open():
            return
        out, _ = QFileDialog.getSaveFileName(self, "另存解密文件", "decrypted.pdf", "PDF (*.pdf)")
        if not out:
            return
        try:
            save_decrypted(self.doc.doc, out)
            QMessageBox.information(self, "解密", f"已写入 {out}。")
        except Exception as exc:
            QMessageBox.critical(self, "解密失败", str(exc))

    # ------------------------------------------------------------------
    # Forms
    # ------------------------------------------------------------------
    def _form_dialog(self) -> None:
        if not self.doc.is_open():
            return
        fields = list_form_fields(self.doc.doc)
        if not fields:
            QMessageBox.information(self, "表单", "未检测到表单字段。")
            return
        dlg = FormFieldsDialog(fields, self)
        if not dlg.exec():
            return
        values = dlg.values()
        self.doc.push_undo()
        try:
            for idx, val in values.items():
                f = fields[idx]
                widgets = self.doc.page(f["page"]).widgets() or []
                # Find matching widget
                for w in widgets:
                    if w.field_name == f["name"] and w.rect == f["rect"]:
                        try:
                            w.field_value = val
                            w.update()
                        except Exception:
                            pass
                        break
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "表单", str(exc))

    def _flatten_form(self) -> None:
        if not self.doc.is_open():
            return
        if QMessageBox.question(
            self, "扁平化表单",
            "扁平化所有表单字段（之后将不能再编辑），是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        self.doc.push_undo()
        try:
            flatten_form(self.doc.doc)
            self.doc.mark_dirty()
            self.doc.documentReplaced.emit()
        except Exception as exc:
            QMessageBox.critical(self, "扁平化", str(exc))

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def _export_text(self) -> None:
        if not self.doc.is_open():
            return
        out, _ = QFileDialog.getSaveFileName(self, "导出文本", "document.txt",
                                              "文本 (*.txt)")
        if out:
            try:
                export_text(self.doc.doc, out)
                self.statusBar().showMessage(f"已写入 {out}", 5000)
            except Exception as exc:
                QMessageBox.critical(self, "导出失败", str(exc))

    def _export_html(self) -> None:
        if not self.doc.is_open():
            return
        out, _ = QFileDialog.getSaveFileName(self, "导出 HTML", "document.html",
                                              "HTML (*.html *.htm)")
        if out:
            try:
                export_html(self.doc.doc, out)
                self.statusBar().showMessage(f"已写入 {out}", 5000)
            except Exception as exc:
                QMessageBox.critical(self, "导出失败", str(exc))

    def _export_images(self) -> None:
        if not self.doc.is_open():
            return
        out = QFileDialog.getExistingDirectory(self, "输出目录")
        if not out:
            return
        fmt, ok = QInputDialog.getItem(self, "格式", "图片格式：",
                                        ["png", "jpg"], 0, False)
        if not ok:
            return
        dpi, ok = QInputDialog.getInt(self, "DPI", "分辨率（DPI）：", 150, 36, 600)
        if not ok:
            return
        try:
            written = export_page_images(self.doc.doc, out, fmt=fmt, dpi=dpi)
            QMessageBox.information(self, "导出图片", f"已写入 {len(written)} 个文件。")
        except Exception as exc:
            QMessageBox.critical(self, "导出失败", str(exc))

    def _extract_images(self) -> None:
        if not self.doc.is_open():
            return
        out = QFileDialog.getExistingDirectory(self, "输出目录")
        if not out:
            return
        try:
            written = extract_all_images(self.doc.doc, out)
            QMessageBox.information(self, "提取图片", f"已写入 {len(written)} 个文件。")
        except Exception as exc:
            QMessageBox.critical(self, "提取失败", str(exc))

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def _on_search(self, query: str) -> None:
        if not self.doc.is_open() or not query:
            return
        hits = search_document(self.doc.doc, query)
        self.search.set_results(hits)
        rects = [(p, r) for p, r, _ in hits]
        self.viewer.highlight_search(rects)
        if hits:
            page_index, rect, _ = hits[0]
            self.viewer.go_to_page(page_index)

    def _on_search_result(self, page_index: int, rect: fitz.Rect) -> None:
        self.viewer.go_to_page(page_index)

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------
    def _show_donate(self) -> None:
        dlg = DonateDialog(self)
        dlg.exec()

    def _toggle_language(self) -> None:
        new = "en" if get_lang() == "zh" else "zh"
        set_lang(new)
        # Refresh the language button caption itself (it's outside the
        # i18n dict because it always shows the OTHER language).
        self.lang_btn.setText("Switch to English" if new == "zh" else "切换为中文")
        apply_language(self)
        self._refresh_title()
        msg = "Language switched." if new == "en" else "语言已切换。"
        self.statusBar().showMessage(msg, 3000)

    def _show_font_log(self) -> None:
        """Open the per-session font-decision log in a viewable dialog
        so the user can copy-paste a transcript when reporting a
        font-drift bug.
        """
        log_dir = os.path.expanduser("~/Desktop")
        if not os.path.isdir(log_dir):
            log_dir = os.path.expanduser("~")
        log_path = os.path.join(log_dir, "kitty_pdf_font_log.txt")
        content = ""
        if os.path.isfile(log_path):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as exc:
                content = f"(读取日志失败: {exc})"
        else:
            content = (
                f"日志文件尚未创建。\n\n"
                f"请先打开一个 PDF，开启内容编辑模式，拖动或编辑一段文字，"
                f"然后再次打开本对话框。\n\n"
                f"日志位置: {log_path}"
            )
        from PyQt6.QtWidgets import (
            QApplication as _QApp, QDialog, QDialogButtonBox,
            QPlainTextEdit, QVBoxLayout, QPushButton, QHBoxLayout,
        )
        dlg = QDialog(self)
        dlg.setWindowTitle("字体诊断日志")
        dlg.resize(900, 600)
        lay = QVBoxLayout(dlg)
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(content)
        edit.setStyleSheet("font-family: Consolas, monospace; font-size: 11px;")
        lay.addWidget(edit, 1)
        row = QHBoxLayout()
        copy_btn = QPushButton("全部复制到剪贴板")
        copy_btn.clicked.connect(
            lambda: _QApp.clipboard().setText(content)
        )
        row.addWidget(copy_btn)
        clear_btn = QPushButton("清空日志")
        def _clear():
            try:
                if os.path.isfile(log_path):
                    os.remove(log_path)
                edit.setPlainText("(已清空)")
            except Exception as exc:
                edit.setPlainText(f"(清空失败: {exc})")
        clear_btn.clicked.connect(_clear)
        row.addWidget(clear_btn)
        row.addStretch(1)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)
        dlg.exec()

    def _about(self) -> None:
        if get_lang() == "en":
            QMessageBox.about(
                self, "About PDF Editor",
                "<h3>PDF Editor</h3>"
                "<p>A PDF viewer / editor built on PyQt6 + PyMuPDF.</p>"
                "<p>Features: page operations, annotations, text + image "
                "editing, content-edit mode, signatures, watermarks, "
                "page numbers, encryption, forms, redactions, text / "
                "HTML / image export, and more.</p>",
            )
        else:
            QMessageBox.about(
                self, "关于 PDF 编辑器",
                "<h3>PDF 编辑器</h3>"
                "<p>基于 PyQt6 + PyMuPDF 的 PDF 查看 / 编辑工具。</p>"
                "<p>功能：页面操作、注解、文字与图片编辑、内容编辑模式、"
                "签名、水印、页码、加密、表单、密涂、文本/HTML/图片导出等。</p>",
            )

    def closeEvent(self, event):
        if self._prompt_save():
            event.accept()
        else:
            event.ignore()
