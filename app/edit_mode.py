"""WPS-like content edit mode.

When active, every text span and every embedded image on each rendered
page is wrapped in a selectable, movable, resizable overlay item.

Interactions per element:
  * single-click          – select (shows resize handles)
  * drag the body         – move
  * drag a corner / edge  – resize
  * double-click text     – edit text via dialog
  * Delete / Backspace    – remove (covers with background)

Edits are committed to the underlying PDF on mouse release; the affected
page is then re-rendered and the overlay rebuilt so everything stays in
sync.
"""

from __future__ import annotations

from typing import Optional

import fitz
from PyQt6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QKeyEvent, QPainter, QPen,
)
from PyQt6.QtWidgets import (
    QGraphicsItem,
    QGraphicsProxyWidget,
    QGraphicsRectItem,
    QGraphicsSceneMouseEvent,
    QLineEdit,
)

from .text_edit import (
    ImageInstance,
    TextSpan,
    delete_image,
    delete_text_span,
    find_images_on_page,
    list_all_spans,
    move_image,
    move_text_span,
    sample_background_color,
)


HANDLE_VISIBLE_SIZE = 5.5     # how big the white square LOOKS
HANDLE_HIT_PAD = 3.0          # extra invisible margin around the square
                              #   that still counts as a click on the handle
EDGE_HANDLE_MIN_SIDE = 24.0   # hide edge-midpoint handles if the element
                              # is shorter than this in the perpendicular axis
TEXT_PEN = QColor(70, 110, 220, 230)
IMAGE_PEN = QColor(220, 100, 60, 230)
SELECTED_PEN = QColor(0, 120, 215, 255)
MIN_ELEMENT_SIZE = 5.0


