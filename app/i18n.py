"""Lightweight i18n.

Two strategies:
  1. `tr(s)` — call-site translation for dynamic strings (status bar,
     dialog titles created at runtime).
  2. `apply_language(widget)` — walk a widget tree and translate text
     properties of every QAction / QMenu / QLabel / QPushButton /
     QCheckBox / QLineEdit / QComboBox / QDockWidget / QTabWidget /
     QGroupBox we encounter.

The dictionary is keyed by the original Chinese strings, so call sites
can stay terse: they keep their Chinese literals and the walker maps
them to English when language == "en".  Strings not in the map fall
through to their original form.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QSettings
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDockWidget,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QMenuBar,
    QTabWidget,
    QWidget,
)


_LANG = "zh"
_SETTINGS_KEY = "lang"


# ----------------------------------------------------------------------
# Mappings (Chinese source → English).
# Keep keys EXACTLY as they appear in source code.
# ----------------------------------------------------------------------
EN: dict[str, str] = {
    # ---- App title / window ----
    "PDF 编辑器": "PDF Editor",
    "未命名": "Untitled",

    # ---- Menu titles ----
    "文件(&F)": "&File",
    "编辑(&E)": "&Edit",
    "查看(&V)": "&View",
    "导航(&N)": "&Navigate",
    "页面(&P)": "&Page",
    "工具(&T)": "&Tools",
    "文档(&D)": "&Document",
    "表单(&O)": "F&orms",
    "导出(&X)": "E&xport",
    "帮助(&H)": "&Help",
    "最近打开(&R)": "Open &Recent",
    "（无最近打开）": "(no recent files)",
    "清空最近列表": "Clear recent files",

    # ---- File ----
    "新建空白 PDF(&N)": "&New blank PDF",
    "打开(&O)…": "&Open…",
    "保存(&S)": "&Save",
    "另存为(&A)…": "Save &As…",
    "关闭(&C)": "&Close",
    "文档属性(&P)…": "Document &Properties…",
    "退出(&X)": "E&xit",
    "打开 PDF": "Open PDF",
    "已保存。": "Saved.",
    "另存为": "Save As",
    "未保存的更改": "Unsaved changes",
    "文档有未保存的更改，是否在继续前保存？":
        "The document has unsaved changes. Save before continuing?",
    "保存失败": "Save failed",
    "打开失败": "Open failed",
    "密码": "Password",
    "密码不正确。": "Incorrect password.",

    # ---- Edit ----
    "撤销(&U)": "&Undo",
    "重做(&R)": "&Redo",
    "查找(&F)…": "&Find…",
    "✎  内容编辑": "✎  Edit Content",
    "◉  内容编辑（已开启）": "◉  Edit Content (ON)",
    "将页面中每个文字段与图片显示为可编辑元素 (Ctrl+E)":
        "Show every text span and image as an editable element (Ctrl+E)",
    "内容编辑已开启：单击选中 · 再次单击就地编辑文字 · 拖动移动 · 角点缩放 · Del 删除":
        "Edit Content ON · click selects · click again to edit text in place · "
        "drag to move · handles to resize · Del to remove",
    "已关闭内容编辑": "Edit Content OFF",

    # ---- View ----
    "放大(&I)": "Zoom &In",
    "缩小(&O)": "Zoom &Out",
    "实际大小(&S)": "Actual &Size",
    "适合宽度(&W)": "Fit &Width",
    "适合页面(&P)": "Fit &Page",
    "显示缩略图": "Show Thumbnails",
    "显示导航": "Show Navigator",
    "全屏(&F)": "&Full screen",
    "适合宽度": "Fit Width",
    "适合页面": "Fit Page",

    # ---- Navigate ----
    "第一页": "First page",
    "上一页": "Previous page",
    "下一页": "Next page",
    "最后一页": "Last page",
    "跳转到页(&G)…": "&Go to page…",
    "跳转到页": "Go to page",
    "页码：": "Page:",

    # ---- Page ops ----
    "插入空白页(&B)…": "Insert &blank page…",
    "从 PDF 插入页…": "Insert pages from PDF…",
    "删除当前页": "Delete current page",
    "复制当前页": "Duplicate current page",
    "顺时针旋转页面": "Rotate page clockwise",
    "逆时针旋转页面": "Rotate page counter-clockwise",
    "旋转 180°": "Rotate page 180°",
    "提取页面…": "Extract pages…",
    "提取页面": "Extract pages",
    "页码范围（例如 1-3,5）：": "Ranges (e.g. 1-3,5):",
    "裁剪到选区…": "Crop page to selection…",
    "裁剪": "Crop",
    "新的裁剪框 'x0,y0,x1,y1'（PDF 点）：":
        "New crop box as 'x0,y0,x1,y1' in PDF points:",
    "无法解析裁剪矩形。": "Could not parse rectangle.",
    "插入空白页": "Insert blank page",
    "宽度（pt）：": "Width (pt):",
    "高度（pt）：": "Height (pt):",
    "删除": "Delete",
    "无法删除全部页面。": "Cannot delete every page.",
    "删除页面": "Delete pages",
    "重排失败": "Reorder failed",
    "提取页面到": "Extract pages to",
    "插入": "Insert",
    "请选择有效的 PDF 文件。": "Choose a valid PDF file.",

    # ---- Tools ----
    "选择 / 平移": "Select / Pan",
    "手型": "Hand",
    "添加文字": "Add Text",
    "编辑已有文字": "Edit existing text",
    "高亮": "Highlight",
    "下划线": "Underline",
    "删除线": "Strikethrough",
    "波浪线": "Squiggly",
    "便笺": "Sticky Note",
    "便笺内容：": "Note text:",
    "内容：": "Text:",
    "自由文字框": "Free Text Box",
    "矩形": "Rectangle",
    "椭圆": "Ellipse",
    "直线": "Line",
    "箭头": "Arrow",
    "自由绘制": "Freehand",
    "橡皮擦（删除注解）": "Eraser (delete annotation)",
    "标记密涂": "Mark for Redaction",
    "插入图片": "Insert Image",
    "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)":
        "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
    "添加链接": "Add Link",
    "放置签名（先用菜单加载签名）": "Place signature (load via menu first)",
    "应用已标记密涂": "Apply marked redactions",
    "✍  插入签名…": "✍  Insert signature…",
    "手绘或从文件加载签名后单击放置到页面":
        "Draw or load a signature, then click on a page to place it",
    "签名已就绪——在页面上单击放置（按 Esc 或切换其他工具取消）。":
        "Signature ready — click on a page to place it (Esc / switch tools to cancel).",
    "应用密涂": "Apply redactions",
    "这将永久删除所有已标记密涂区域下的内容，是否继续？":
        "This permanently removes the content under all marked redactions. Continue?",
    "密涂失败": "Redaction failed",
    "自由文字": "Free text",
    "链接目标": "Link target",
    "输入 URL（https://...）或 'page:N'：":
        "Enter URL (https://...) or 'page:N':",
    "无效的 'page:N' 目标": "Invalid 'page:N' target",
    "选区内没有可高亮的文字。": "No text under selection to highlight.",
    "点击位置没有可编辑的文字。": "No editable text at click point.",
    "签名插入失败：{exc}": "Signature insert failed: {exc}",
    "文字编辑失败：{exc}": "Text edit failed: {exc}",

    # ---- Document ----
    "合并 PDF(&M)…": "&Merge PDFs…",
    "拆分 PDF(&S)…": "&Split PDF…",
    "添加水印(&W)…": "Add &watermark…",
    "添加页码(&P)…": "Add &page numbers…",
    "添加页眉/页脚(&H)…": "Add &header / footer…",
    "优化/压缩(&O)": "&Optimize / Compress",
    "加密(&E)…": "&Encrypt…",
    "移除加密(&R)": "&Remove encryption",
    "选择要合并的 PDF": "Choose PDFs to merge",
    "合并": "Merge",
    "是否将当前打开的文档放在最前？": "Prepend the currently open document?",
    "保存合并后的 PDF": "Save merged PDF",
    "合并失败": "Merge failed",
    "输出目录": "Output directory",
    "拆分": "Split",
    "拆分失败": "Split failed",
    "水印": "Watermark",
    "水印失败": "Watermark failed",
    "请选择图片文件。": "Choose an image file.",
    "添加页码失败": "Page numbers failed",
    "页眉页脚失败": "Header/Footer failed",
    "另存优化文件": "Save optimized as",
    "优化": "Optimize",
    "优化失败": "Optimize failed",
    "另存加密文件": "Save encrypted as",
    "加密": "Encrypt",
    "加密失败": "Encrypt failed",
    "另存解密文件": "Save decrypted as",
    "解密": "Decrypt",
    "解密失败": "Decrypt failed",

    # ---- Forms ----
    "编辑表单字段…": "Edit form fields…",
    "扁平化表单": "Flatten form",
    "表单": "Forms",
    "未检测到表单字段。": "No form fields detected.",
    "扁平化": "Flatten",
    "扁平化所有表单字段（之后将不能再编辑），是否继续？":
        "Flatten all form fields (no longer editable)?",

    # ---- Export ----
    "导出文本(&T)…": "Export &text…",
    "导出 HTML(&H)…": "Export &HTML…",
    "导出页面图片(&I)…": "Export page &images…",
    "提取嵌入图片(&E)…": "Extract embedded &images…",
    "导出文本": "Export text",
    "文本 (*.txt)": "Text (*.txt)",
    "导出 HTML": "Export HTML",
    "格式": "Format",
    "图片格式：": "Image format:",
    "分辨率（DPI）：": "Resolution (DPI):",
    "导出图片": "Export images",
    "导出失败": "Export failed",
    "提取图片": "Extract images",
    "提取失败": "Extract failed",

    # ---- Help / Donate ----
    "关于(&A)": "&About",
    "关于 PDF 编辑器": "About PDF Editor",
    "❤  支持作者": "❤  Support author",
    "支持作者": "Support author",
    "如果这个工具帮到了你，欢迎请作者喝杯咖啡 ☕":
        "If this tool helped, treat the author to a coffee ☕",
    "关闭": "Close",
    "（未打包收款码图片）": "(no donation image bundled)",

    # ---- Toolbars / status ----
    "主工具栏": "Main",
    "工具": "Tools",
    "描边": "Stroke",
    "填充": "Fill",
    "粗细": "Width",
    "字号": "Font",
    "选择颜色": "Choose color",

    # ---- Docks ----
    "页面缩略图": "Pages",
    "大纲": "Outline",
    "查找": "Find",
    "导航": "Navigator",
    "元素属性": "Element Inspector",

    # ---- Inspector ----
    "元素": "Element",
    "在编辑模式下点击元素以查看属性。": "Click an element in edit mode.",
    "点击页面上的元素查看属性。": "Click an element to inspect.",
    "开启内容编辑模式后此面板可用。":
        "Enable Edit Content mode to use this panel.",
    "已应用。点击其他元素继续编辑。":
        "Applied. Click another element to inspect.",
    "已删除。点击其他元素。": "Deleted. Click another element.",
    "应用失败：": "Apply failed: ",
    "删除失败：": "Delete failed: ",
    "拖动元素移动；用角点/边手柄缩放。": "Drag to move; corner/edge handles to resize.",
    "内容编辑模式会把每段文字和每张图片显示为可编辑元素。\n\n"
    "• 单击元素选中\n"
    "• 已选中元素再次单击可就地编辑文字\n"
    "• 拖动元素移动；拖角点/边手柄缩放\n"
    "• Del 删除；双击也可进入就地编辑":
        "Edit Content shows every text span and image as a selectable "
        "element.\n\n"
        "• Click to select\n"
        "• Click a selected element again to edit text in place\n"
        "• Drag to move; corner/edge handles to resize\n"
        "• Del to remove; double-click also opens inline edit",
    "文字段": "Text span",
    "在此修改文字与样式后点击「应用」；也可以再次点击元素就地编辑。":
        "Edit text / style here and click Apply; or click the element "
        "again on the page to edit in place.",
    "文字：": "Text:",
    "修改文字内容": "Edit text content",
    "字体：": "Family:",
    "无衬线（Helvetica）": "Sans (Helvetica)",
    "衬线（Times）": "Serif (Times)",
    "等宽（Courier）": "Mono (Courier)",
    "样式：": "Style:",
    "粗体": "Bold",
    "斜体": "Italic",
    "字号：": "Size:",
    "颜色：": "Color:",
    "位置：": "Bbox:",
    "应用": "Apply",
    "删除元素": "Delete element",
    "图片": "Image",
    "拖动元素移动位置；用角点/边手柄缩放。":
        "Drag to move; corner/edge handles to resize.",
    "拖动元素移动；用角点/边手柄缩放。":
        "Drag to move; corner/edge handles to resize.",

    # ---- Common dialogs ----
    "添加书签": "Add bookmark",
    "标题：": "Title:",
    "页码（从 1 开始）：": "Page (1-based):",
    "重命名书签": "Rename bookmark",
    "添加": "Add",
    "重命名": "Rename",
    "为当前页添加书签": "Add bookmark for current page",
    "书签": "Bookmark",
    "页码": "Page",
    "在文档中搜索…": "Find in document…",
    "清除": "Clear",
    "在末尾插入空白页": "Insert blank page at end",
    "复制此页": "Duplicate",
    "在此页后插入空白页": "Insert blank page after",
    "提取为新 PDF…": "Extract to new PDF…",
    "顺时针旋转": "Rotate clockwise",
    "逆时针旋转": "Rotate counter-clockwise",
    "选择 PDF": "Choose PDF",
    "从 PDF 插入页面": "Insert pages from PDF",
    "PDF 文件：": "PDF file:",
    "页面：": "Pages:",
    "插入到（0=开头）：": "Insert after (0 = beginning):",
    "浏览…": "Browse…",
    "类型：": "Type:",
    "文字": "Text",
    "图片：": "Image:",
    "不透明度：": "Opacity:",
    "旋转（文字）：": "Rotation (text):",
    "全部页（或 1-3,5,7-9）": "All pages (or e.g. 1-3,5,7-9)",
    "选择图片": "Choose image",
    "位置": "Position",
    "格式：": "Format:",
    "起始页码：": "Start at:",
    "页眉 / 页脚": "Header / Footer",
    "页眉：": "Header:",
    "页脚：": "Footer:",
    "拆分 PDF": "Split PDF",
    "每 N 页拆分": "Every N pages",
    "自定义范围": "Custom ranges",
    "方式：": "Mode:",
    "N：": "N:",
    "范围：": "Ranges:",
    "加密 PDF": "Encrypt PDF",
    "允许打印": "Allow printing",
    "允许复制文字": "Allow copying text",
    "允许修改": "Allow modifying",
    "允许添加注解": "Allow annotating",
    "用户密码：": "User password:",
    "所有者密码：": "Owner password:",
    "文档属性": "Document properties",
    "表单字段": "Form fields",
    "（未命名）": "(unnamed)",

    # ---- Signature dialog ----
    "插入签名": "Insert signature",
    "在下方用鼠标画签名：": "Draw your signature below with the mouse:",
    "笔粗：": "Width:",
    "颜色：": "Color:",
    "选择签名颜色": "Pick signature colour",
    "选择签名图片": "Choose signature image",
    "手绘签名": "Hand-drawn",
    "从文件加载签名（建议为透明背景的 PNG）：":
        "Load from a file (transparent PNG recommended):",
    "（未选择）": "(none selected)",
    "从文件加载": "From file",
    "签名": "Signature",
    "请先在画布上画签名。": "Please draw a signature on the canvas first.",
    "请选择签名图片文件。": "Please choose a signature image file.",
    "读取文件失败：{exc}": "Failed to read file: {exc}",
    "插入": "Insert",
    "取消": "Cancel",

    # ---- Language ----
    "Switch to English": "切换为中文",
}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------
def get_lang() -> str:
    return _LANG


def load_lang() -> None:
    """Restore the user's language preference, defaulting to Chinese."""
    global _LANG
    s = QSettings("LocalTools", "PDFEditor").value(_SETTINGS_KEY, "zh")
    _LANG = "en" if str(s) == "en" else "zh"


