"""PDF document model wrapping PyMuPDF (fitz).

Provides the in-memory representation that the UI binds to. Tracks the
current path, dirty state, and a bounded undo/redo history of serialized
document bytes.
"""

from __future__ import annotations

import io
from typing import Optional

import fitz  # PyMuPDF
from PyQt6.QtCore import QObject, pyqtSignal


UNDO_LIMIT = 30


class PdfDocument(QObject):
    documentReplaced = pyqtSignal()  # entire doc swapped (open/close/undo/redo)
    pagesChanged = pyqtSignal()      # page set changed (insert/delete/reorder/rotate)
    pageContentChanged = pyqtSignal(int)  # single-page edit (annotation, text)
    dirtyChanged = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc: Optional[fitz.Document] = None
        self.path: Optional[str] = None
        self._dirty = False
        self._undo: list[bytes] = []
        self._redo: list[bytes] = []
        self._password: Optional[str] = None
        # Per-page list of rectangles the user has "logically deleted"
        # (covered with a white box) during this session.  The original
        # glyphs are still in the content stream — these rects tell
        # list_all_spans which spans to hide from the editable overlay
        # so the user doesn't see ghost copies of the moved text.
        self._covered_rects: dict[int, list[fitz.Rect]] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def new_blank(self, width: float = 595.0, height: float = 842.0) -> None:
        """Create an empty document (A4 by default)."""
        self.close()
        self.doc = fitz.open()
        self.doc.new_page(-1, width=width, height=height)
        self.path = None
        self._set_dirty(True)
        self.documentReplaced.emit()

    def open(self, path: str, password: Optional[str] = None) -> bool:
        self.close()
        doc = fitz.open(path)
        if doc.needs_pass:
            if not password or not doc.authenticate(password):
                doc.close()
                return False
            self._password = password
        self.doc = doc
        self.path = path
        self._set_dirty(False)
        self._undo.clear()
        self._redo.clear()
        self._covered_rects.clear()
        self.documentReplaced.emit()
        return True

    def close(self) -> None:
        if self.doc is not None:
            self.doc.close()
            self.doc = None
        self.path = None
        self._password = None
        self._set_dirty(False)
        self._undo.clear()
        self._redo.clear()
        self._covered_rects.clear()
        self.documentReplaced.emit()

    # ------------------------------------------------------------------
    # Logical-delete tracking — see _covered_rects field doc
    # ------------------------------------------------------------------
    def covered_rects(self, page_index: int) -> list:
        """All rectangles the editor has visually covered on this page."""
        return list(self._covered_rects.get(page_index, ()))

    def mark_covered(self, page_index: int, rect) -> None:
        self._covered_rects.setdefault(page_index, []).append(fitz.Rect(rect))

    def clear_covered(self, page_index: Optional[int] = None) -> None:
        if page_index is None:
            self._covered_rects.clear()
        else:
            self._covered_rects.pop(page_index, None)

    def uncover_at(self, page_index: int, rect) -> int:
        """Drop any covered_rect on `page_index` whose centre falls
        inside `rect`.  Used right after fresh content is inserted at
        `rect` — that area is no longer "logically deleted" no matter
        what previous moves stamped there.

        Returns the number of covered rects removed.
        """
        existing = self._covered_rects.get(page_index)
        if not existing:
            return 0
        r = fitz.Rect(rect)
        kept = []
        dropped = 0
        for cr in existing:
            cx = (cr.x0 + cr.x1) / 2.0
            cy = (cr.y0 + cr.y1) / 2.0
            if r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1:
                dropped += 1
                continue
            kept.append(cr)
        self._covered_rects[page_index] = kept
        return dropped

    def is_open(self) -> bool:
        return self.doc is not None

    def needs_password(self, path: str) -> bool:
        try:
            d = fitz.open(path)
            needs = d.needs_pass
            d.close()
            return needs
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------
    def save(self, path: Optional[str] = None, *, incremental: bool = False,
             garbage: int = 3, deflate: bool = True,
             encryption: Optional[dict] = None) -> str:
        """Save the document. Returns the path it was saved to."""
        assert self.doc is not None
        target = path or self.path
        if target is None:
            raise ValueError("No path to save to")
        kwargs: dict = dict(garbage=garbage, deflate=deflate)
        if encryption:
            kwargs.update(encryption)
        if incremental and target == self.path:
            kwargs["incremental"] = True
            kwargs["garbage"] = 0
        # If saving over the same path that the doc was opened from, fitz
        # disallows non-incremental save unless we write to a temp and swap.
        if target == self.path and not incremental:
            data = self.doc.tobytes(**{k: v for k, v in kwargs.items() if k != "incremental"})
            with open(target, "wb") as f:
                f.write(data)
        else:
            self.doc.save(target, **kwargs)
        self.path = target
        self._set_dirty(False)
        return target

    def to_bytes(self, **kwargs) -> bytes:
        assert self.doc is not None
        return self.doc.tobytes(**kwargs)

    # ------------------------------------------------------------------
    # Undo / Redo
    # ------------------------------------------------------------------
    def _snapshot_covered(self) -> dict[int, list]:
        return {k: list(v) for k, v in self._covered_rects.items()}

    def push_undo(self) -> None:
        """Snapshot current document for undo. Call BEFORE a mutation."""
        if self.doc is None:
            return
        try:
            snap = self.doc.tobytes(garbage=0, deflate=False)
        except Exception:
            return
        self._undo.append((snap, self._snapshot_covered()))
        if len(self._undo) > UNDO_LIMIT:
            self._undo.pop(0)
        self._redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> None:
        if not self._undo or self.doc is None:
            return
        cur = (self.doc.tobytes(garbage=0, deflate=False),
               self._snapshot_covered())
        self._redo.append(cur)
        data, covered = self._undo.pop()
        self._covered_rects = covered
        self._reload_from_bytes(data)

    def redo(self) -> None:
        if not self._redo or self.doc is None:
            return
        cur = (self.doc.tobytes(garbage=0, deflate=False),
               self._snapshot_covered())
        self._undo.append(cur)
        data, covered = self._redo.pop()
        self._covered_rects = covered
        self._reload_from_bytes(data)

    def _reload_from_bytes(self, data: bytes) -> None:
        try:
            self.doc.close()
        except Exception:
            pass
        self.doc = fitz.open(stream=data, filetype="pdf")
        self._set_dirty(True)
        self.documentReplaced.emit()

    # ------------------------------------------------------------------
    # Dirty
    # ------------------------------------------------------------------
    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirtyChanged.emit(value)

    @property
    def dirty(self) -> bool:
        return self._dirty

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------
    @property
    def page_count(self) -> int:
        return self.doc.page_count if self.doc is not None else 0

    def page(self, index: int) -> fitz.Page:
        assert self.doc is not None
        return self.doc[index]

    # ------------------------------------------------------------------
    # Metadata / outline
    # ------------------------------------------------------------------
    def metadata(self) -> dict:
        return dict(self.doc.metadata) if self.doc else {}

    def set_metadata(self, md: dict) -> None:
        assert self.doc is not None
        self.push_undo()
        self.doc.set_metadata(md)
        self._set_dirty(True)
        self.documentReplaced.emit()

    def toc(self) -> list:
        return self.doc.get_toc() if self.doc else []

    def set_toc(self, toc: list) -> None:
        assert self.doc is not None
        self.push_undo()
        self.doc.set_toc(toc)
        self._set_dirty(True)
        self.documentReplaced.emit()