class ResizeHandle(QGraphicsRectItem):
    """A draggable handle that mutates the parent element's rectangle."""

    POSITIONS = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
    CURSORS = {
        "nw": Qt.CursorShape.SizeFDiagCursor,
        "n": Qt.CursorShape.SizeVerCursor,
        "ne": Qt.CursorShape.SizeBDiagCursor,
        "e": Qt.CursorShape.SizeHorCursor,
        "se": Qt.CursorShape.SizeFDiagCursor,
        "s": Qt.CursorShape.SizeVerCursor,
        "sw": Qt.CursorShape.SizeBDiagCursor,
        "w": Qt.CursorShape.SizeHorCursor,
    }

    def __init__(self, parent: "ElementItem", which: str):
        super().__init__(parent)
        self.which = which
        # Visual square is small, but the actual rect (and therefore
        # hit area) is bigger so it's easy to grab.  We paint the
        # smaller white box manually inside paint().
        click = HANDLE_VISIBLE_SIZE + 2 * HANDLE_HIT_PAD
        half_click = click / 2
        self.setRect(-half_click, -half_click, click, click)
        # Transparent for default drawing — we override paint() to draw
        # only the small visible square.
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setPen(QPen(Qt.GlobalColor.transparent))
        self.setZValue(20)
        self.setCursor(self.CURSORS[which])
        # Do NOT inherit ItemIsMovable: we handle drag ourselves.
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._drag_start_scene: Optional[QPointF] = None
        self._original_local_rect = QRectF()
        self._original_pos = QPointF()

    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        half = HANDLE_VISIBLE_SIZE / 2
        visible = QRectF(-half, -half, HANDLE_VISIBLE_SIZE, HANDLE_VISIBLE_SIZE)
        painter.fillRect(visible, QColor(255, 255, 255))
        pen = QPen(SELECTED_PEN, 1.0)
        painter.setPen(pen)
        painter.drawRect(visible)

    def update_position(self) -> None:
        """Place handle at the correct corner/edge of the parent's rect."""
        parent: ElementItem = self.parentItem()  # type: ignore[assignment]
        r = parent.rect()
        coords = {
            "nw": (r.left(), r.top()),
            "n": (r.center().x(), r.top()),
            "ne": (r.right(), r.top()),
            "e": (r.right(), r.center().y()),
            "se": (r.right(), r.bottom()),
            "s": (r.center().x(), r.bottom()),
            "sw": (r.left(), r.bottom()),
            "w": (r.left(), r.center().y()),
        }
        x, y = coords[self.which]
        self.setPos(x, y)

    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        parent: ElementItem = self.parentItem()  # type: ignore[assignment]
        self._drag_start_scene = event.scenePos()
        self._original_local_rect = QRectF(parent.rect())
        self._original_pos = parent.pos()
        # Make sure the parent stays selected during resize.
        parent.setSelected(True)
        event.accept()

    def mouseMoveEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_start_scene is None:
            return
        delta = event.scenePos() - self._drag_start_scene
        parent: ElementItem = self.parentItem()  # type: ignore[assignment]
        new_rect = QRectF(self._original_local_rect)
        new_pos = QPointF(self._original_pos)
        w = self.which
        # Resize works in parent's local coordinates. When dragging a
        # left/top edge, we adjust both pos and size to keep the opposite
        # edge anchored.
        if "n" in w:
            new_h = new_rect.height() - delta.y()
            if new_h < MIN_ELEMENT_SIZE:
                new_h = MIN_ELEMENT_SIZE
                delta_y = new_rect.height() - MIN_ELEMENT_SIZE
            else:
                delta_y = delta.y()
            new_pos.setY(self._original_pos.y() + delta_y)
            new_rect.setHeight(new_h)
        if "s" in w:
            new_h = new_rect.height() + delta.y()
            if new_h < MIN_ELEMENT_SIZE:
                new_h = MIN_ELEMENT_SIZE
            new_rect.setHeight(new_h)
        if "w" in w:
            new_w = new_rect.width() - delta.x()
            if new_w < MIN_ELEMENT_SIZE:
                new_w = MIN_ELEMENT_SIZE
                delta_x = new_rect.width() - MIN_ELEMENT_SIZE
            else:
                delta_x = delta.x()
            new_pos.setX(self._original_pos.x() + delta_x)
            new_rect.setWidth(new_w)
        if "e" in w:
            new_w = new_rect.width() + delta.x()
            if new_w < MIN_ELEMENT_SIZE:
                new_w = MIN_ELEMENT_SIZE
            new_rect.setWidth(new_w)
        parent.setPos(new_pos)
        parent.setRect(0, 0, new_rect.width(), new_rect.height())
        parent.update_handles()
        event.accept()

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if self._drag_start_scene is None:
            super().mouseReleaseEvent(event)
            return
        self._drag_start_scene = None
        parent: ElementItem = self.parentItem()  # type: ignore[assignment]
        parent.commit_resize()
        event.accept()