def set_lang(lang: str) -> None:
    global _LANG
    _LANG = "en" if lang == "en" else "zh"
    QSettings("LocalTools", "PDFEditor").setValue(_SETTINGS_KEY, _LANG)


_ZH: dict[str, str] = {v: k for k, v in EN.items()}


def tr(text: Optional[str]) -> str:
    """Translate a single string both ways.

    The dict is keyed by the Chinese source; the reverse map handles
    text that is currently in English (so toggling back to Chinese
    works without re-creating widgets).
    """
    if not text:
        return text or ""
    if _LANG == "en":
        return EN.get(text, text)
    return _ZH.get(text, text)


# ----------------------------------------------------------------------
# Widget-tree walker
# ----------------------------------------------------------------------
def _translate_action(act: QAction) -> None:
    t = act.text()
    if t:
        nt = tr(t)
        if nt != t:
            act.setText(nt)
    tip = act.statusTip()
    if tip:
        ntip = tr(tip)
        if ntip != tip:
            act.setStatusTip(ntip)
    tt = act.toolTip()
    if tt and tt != t:
        ntt = tr(tt)
        if ntt != tt:
            act.setToolTip(ntt)


def _translate_menu(menu: QMenu) -> None:
    t = menu.title()
    if t:
        menu.setTitle(tr(t))
    for a in menu.actions():
        _translate_action(a)
        if a.menu() is not None:
            _translate_menu(a.menu())


