"""PDF viewer / editor canvas.

`PdfView` renders the current document via a `QGraphicsScene`, paints
each page as a `PageItem`, supports zoom/pan, and dispatches mouse
events to a tool handler that performs the actual edits via PyMuPDF.
"""

from __future__ import annotations

from typing import Optional

import fitz
from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt, pyqtSignal, QEvent
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
    QMouseEvent,
)
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsPathItem,
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsView,
    QInputDialog,
    QFileDialog,
)

from .document import PdfDocument
from .edit_mode import EditController, ElementItem
from .text_edit import (
    TextSpan,
    find_text_span_at,
    map_to_base14,
    replace_span,
    sample_background_color,
)
from .tools import (
    Tool,
    ToolSettings,
    add_link,
    apply_freetext,
    apply_highlight_like,
    apply_ink,
    apply_line,
    apply_note,
    apply_redact_mark,
    apply_shape,
    insert_image,
    insert_text_at,
)


PAGE_GAP = 12.0          # gap between pages, in scene units (== zoomed PDF points)
PAGE_MARGIN = 16.0       # outer scene margin
SEARCH_HIGHLIGHT = QColor(255, 200, 0, 110)


def _qimage_from_pixmap(pix: fitz.Pixmap) -> QImage:
    """Convert a fitz.Pixmap to a QImage (no alpha)."""
    if pix.alpha:
        fmt = QImage.Format.Format_RGBA8888
    else:
        fmt = QImage.Format.Format_RGB888
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt)
    # Copy so the underlying buffer doesn't get reclaimed.
    return img.copy()


class PageItem(QGraphicsPixmapItem):
    """A rendered PDF page positioned in the scene at `zoom` scale."""

    def __init__(self, page_index: int, page_rect: fitz.Rect):
        super().__init__()
        self.page_index = page_index
        self.page_rect = page_rect  # rotated page rect in PDF coords (origin 0,0)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)

    def set_render(self, pixmap: QPixmap, zoom: float, dpr: float) -> None:
        pixmap.setDevicePixelRatio(dpr)
        self.setPixmap(pixmap)
        # Drawn size in scene units = page_rect.size * zoom
        # The QGraphicsPixmapItem renders the pixmap at its native pixel size by
        # default; we scale so the displayed size matches scene units.
        target_w = self.page_rect.width * zoom
        target_h = self.page_rect.height * zoom
        actual_w = pixmap.width() / dpr
        actual_h = pixmap.height() / dpr
        if actual_w > 0 and actual_h > 0:
            sx = target_w / actual_w
            sy = target_h / actual_h
            self.setTransform(QTransform().scale(sx, sy))