class ElementItem(QGraphicsRectItem):
    """Base overlay item for an editable PDF element."""

    def __init__(self, controller: "EditController", page_item, pdf_rect: fitz.Rect):
        super().__init__()
        self.controller = controller
        self.page_item = page_item
        self.original_pdf_rect = fitz.Rect(pdf_rect)
        self.zoom = controller.viewer.zoom
        w = max(MIN_ELEMENT_SIZE, pdf_rect.width * self.zoom)
        h = max(MIN_ELEMENT_SIZE, pdf_rect.height * self.zoom)
        self.setRect(0, 0, w, h)
        self.setPos(page_item.pos().x() + pdf_rect.x0 * self.zoom,
                    page_item.pos().y() + pdf_rect.y0 * self.zoom)
        pen = QPen(self._default_pen_color())
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidthF(1.0)
        pen.setCosmetic(True)
        self.setPen(pen)
        self.setBrush(QBrush(Qt.GlobalColor.transparent))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptHoverEvents(True)
        self.setZValue(5)
        self._handles: list[ResizeHandle] = []
        self._move_start: Optional[QPointF] = None
        self._was_selected_at_press = False
        for which in ResizeHandle.POSITIONS:
            h = ResizeHandle(self, which)
            self._handles.append(h)
        self.update_handles()
        self.set_handles_visible(False)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------
    def _default_pen_color(self) -> QColor:
        return TEXT_PEN

    def update_handles(self) -> None:
        for h in self._handles:
            h.update_position()
        if self.isSelected():
            self.set_handles_visible(True)

    def set_handles_visible(self, visible: bool) -> None:
        if not visible:
            for h in self._handles:
                h.setVisible(False)
            return
        # Selected: corner handles always show, edge-midpoint handles
        # only when the rect is wide / tall enough that they don't
        # crowd the corner ones.
        r = self.rect()
        show_horizontal = r.width() >= EDGE_HANDLE_MIN_SIDE
        show_vertical = r.height() >= EDGE_HANDLE_MIN_SIDE
        for h in self._handles:
            w = h.which
            if w in ("nw", "ne", "se", "sw"):
                h.setVisible(True)
            elif w in ("n", "s"):
                h.setVisible(show_horizontal)
            else:  # "e" or "w"
                h.setVisible(show_vertical)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            selected = bool(value)
            self.set_handles_visible(selected)
            pen = self.pen()
            pen.setStyle(Qt.PenStyle.SolidLine if selected else Qt.PenStyle.DashLine)
            pen.setWidthF(1.5 if selected else 1.0)
            pen.setColor(SELECTED_PEN if selected else self._default_pen_color())
            self.setPen(pen)
            if selected:
                self.controller.element_selected.emit(self)
        return super().itemChange(change, value)

    # ------------------------------------------------------------------
    # Move (entire rect drag) + click-on-selected → edit
    # ------------------------------------------------------------------
    def mousePressEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._move_start = self.pos()
            self._was_selected_at_press = self.isSelected()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if self._move_start is None:
            return
        delta = self.pos() - self._move_start
        was_selected = self._was_selected_at_press
        self._move_start = None
        self._was_selected_at_press = False
        moved = abs(delta.x()) > 0.5 or abs(delta.y()) > 0.5
        if moved:
            self.commit_move()
        elif was_selected:
            # Click on already-selected element without dragging — enter
            # in-place edit (PowerPoint / WPS style).
            self.handle_click_on_selected()

    def mouseDoubleClickEvent(self, event: QGraphicsSceneMouseEvent) -> None:
        self.handle_double_click()
        event.accept()

    # ------------------------------------------------------------------
    # Conversion: scene rect -> PDF rect on the page
    # ------------------------------------------------------------------
    def current_pdf_rect(self) -> fitz.Rect:
        r = self.rect()
        page_x = self.page_item.pos().x()
        page_y = self.page_item.pos().y()
        x0 = (self.pos().x() - page_x) / self.zoom
        y0 = (self.pos().y() - page_y) / self.zoom
        x1 = x0 + r.width() / self.zoom
        y1 = y0 + r.height() / self.zoom
        return fitz.Rect(x0, y0, x1, y1)

    # ------------------------------------------------------------------
    # To be overridden
    # ------------------------------------------------------------------
    def commit_move(self) -> None:
        pass

    def commit_resize(self) -> None:
        pass

    def commit_delete(self) -> None:
        pass

    def handle_double_click(self) -> None:
        pass

    def handle_click_on_selected(self) -> None:
        """Click on an already-selected element (no drag). Default: nothing."""
        pass

    def element_label(self) -> str:
        return "element"