def apply_language(root: QWidget) -> None:
    """Translate the text properties of every translatable widget under
    `root`.  Idempotent; running again in the other language re-maps."""
    # MenuBar — direct walk
    if isinstance(root, QMenuBar):
        for a in root.actions():
            _translate_action(a)
            if a.menu() is not None:
                _translate_menu(a.menu())

    # Recurse children
    for w in root.findChildren(QWidget):
        if isinstance(w, QMenuBar):
            for a in w.actions():
                _translate_action(a)
                if a.menu() is not None:
                    _translate_menu(a.menu())
        elif isinstance(w, QMenu):
            _translate_menu(w)
        elif isinstance(w, QDockWidget):
            t = w.windowTitle()
            if t:
                w.setWindowTitle(tr(t))
        elif isinstance(w, QGroupBox):
            t = w.title()
            if t:
                w.setTitle(tr(t))
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                t = w.tabText(i)
                if t:
                    w.setTabText(i, tr(t))
        elif isinstance(w, QLineEdit):
            ph = w.placeholderText()
            if ph:
                w.setPlaceholderText(tr(ph))
        elif isinstance(w, QComboBox):
            for i in range(w.count()):
                t = w.itemText(i)
                if t:
                    w.setItemText(i, tr(t))
        elif isinstance(w, QLabel):
            t = w.text()
            if t:
                nt = tr(t)
                if nt != t:
                    w.setText(nt)
        elif isinstance(w, QAbstractButton):
            t = w.text()
            if t:
                nt = tr(t)
                if nt != t:
                    w.setText(nt)
            tt = w.toolTip()
            if tt:
                ntt = tr(tt)
                if ntt != tt:
                    w.setToolTip(ntt)

    # Window title on the top-level widget
    if root.isWindow():
        wt = root.windowTitle()
        if wt:
            # Don't re-translate if it already contains user data like " — file.pdf"
            sep = " — "
            if sep in wt:
                left, _, rest = wt.partition(sep)
                root.setWindowTitle(tr(left) + sep + rest)
            else:
                root.setWindowTitle(tr(wt))

    # Also walk QActions held directly by root (e.g., MainWindow has
    # toolbar actions that are children but not QWidgets).
    for a in root.findChildren(QAction):
        _translate_action(a)


# ----------------------------------------------------------------------
# Install a QDialog.exec() shim that auto-translates every dialog
# right before it shows.  This means every QDialog subclass picks up
# i18n for free without an apply_language(self) call per __init__.
# ----------------------------------------------------------------------
_dialog_patch_installed = False


def install_dialog_translation() -> None:
    """Patch QDialog.exec / showEvent so every dialog auto-translates."""
    global _dialog_patch_installed
    if _dialog_patch_installed:
        return
    from PyQt6.QtWidgets import QDialog

    _orig_exec = QDialog.exec
    _orig_open = QDialog.open
    _orig_show = QDialog.show

    def _maybe_translate(self):
        try:
            apply_language(self)
        except Exception:
            pass

    def _exec(self):
        _maybe_translate(self)
        return _orig_exec(self)

    def _open(self):
        _maybe_translate(self)
        return _orig_open(self)

    def _show(self):
        _maybe_translate(self)
        return _orig_show(self)

    QDialog.exec = _exec  # type: ignore[assignment]
    QDialog.open = _open  # type: ignore[assignment]
    QDialog.show = _show  # type: ignore[assignment]
    _dialog_patch_installed = True