class PdfView(QGraphicsView):
    pageHovered = pyqtSignal(int)               # mouse moved into a page
    pageClicked = pyqtSignal(int)               # left-click registered on a page
    zoomChanged = pyqtSignal(float)
    selectionChanged = pyqtSignal(int)          # number of currently-marked items
    annotationsModified = pyqtSignal(int)       # page index whose annots were changed
    statusMessage = pyqtSignal(str)

    def __init__(self, document: PdfDocument, parent=None):
        super().__init__(parent)
        self.doc = document
        self.tool_settings = ToolSettings()
        self._zoom = 1.0
        self._fit_mode: Optional[str] = None  # None, "width", "page"
        self._page_items: list[PageItem] = []
        self._render_cache: dict[int, tuple[float, QPixmap]] = {}  # page_index -> (zoom, pix)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setBackgroundBrush(QBrush(QColor(80, 80, 86)))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setMouseTracking(True)

        # Live preview items during drag
        self._press_scene: Optional[QPointF] = None
        self._press_page_index: Optional[int] = None
        self._press_page_pt: Optional[fitz.Point] = None
        self._preview_item: Optional[QGraphicsItem] = None
        self._ink_strokes: list[list[fitz.Point]] = []
        self._ink_current: list[fitz.Point] = []
        self._ink_path: Optional[QGraphicsPathItem] = None
        self._search_overlays: list[QGraphicsRectItem] = []
        self._panning = False
        self._pan_start = QPointF()
        # Pending signature image bytes, set by the main window before
        # activating Tool.SIGNATURE.  Reset after first use.
        self._pending_signature: Optional[bytes] = None
        self._signature_default_size = (180.0, 70.0)

        # Lazy page rendering: only pages intersecting the viewport (plus
        # a small margin) get a real pixmap; the rest stay as cheap
        # placeholder fills.  Triggered on scroll via a debounced timer.
        self._rendered_pages: set[int] = set()
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.setInterval(60)
        self._scroll_timer.timeout.connect(self._render_visible_pages)
        self.verticalScrollBar().valueChanged.connect(lambda _v: self._scroll_timer.start())
        self.horizontalScrollBar().valueChanged.connect(lambda _v: self._scroll_timer.start())

        # Wire signals
        self.doc.documentReplaced.connect(self._on_document_replaced)
        self.doc.pagesChanged.connect(self._on_pages_changed)
        self.doc.pageContentChanged.connect(self._on_page_changed)

        # Content-edit overlay controller (WPS-style edit mode)
        self.edit_controller = EditController(self)

    # ------------------------------------------------------------------
    # Tool selection
    # ------------------------------------------------------------------
    def set_tool(self, tool: Tool) -> None:
        self.tool_settings.tool = tool
        # Update drag mode for SELECT/HAND
        if tool in (Tool.SELECT, Tool.HAND):
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag if tool == Tool.HAND
                              else QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor if tool == Tool.HAND
                                     else Qt.CursorShape.ArrowCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)

    # ------------------------------------------------------------------
    # Zoom
    # ------------------------------------------------------------------
    @property
    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float, *, anchor_under_mouse: bool = False) -> None:
        value = max(0.1, min(8.0, value))
        if abs(value - self._zoom) < 1e-3:
            return
        self._zoom = value
        self._fit_mode = None
        self._render_cache.clear()
        self.relayout()
        self.zoomChanged.emit(self._zoom)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.25)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.25)

    def fit_width(self) -> None:
        if not self._page_items:
            return
        max_w = max(p.page_rect.width for p in self._page_items)
        avail = max(50, self.viewport().width() - int(PAGE_MARGIN * 2))
        self.set_zoom(avail / max_w)
        self._fit_mode = "width"

    def fit_page(self) -> None:
        if not self._page_items:
            return
        idx = self.current_page_index()
        page = self._page_items[idx]
        avail_w = max(50, self.viewport().width() - int(PAGE_MARGIN * 2))
        avail_h = max(50, self.viewport().height() - int(PAGE_MARGIN * 2))
        zw = avail_w / page.page_rect.width
        zh = avail_h / page.page_rect.height
        self.set_zoom(min(zw, zh))
        self._fit_mode = "page"

    # ------------------------------------------------------------------
    # Layout & rendering
    # ------------------------------------------------------------------
    def _on_document_replaced(self) -> None:
        # IMPORTANT: drop edit-overlay references BEFORE the scene is
        # cleared.  Otherwise relayout() destroys the underlying C++
        # graphics items and a later refresh_all() segfaults trying to
        # call .scene() on the dangling Python wrappers.
        if hasattr(self, "edit_controller"):
            self.edit_controller._items_per_page.clear()
        self._render_cache.clear()
        self.relayout()
        if hasattr(self, "edit_controller") and self.edit_controller.is_active():
            self.edit_controller.refresh_all()

    def _on_pages_changed(self) -> None:
        if hasattr(self, "edit_controller"):
            self.edit_controller._items_per_page.clear()
        self._render_cache.clear()
        self.relayout()
        if hasattr(self, "edit_controller") and self.edit_controller.is_active():
            self.edit_controller.refresh_all()

    def _on_page_changed(self, page_index: int) -> None:
        if page_index in self._render_cache:
            del self._render_cache[page_index]
        self._rendered_pages.discard(page_index)
        if 0 <= page_index < len(self._page_items):
            item = self._page_items[page_index]
            if item.sceneBoundingRect().intersects(self._viewport_scene_rect()):
                self._render_page(page_index)
                self._rendered_pages.add(page_index)
            else:
                self._set_placeholder(item)
        if hasattr(self, "edit_controller") and self.edit_controller.is_active():
            self.edit_controller.refresh_page(page_index)

    def relayout(self) -> None:
        self._scene.clear()
        self._page_items.clear()
        self._rendered_pages.clear()
        self._search_overlays.clear()
        self._preview_item = None
        if not self.doc.is_open():
            self._scene.setSceneRect(QRectF(0, 0, 1, 1))
            return
        y = PAGE_MARGIN
        widths = []
        for i in range(self.doc.page_count):
            page = self.doc.page(i)
            rect = page.rect  # rotated rect (origin 0,0)
            item = PageItem(i, rect)
            item.setPos(0, y)  # placeholder; we'll center later
            self._scene.addItem(item)
            self._page_items.append(item)
            widths.append(rect.width)
            y += rect.height * self._zoom + PAGE_GAP
        max_w = max(widths) if widths else 1.0
        view_w = max_w * self._zoom + PAGE_MARGIN * 2
        # Reposition centered, give each page a cheap placeholder so its
        # bounding box is correct before the real pixmap arrives.
        for item in self._page_items:
            cx = (view_w - item.page_rect.width * self._zoom) / 2
            item.setPos(cx, item.pos().y())
            self._set_placeholder(item)
        self._scene.setSceneRect(0, 0, view_w, y - PAGE_GAP + PAGE_MARGIN)
        # Only render what's actually visible; the rest renders on scroll.
        self._render_visible_pages()
        # Rebuild content-edit overlay (it was wiped by scene.clear()).
        if hasattr(self, "edit_controller") and self.edit_controller.is_active():
            # _items_per_page references are now dangling; just rebuild.
            self.edit_controller._items_per_page.clear()
            for i in range(self.doc.page_count):
                self.edit_controller._build_page(i)

    def _set_placeholder(self, item: "PageItem") -> None:
        """Give a page item a cheap solid-white pixmap so layout is
        correct before the real render lands.
        """
        dpr = float(self.devicePixelRatioF())
        w = max(1, int(item.page_rect.width * self._zoom * dpr))
        h = max(1, int(item.page_rect.height * self._zoom * dpr))
        pix = QPixmap(w, h)
        pix.fill(QColor(255, 255, 255))
        item.set_render(pix, self._zoom, dpr)

    def _viewport_scene_rect(self, margin_pages: float = 1.0) -> QRectF:
        """Scene-space rectangle of what's on screen, expanded by
        `margin_pages` viewport heights so neighbours pre-render.
        """
        r = self.mapToScene(self.viewport().rect()).boundingRect()
        if margin_pages > 0:
            m = r.height() * margin_pages
            r.adjust(0, -m, 0, m)
        return r

    def _render_visible_pages(self) -> None:
        if not self._page_items:
            return
        target = self._viewport_scene_rect()
        for i, item in enumerate(self._page_items):
            if item.sceneBoundingRect().intersects(target) and i not in self._rendered_pages:
                self._render_page(i)
                self._rendered_pages.add(i)

    def _render_page(self, index: int) -> None:
        if not (0 <= index < len(self._page_items)):
            return
        item = self._page_items[index]
        page = self.doc.page(index)
        dpr = float(self.devicePixelRatioF())
        scale = self._zoom * dpr
        cache_key = (round(scale, 3),)
        cached = self._render_cache.get(index)
        if cached and cached[0] == cache_key[0]:
            pix = cached[1]
        else:
            mat = fitz.Matrix(scale, scale)
            pixmap = page.get_pixmap(matrix=mat, alpha=False, annots=True)
            qimg = _qimage_from_pixmap(pixmap)
            pix = QPixmap.fromImage(qimg)
            self._render_cache[index] = (cache_key[0], pix)
        item.set_render(pix, self._zoom, dpr)

    # ------------------------------------------------------------------
    # Coordinate helpers
    # ------------------------------------------------------------------
    def _scene_to_page(self, scene_pt: QPointF) -> tuple[Optional[int], Optional[fitz.Point]]:
        for item in self._page_items:
            x = item.pos().x()
            y = item.pos().y()
            w = item.page_rect.width * self._zoom
            h = item.page_rect.height * self._zoom
            if x <= scene_pt.x() <= x + w and y <= scene_pt.y() <= y + h:
                px = (scene_pt.x() - x) / self._zoom
                py = (scene_pt.y() - y) / self._zoom
                return item.page_index, fitz.Point(px, py)
        return None, None

    def _page_rect_to_scene(self, page_index: int, rect: fitz.Rect) -> QRectF:
        item = self._page_items[page_index]
        z = self._zoom
        return QRectF(
            item.pos().x() + rect.x0 * z,
            item.pos().y() + rect.y0 * z,
            rect.width * z,
            rect.height * z,
        )

    def current_page_index(self) -> int:
        if not self._page_items:
            return 0
        # Find the page nearest the viewport center
        center = self.mapToScene(self.viewport().rect().center())
        best = 0
        best_dy = float("inf")
        for i, item in enumerate(self._page_items):
            mid_y = item.pos().y() + (item.page_rect.height * self._zoom) / 2
            d = abs(center.y() - mid_y)
            if d < best_dy:
                best_dy = d
                best = i
        return best

    def go_to_page(self, index: int) -> None:
        if 0 <= index < len(self._page_items):
            item = self._page_items[index]
            target = QRectF(item.pos().x(), item.pos().y(),
                            item.page_rect.width * self._zoom,
                            item.page_rect.height * self._zoom)
            self.centerOn(target.center())

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------
    def clear_search_overlay(self) -> None:
        for it in self._search_overlays:
            self._scene.removeItem(it)
        self._search_overlays.clear()

    def highlight_search(self, results: list[tuple[int, fitz.Rect]]) -> None:
        self.clear_search_overlay()
        for page_index, rect in results:
            scene_rect = self._page_rect_to_scene(page_index, rect)
            it = QGraphicsRectItem(scene_rect)
            it.setBrush(QBrush(SEARCH_HIGHLIGHT))
            it.setPen(QPen(Qt.PenStyle.NoPen))
            it.setZValue(50)
            self._scene.addItem(it)
            self._search_overlays.append(it)

    # ------------------------------------------------------------------
    # Mouse / wheel events
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            angle = event.angleDelta().y()
            if angle > 0:
                self.zoom_in()
            elif angle < 0:
                self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        tool = self.tool_settings.tool
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        scene_pt = self.mapToScene(event.position().toPoint())
        idx, page_pt = self._scene_to_page(scene_pt)
        if idx is None:
            super().mousePressEvent(event)
            return
        self._press_scene = scene_pt
        self._press_page_index = idx
        self._press_page_pt = page_pt
        self.pageClicked.emit(idx)

        # Alt+Click while in edit mode cycles through the stack of
        # ElementItems sitting under the cursor — lets you reach a
        # span that's hidden behind another element.
        if (self.edit_controller.is_active()
                and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            from .edit_mode import ElementItem
            stack = [it for it in self._scene.items(scene_pt)
                     if isinstance(it, ElementItem)]
            if stack:
                # Find the currently-selected element in the stack and
                # advance to the next one; if nothing was selected
                # here, take the topmost.
                current = next((it for it in stack if it.isSelected()), None)
                if current is not None and len(stack) > 1:
                    next_idx = (stack.index(current) + 1) % len(stack)
                    target = stack[next_idx]
                else:
                    target = stack[0]
                for it in stack:
                    it.setSelected(False)
                target.setSelected(True)
                self.statusMessage.emit(
                    f"已选中第 {stack.index(target) + 1} / {len(stack)} 个元素"
                    f"（Alt+点击切换）"
                )
                event.accept()
                return

        if tool == Tool.SELECT or tool == Tool.HAND:
            # Hint the user when they're clicking somewhere that has
            # multiple overlapping edit-mode elements.
            if self.edit_controller.is_active():
                from .edit_mode import ElementItem
                stack = [it for it in self._scene.items(scene_pt)
                         if isinstance(it, ElementItem)]
                if len(stack) >= 2:
                    self.statusMessage.emit(
                        f"此处共有 {len(stack)} 个重叠元素，"
                        f"按住 Alt 再点击可切换选择"
                    )
            super().mousePressEvent(event)
            return
        if tool == Tool.INK:
            self._ink_strokes = []
            self._ink_current = [page_pt]
            self._ink_path = QGraphicsPathItem()
            pen = QPen(self.tool_settings.stroke_color)
            pen.setWidthF(self.tool_settings.stroke_width)
            self._ink_path.setPen(pen)
            self._ink_path.setZValue(100)
            self._scene.addItem(self._ink_path)
            path = QPainterPath()
            path.moveTo(scene_pt)
            self._ink_path.setPath(path)
        elif tool == Tool.ERASER:
            self._try_erase_annot(idx, page_pt)
        elif tool == Tool.NOTE:
            text, ok = QInputDialog.getMultiLineText(self, "便笺", "便笺内容：", "")
            if ok:
                self._commit_note(idx, page_pt, text)
        elif tool == Tool.TEXT:
            text, ok = QInputDialog.getMultiLineText(self, "添加文字", "内容：", "")
            if ok and text:
                self._commit_text(idx, page_pt, text)
        elif tool == Tool.EDIT_TEXT:
            self._edit_existing_text(idx, page_pt)
        elif tool == Tool.IMAGE:
            path, _ = QFileDialog.getOpenFileName(self, "插入图片", "",
                                                   "图片 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
            if path:
                # default 200x200 box centered on click; user can drag later
                page = self.doc.page(idx)
                box = fitz.Rect(page_pt.x - 100, page_pt.y - 100,
                                page_pt.x + 100, page_pt.y + 100)
                page_rect = page.rect
                # clip to page
                box = box & page_rect
                self._commit_image(idx, box, path)
        elif tool == Tool.SIGNATURE:
            data = self._pending_signature
            if not data:
                self.statusMessage.emit("请先通过菜单加载签名。")
                return
            page = self.doc.page(idx)
            w, h = self._signature_default_size
            box = fitz.Rect(page_pt.x, page_pt.y, page_pt.x + w, page_pt.y + h)
            box = box & page.rect
            self.doc.push_undo()
            try:
                page.insert_image(box, stream=data, keep_proportion=True)
            except Exception as exc:
                self.statusMessage.emit(f"签名插入失败：{exc}")
                return
            self.doc.mark_dirty()
            self.doc.pageContentChanged.emit(idx)
            self.annotationsModified.emit(idx)
            # Auto-switch back to SELECT so the next click doesn't drop
            # another copy by accident.
            self.set_tool(Tool.SELECT)
        else:
            # Drag tools: rect/ellipse/line/arrow/highlight/etc.
            preview = self._make_preview_item(tool, scene_pt)
            if preview is not None:
                self._preview_item = preview
                self._scene.addItem(preview)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        scene_pt = self.mapToScene(event.position().toPoint())
        idx, page_pt = self._scene_to_page(scene_pt)
        if idx is not None:
            self.pageHovered.emit(idx)
        tool = self.tool_settings.tool
        if self._ink_path is not None and tool == Tool.INK and self._press_page_index == idx and page_pt is not None:
            self._ink_current.append(page_pt)
            path = self._ink_path.path()
            path.lineTo(scene_pt)
            self._ink_path.setPath(path)
        elif self._preview_item is not None and self._press_scene is not None:
            self._update_preview_item(tool, self._press_scene, scene_pt)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._panning and event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        tool = self.tool_settings.tool
        if self._press_page_index is None:
            super().mouseReleaseEvent(event)
            return
        scene_pt = self.mapToScene(event.position().toPoint())
        idx, page_pt = self._scene_to_page(scene_pt)
        # If release is outside, clamp release point to press page
        end_idx = self._press_page_index
        if idx != end_idx or page_pt is None:
            item = self._page_items[end_idx]
            px = (scene_pt.x() - item.pos().x()) / self._zoom
            py = (scene_pt.y() - item.pos().y()) / self._zoom
            px = max(0, min(item.page_rect.width, px))
            py = max(0, min(item.page_rect.height, py))
            page_pt = fitz.Point(px, py)
        start_pt = self._press_page_pt or page_pt
        try:
            if tool == Tool.INK and self._ink_current:
                # Ink may have multiple strokes if user briefly lifts; we use one
                self._ink_strokes.append(list(self._ink_current))
                self._commit_ink(end_idx, self._ink_strokes)
            elif tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.SQUIGGLY):
                rect = self._normalize_rect(start_pt, page_pt)
                self._commit_highlight(end_idx, rect, tool)
            elif tool in (Tool.RECT, Tool.ELLIPSE):
                rect = self._normalize_rect(start_pt, page_pt)
                self._commit_shape(end_idx, rect, tool)
            elif tool == Tool.LINE:
                self._commit_line(end_idx, start_pt, page_pt, arrow=False)
            elif tool == Tool.ARROW:
                self._commit_line(end_idx, start_pt, page_pt, arrow=True)
            elif tool == Tool.FREETEXT:
                rect = self._normalize_rect(start_pt, page_pt)
                if rect.is_empty:
                    rect = fitz.Rect(start_pt.x, start_pt.y, start_pt.x + 160, start_pt.y + 40)
                text, ok = QInputDialog.getMultiLineText(self, "自由文字", "内容：", "")
                if ok and text:
                    self._commit_freetext(end_idx, rect, text)
            elif tool == Tool.REDACT:
                rect = self._normalize_rect(start_pt, page_pt)
                if not rect.is_empty:
                    self._commit_redact(end_idx, rect)
            elif tool == Tool.LINK:
                rect = self._normalize_rect(start_pt, page_pt)
                if not rect.is_empty:
                    uri, ok = QInputDialog.getText(self, "链接目标",
                                                    "输入 URL（https://...）或 'page:N'：")
                    if ok and uri:
                        self._commit_link(end_idx, rect, uri)
        finally:
            self._clear_preview()
            self._press_scene = None
            self._press_page_index = None
            self._press_page_pt = None
            self._ink_strokes = []
            self._ink_current = []
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------
    def _make_preview_item(self, tool: Tool, start: QPointF) -> Optional[QGraphicsItem]:
        pen = QPen(self.tool_settings.stroke_color)
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(max(1.0, self.tool_settings.stroke_width))
        if tool in (Tool.RECT, Tool.ELLIPSE, Tool.FREETEXT, Tool.REDACT, Tool.LINK,
                     Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.SQUIGGLY):
            item = QGraphicsRectItem(QRectF(start, start))
            item.setPen(pen)
            if tool in (Tool.HIGHLIGHT, Tool.UNDERLINE, Tool.STRIKEOUT, Tool.SQUIGGLY):
                item.setBrush(QBrush(QColor(255, 255, 0, 60)))
            elif tool == Tool.REDACT:
                item.setBrush(QBrush(QColor(0, 0, 0, 80)))
            else:
                item.setBrush(QBrush(Qt.GlobalColor.transparent))
            item.setZValue(60)
            return item
        if tool in (Tool.LINE, Tool.ARROW):
            path = QPainterPath(start)
            path.lineTo(start)
            it = QGraphicsPathItem(path)
            it.setPen(pen)
            it.setZValue(60)
            return it
        return None

    def _update_preview_item(self, tool: Tool, start: QPointF, end: QPointF) -> None:
        if self._preview_item is None:
            return
        if isinstance(self._preview_item, QGraphicsRectItem):
            self._preview_item.setRect(QRectF(start, end).normalized())
        elif isinstance(self._preview_item, QGraphicsPathItem):
            path = QPainterPath(start)
            path.lineTo(end)
            self._preview_item.setPath(path)

    def _clear_preview(self) -> None:
        if self._preview_item is not None:
            self._scene.removeItem(self._preview_item)
            self._preview_item = None
        if self._ink_path is not None:
            self._scene.removeItem(self._ink_path)
            self._ink_path = None

    @staticmethod
    def _normalize_rect(p1: fitz.Point, p2: fitz.Point) -> fitz.Rect:
        x0, x1 = sorted([p1.x, p2.x])
        y0, y1 = sorted([p1.y, p2.y])
        return fitz.Rect(x0, y0, x1, y1)

    # ------------------------------------------------------------------
    # Commits
    # ------------------------------------------------------------------
    def _commit_highlight(self, page_index: int, rect: fitz.Rect, tool: Tool) -> None:
        if rect.is_empty:
            return
        self.doc.push_undo()
        page = self.doc.page(page_index)
        color = self.tool_settings.highlight_color
        annot = apply_highlight_like(page, rect, tool, color)
        if annot is None:
            self.statusMessage.emit("选区内没有可高亮的文字。")
            return
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_shape(self, page_index: int, rect: fitz.Rect, tool: Tool) -> None:
        if rect.is_empty:
            return
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_shape(page, rect, tool,
                    self.tool_settings.stroke_color,
                    self.tool_settings.fill_color,
                    self.tool_settings.stroke_width)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_line(self, page_index: int, p1: fitz.Point, p2: fitz.Point, *, arrow: bool) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_line(page, p1, p2, self.tool_settings.stroke_color,
                   self.tool_settings.stroke_width, arrow)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_ink(self, page_index: int, strokes: list[list[fitz.Point]]) -> None:
        if not strokes or not strokes[0]:
            return
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_ink(page, strokes, self.tool_settings.stroke_color,
                  self.tool_settings.stroke_width)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_freetext(self, page_index: int, rect: fitz.Rect, text: str) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_freetext(page, rect, text,
                       self.tool_settings.font_size,
                       self.tool_settings.text_color,
                       self.tool_settings.stroke_color)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_note(self, page_index: int, point: fitz.Point, text: str) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_note(page, point, text)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_text(self, page_index: int, point: fitz.Point, text: str) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        insert_text_at(page, point, text,
                       self.tool_settings.font_size,
                       self.tool_settings.font_name,
                       self.tool_settings.text_color)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_image(self, page_index: int, rect: fitz.Rect, path: str) -> None:
        if rect.is_empty:
            return
        self.doc.push_undo()
        page = self.doc.page(page_index)
        insert_image(page, rect, path)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_redact(self, page_index: int, rect: fitz.Rect) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        apply_redact_mark(page, rect)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _commit_link(self, page_index: int, rect: fitz.Rect, uri: str) -> None:
        self.doc.push_undo()
        page = self.doc.page(page_index)
        if uri.startswith("page:"):
            try:
                target = int(uri.split(":", 1)[1]) - 1
                add_link(page, rect, page_to=target)
            except Exception:
                self.statusMessage.emit("无效的 'page:N' 目标")
                return
        else:
            add_link(page, rect, uri=uri)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _edit_existing_text(self, page_index: int, point: fitz.Point) -> None:
        page = self.doc.page(page_index)
        span = find_text_span_at(page, point)
        if span is None:
            self.statusMessage.emit("点击位置没有可编辑的文字。")
            return
        self._edit_text_via_dialog(page_index, span)

    def _edit_text_via_dialog(self, page_index: int, span: TextSpan) -> None:
        page = self.doc.page(page_index)
        from .dialogs import EditTextDialog  # local import to avoid cycle
        suggested_alias = map_to_base14(span)
        bg = sample_background_color(page, span.rect)
        dlg = EditTextDialog(span, suggested_alias, bg, self)
        if not dlg.exec():
            return
        v = dlg.values()
        self.doc.push_undo()
        try:
            replace_span(
                page, span, v["text"],
                font_alias=v["font_alias"],
                font_size=v["font_size"],
                text_color=v["text_color"],
                background=v["background"],
            )
        except Exception as exc:
            self.statusMessage.emit(f"文字编辑失败：{exc}")
            return
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _try_erase_annot(self, page_index: int, point: fitz.Point) -> None:
        page = self.doc.page(page_index)
        target = None
        for annot in page.annots() or []:
            if annot.rect.contains(point):
                target = annot
                break
        if target is None:
            return
        self.doc.push_undo()
        page.delete_annot(target)
        self.doc.mark_dirty()
        self.doc.pageContentChanged.emit(page_index)
        self.annotationsModified.emit(page_index)

    def _invalidate_page(self, page_index: int) -> None:
        if page_index in self._render_cache:
            del self._render_cache[page_index]
        self._rendered_pages.discard(page_index)
        if 0 <= page_index < len(self._page_items):
            item = self._page_items[page_index]
            if item.sceneBoundingRect().intersects(self._viewport_scene_rect()):
                self._render_page(page_index)
                self._rendered_pages.add(page_index)

    # ------------------------------------------------------------------
    # Keyboard
    # ------------------------------------------------------------------
    def keyPressEvent(self, event):
        if (event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                and self.edit_controller.is_active()):
            if self.edit_controller.delete_selected():
                event.accept()
                return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Resize re-fit
    # ------------------------------------------------------------------
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._fit_mode == "width":
            self.fit_width()
        elif self._fit_mode == "page":
            self.fit_page()
        # New page area may have come into view.
        self._scroll_timer.start()