class TextElementItem(ElementItem):
    def __init__(self, controller, page_item, span: TextSpan):
        super().__init__(controller, page_item, span.rect)
        self.span = span
        self.setToolTip(f"文字：{span.text[:40]}…" if len(span.text) > 40
                         else f"文字：{span.text}")

    def _default_pen_color(self) -> QColor:
        return TEXT_PEN

    def element_label(self) -> str:
        snippet = self.span.text[:24]
        if len(self.span.text) > 24:
            snippet += "…"
        return f"文字「{snippet}」"

    def commit_move(self) -> None:
        new_rect = self.current_pdf_rect()
        if new_rect == self.span.rect:
            return
        self.controller.commit_text_move(self, new_rect)

    def commit_resize(self) -> None:
        new_rect = self.current_pdf_rect()
        if new_rect == self.span.rect:
            return
        self.controller.commit_text_move(self, new_rect)

    def commit_delete(self) -> None:
        self.controller.commit_text_delete(self)

    def _open_inline_editor(self) -> None:
        editor = InlineTextEditor(self.controller, self)
        scene = self.scene()
        if scene is None:
            return
        scene.addItem(editor)
        editor.focus_editor()

    def handle_double_click(self) -> None:
        self._open_inline_editor()

    def handle_click_on_selected(self) -> None:
        self._open_inline_editor()


class ImageElementItem(ElementItem):
    def __init__(self, controller, page_item, image: ImageInstance):
        super().__init__(controller, page_item, image.rect)
        self.image = image
        self.setToolTip(f"图片 xref={image.xref}")

    def _default_pen_color(self) -> QColor:
        return IMAGE_PEN

    def element_label(self) -> str:
        return f"图片 #{self.image.xref}"

    def commit_move(self) -> None:
        new_rect = self.current_pdf_rect()
        if new_rect == self.image.rect:
            return
        self.controller.commit_image_move(self, new_rect)

    def commit_resize(self) -> None:
        new_rect = self.current_pdf_rect()
        if new_rect == self.image.rect:
            return
        self.controller.commit_image_move(self, new_rect)

    def commit_delete(self) -> None:
        self.controller.commit_image_delete(self)


class InlineTextEditor(QGraphicsProxyWidget):
    """A QLineEdit overlay placed exactly on top of a TextElementItem.

    Enter / focus-out commits the new text; Escape cancels.  While the
    editor is up, the underlying element is hidden so the dashed outline
    and handles don't show through.
    """

    def __init__(self, controller: "EditController", element: "TextElementItem"):
        super().__init__()
        self.controller = controller
        self.element = element
        self._committed = False
        self._cancelled = False

        line = QLineEdit()
        line.setText(element.span.text)
        line.setStyleSheet(
            "QLineEdit {"
            "  background-color: rgb(255, 252, 200);"      # solid pale yellow
            "  color: rgb(20, 20, 20);"                     # near-black
            "  border: 3px solid rgb(0, 100, 200);"
            "  padding: 4px 8px;"
            "  border-radius: 4px;"
            "  selection-background-color: rgb(0, 120, 215);"
            "  selection-color: white;"
            "}"
            "QLineEdit:focus {"
            "  border: 3px solid rgb(220, 80, 0);"          # orange when focused
            "  background-color: rgb(255, 255, 230);"
            "}"
        )
        # Roughly match the original font size for a "WYSIWYG" feel; use
        # a CJK-capable family so Chinese input renders correctly.
        font = QFont("Microsoft YaHei")
        font.setPointSizeF(max(9.0, float(element.span.size)))
        if element.span.is_bold:
            font.setBold(True)
        if element.span.is_italic:
            font.setItalic(True)
        line.setFont(font)
        line.selectAll()
        line.returnPressed.connect(self.commit)
        line.installEventFilter(self)

        self.setWidget(line)
        self.setZValue(200)

        sp = element.scenePos()
        r = element.rect()
        pad = 10
        self.setGeometry(QRectF(
            sp.x() - pad,
            sp.y() - pad,
            max(220.0, r.width() + 2 * pad),
            max(38.0, r.height() + 2 * pad),
        ))
        element.setVisible(False)

    def focus_editor(self) -> None:
        if self.widget() is not None:
            self.widget().setFocus()
            self.widget().selectAll()

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.FocusOut:
            # Defer commit slightly so dropdowns / dialogs the user clicked
            # don't lose their first input.
            self.commit()
            return False
        if event.type() == QEvent.Type.KeyPress:
            ke: QKeyEvent = event  # type: ignore[assignment]
            if ke.key() == Qt.Key.Key_Escape:
                self.cancel()
                return True
        return False

    def commit(self) -> None:
        if self._committed or self._cancelled:
            return
        self._committed = True
        new_text = self.widget().text()
        old_text = self.element.span.text
        element = self.element
        controller = self.controller
        self._cleanup()
        if new_text != old_text:
            controller.commit_text_replace(element, new_text)

    def cancel(self) -> None:
        if self._committed or self._cancelled:
            return
        self._cancelled = True
        self._cleanup()

    def _cleanup(self) -> None:
        try:
            self.element.setVisible(True)
        except Exception:
            pass
        scene = self.scene()
        if scene is not None:
            scene.removeItem(self)


class EditController(QObject):
    """Owns the overlay items for the viewer's edit mode."""

    activeChanged = pyqtSignal(bool)
    element_selected = pyqtSignal(object)  # ElementItem

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.active = False
        self._items_per_page: dict[int, list[ElementItem]] = {}

    # ------------------------------------------------------------------
    # Activation
    # ------------------------------------------------------------------
    def set_active(self, active: bool) -> None:
        if active == self.active:
            return
        self.active = active
        if active:
            self._build_all()
        else:
            self._clear_all()
        self.activeChanged.emit(active)

    def is_active(self) -> bool:
        return self.active

    # ------------------------------------------------------------------
    # Overlay (re)build
    # ------------------------------------------------------------------
    def _build_all(self) -> None:
        self._clear_all()
        if not self.viewer.doc.is_open():
            return
        for i in range(self.viewer.doc.page_count):
            self._build_page(i)

    def _clear_all(self) -> None:
        for items in self._items_per_page.values():
            for it in items:
                if it.scene() is not None:
                    it.scene().removeItem(it)
        self._items_per_page.clear()

    def _clear_page(self, page_index: int) -> None:
        items = self._items_per_page.pop(page_index, None)
        if not items:
            return
        for it in items:
            if it.scene() is not None:
                it.scene().removeItem(it)

    def _build_page(self, page_index: int) -> None:
        if not self.active:
            return
        if page_index >= len(self.viewer._page_items):
            return
        page_item = self.viewer._page_items[page_index]
        page = self.viewer.doc.page(page_index)
        # Spans the user "moved out of" or "deleted" earlier this
        # session are filtered out so they don't reappear as ghost
        # overlays after refresh_page.
        covered = self.viewer.doc.covered_rects(page_index)
        items: list[ElementItem] = []
        for span in list_all_spans(page, covered_rects=covered):
            it = TextElementItem(self, page_item, span)
            self.viewer._scene.addItem(it)
            items.append(it)
        for img in find_images_on_page(page):
            it = ImageElementItem(self, page_item, img)
            self.viewer._scene.addItem(it)
            items.append(it)
        # Z-order by inverse area: smaller elements sit ON TOP so the
        # user can still click them when they overlap a bigger one
        # (e.g. a footnote span nested inside a paragraph span, or a
        # signature image dropped over text).  Range [5.0 … 5.999].
        if items:
            areas = []
            for it in items:
                r = it.original_pdf_rect
                areas.append(max(1.0, r.width * r.height))
            biggest = max(areas) or 1.0
            for it, a in zip(items, areas):
                it.setZValue(5.0 + 0.999 * (1.0 - a / biggest))
        self._items_per_page[page_index] = items

    def refresh_page(self, page_index: int) -> None:
        if not self.active:
            return
        self._clear_page(page_index)
        self._build_page(page_index)

    def refresh_all(self) -> None:
        if not self.active:
            return
        self._build_all()

    # ------------------------------------------------------------------
    # Commits — called by the items themselves
    # ------------------------------------------------------------------
    def _resolve_span_font(self, span, text: Optional[str] = None):
        """Build the ordered font-fallback chain for re-inserting text.

        Returns (alias, font_files) where `font_files` is a list to be
        tried in order by `safe_insert_text`.  The first one that
        PyMuPDF can actually load wins, so we stack:

          1. The font that's *already embedded in the PDF* for this
             span — extracted via Document.extract_font.  For drag
             (text unchanged) the original subset definitely covers
             its own glyphs, so we always try this first.  For inline
             edits with new chars we only try it if `font_supports_text`
             confirms every codepoint is present.
          2. A bundled font matched by PSName (Microsoft YaHei →
             msyh.ttc, SimSun → simsun.ttc, …) via
             `pick_default_for_span`.
          3. If the target text contains CJK characters and the
             bundled match was base-14, ALSO append the first bundled
             CJK font — that way unrecognised Chinese PSNames still
             render as Chinese instead of falling all the way to
             Helvetica.
          4. The base-14 alias is the very last resort (handled by
             safe_insert_text itself, no file).
        """
        from .font_registry import (
            _first_bundled_cjk, get_font, pick_default_for_span,
        )
        from .text_edit import (
            extract_embedded_font, find_system_font_by_psname,
            font_supports_text,
        )
        page = self.viewer.doc.page(span.page_index)
        target_text = span.text if text is None else text
        is_drag = text is None or text == span.text
        has_cjk = any(ord(c) > 0xFF for c in target_text)

        font_files: list[str] = []

        # 1. Original embedded font extracted from the PDF resources.
        embedded = extract_embedded_font(page, span.font)
        if embedded:
            if is_drag or font_supports_text(embedded, target_text):
                font_files.append(embedded)

        # 2. The SAME font but resolved on the user's system by
        # PSName — works for many PDFs where extract_font returns
        # an unwrappable CFF / Type-1 binary but the font is
        # actually installed at C:\Windows\Fonts.
        sys_path = find_system_font_by_psname(span.font)
        if sys_path and sys_path not in font_files:
            font_files.append(sys_path)

        # 3. Bundled font matched by PSName (SimSun → simsun.ttc …).
        key = pick_default_for_span(span.font, bold=span.is_bold,
                                     italic=span.is_italic)
        fdef = get_font(key)
        if fdef and fdef.is_bundled and fdef.file:
            if fdef.file not in font_files:
                font_files.append(fdef.file)

        # 4. CJK escalation: ensure Chinese text never falls to Helv.
        if has_cjk:
            cjk_key = _first_bundled_cjk(bold=span.is_bold)
            if cjk_key:
                cjk_def = get_font(cjk_key)
                if cjk_def and cjk_def.file and cjk_def.file not in font_files:
                    font_files.append(cjk_def.file)

        alias = fdef.base14_alias if (fdef and fdef.base14_alias) else "helv"
        return alias, font_files

    def _report_resolved(self, span, font_files) -> None:
        """Status-bar note + append to a debug log on the desktop so
        the user can copy-paste a transcript if something still goes
        wrong."""
        import os as _os
        if not font_files:
            label = "base-14 helv"
            chain_summary = "(empty chain → CJK auto = msyh.ttc)"
        else:
            first = _os.path.basename(font_files[0])
            if first.startswith("kpdf_emb_"):
                label = f"{first}  (原嵌入字体)"
            else:
                label = first
            chain_summary = " → ".join(_os.path.basename(p) for p in font_files)
        try:
            self.viewer.statusMessage.emit(
                f"已用字体：{label}  ←  span PSName={span.font!r}"
            )
        except Exception:
            pass
        # Per-session debug log (overwritten each launch via 'w' on
        # first commit, append after that).
        try:
            log_dir = _os.path.expanduser("~/Desktop")
            if not _os.path.isdir(log_dir):
                log_dir = _os.path.expanduser("~")
            log_path = _os.path.join(log_dir, "kitty_pdf_font_log.txt")
            with open(log_path, "a", encoding="utf-8") as fp:
                fp.write(
                    f"span PSName={span.font!r}  text={span.text[:30]!r}\n"
                    f"  chain: {chain_summary}\n"
                    f"  used : {label}\n\n"
                )
        except Exception:
            pass

    def commit_text_move(self, item: TextElementItem, new_rect: fitz.Rect) -> None:
        doc = self.viewer.doc
        page = doc.page(item.span.page_index)
        bg = sample_background_color(page, item.span.rect)
        alias, font_files = self._resolve_span_font(item.span)
        doc.push_undo()
        move_text_span(page, item.span, new_rect,
                       font_alias=alias, font_files=font_files,
                       background=bg)
        # Logically delete the old position — cover_rect only painted
        # over it; the glyphs are still in the content stream so we
        # need to filter them out of the overlay manually.
        doc.mark_covered(item.span.page_index, item.span.rect)
        doc.mark_dirty()
        doc.pageContentChanged.emit(item.span.page_index)
        self._report_resolved(item.span, font_files)
        self.refresh_page(item.span.page_index)

    def commit_text_delete(self, item: TextElementItem) -> None:
        doc = self.viewer.doc
        page = doc.page(item.span.page_index)
        bg = sample_background_color(page, item.span.rect)
        doc.push_undo()
        delete_text_span(page, item.span, background=bg)
        doc.mark_covered(item.span.page_index, item.span.rect)
        doc.mark_dirty()
        doc.pageContentChanged.emit(item.span.page_index)
        self.refresh_page(item.span.page_index)

    def commit_text_edit(self, item: TextElementItem) -> None:
        # Delegate back to the viewer so it can show the existing dialog.
        self.viewer._edit_text_via_dialog(item.span.page_index, item.span)
        self.refresh_page(item.span.page_index)

    def commit_text_replace(self, item: TextElementItem, new_text: str) -> None:
        """Replace text content keeping the original style."""
        from .text_edit import replace_span
        span = item.span
        # Pass the NEW text so the embedded-font glyph-coverage check
        # can fall back to a bundled font if the user typed characters
        # the original subset doesn't have.
        alias, font_files = self._resolve_span_font(span, text=new_text)
        doc = self.viewer.doc
        page = doc.page(span.page_index)
        bg = sample_background_color(page, span.rect)
        doc.push_undo()
        replace_span(page, span, new_text,
                     font_alias=alias, font_files=font_files,
                     background=bg)
        # The original span's glyphs are still in the content stream
        # (cover_rect only painted on top). Filter them from the
        # rebuilt overlay so we don't end up with two TextElementItems
        # for what the user sees as a single edited span.
        doc.mark_covered(span.page_index, span.rect)
        doc.mark_dirty()
        doc.pageContentChanged.emit(span.page_index)
        self._report_resolved(span, font_files)
        self.refresh_page(span.page_index)

    def commit_image_move(self, item: ImageElementItem, new_rect: fitz.Rect) -> None:
        doc = self.viewer.doc
        page = doc.page(item.image.page_index)
        bg = sample_background_color(page, item.image.rect)
        doc.push_undo()
        move_image(page, item.image, new_rect, background=bg)
        doc.mark_dirty()
        doc.pageContentChanged.emit(item.image.page_index)
        self.refresh_page(item.image.page_index)

    def commit_image_delete(self, item: ImageElementItem) -> None:
        doc = self.viewer.doc
        page = doc.page(item.image.page_index)
        bg = sample_background_color(page, item.image.rect)
        doc.push_undo()
        delete_image(page, item.image, background=bg)
        doc.mark_dirty()
        doc.pageContentChanged.emit(item.image.page_index)
        self.refresh_page(item.image.page_index)

    # ------------------------------------------------------------------
    # Delete selected (called by viewer keyboard handler)
    # ------------------------------------------------------------------
    def delete_selected(self) -> bool:
        scene = self.viewer._scene
        if scene is None:
            return False
        deleted = False
        for it in list(scene.selectedItems()):
            if isinstance(it, ElementItem):
                it.commit_delete()
                deleted = True
        return deleted
