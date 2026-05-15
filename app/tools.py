"""Tool definitions for the PDF editor.

A tool object knows how to react to mouse events on a page (in PDF
coordinates) and how to commit the resulting edit to the document via
PyMuPDF.  Each `apply` is preceded by `document.push_undo()` by the
caller so it can be reverted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional

import fitz
from PyQt6.QtGui import QColor


class Tool(Enum):
    SELECT = auto()           # Pan/select; default
    HAND = auto()             # Pan only
    TEXT = auto()             # Insert text box
    EDIT_TEXT = auto()        # Edit existing text (click a span)
    HIGHLIGHT = auto()        # Highlight underlying text in dragged rect
    UNDERLINE = auto()
    STRIKEOUT = auto()
    SQUIGGLY = auto()
    NOTE = auto()             # Sticky note (point)
    FREETEXT = auto()         # Free text annotation (drag rect)
    RECT = auto()             # Rectangle annotation
    ELLIPSE = auto()          # Circle/ellipse annotation
    LINE = auto()             # Line annotation
    ARROW = auto()            # Line with end arrow
    INK = auto()              # Freehand drawing
    ERASER = auto()           # Click an annotation to remove it
    REDACT = auto()           # Mark area for redaction
    IMAGE = auto()            # Click to insert image
    LINK = auto()             # Drag to create link (URI or page)
    SIGNATURE = auto()        # Click to place a pre-loaded signature image


@dataclass
class ToolSettings:
    tool: Tool = Tool.SELECT
    stroke_color: QColor = field(default_factory=lambda: QColor(255, 0, 0))
    fill_color: QColor = field(default_factory=lambda: QColor(255, 255, 0, 128))
    stroke_width: float = 1.5
    font_name: str = "helv"  # PyMuPDF builtin: helv/cour/times
    font_size: float = 12.0
    text_color: QColor = field(default_factory=lambda: QColor(0, 0, 0))
    highlight_color: QColor = field(default_factory=lambda: QColor(255, 255, 0))


def qcolor_to_tuple(c: QColor) -> tuple[float, float, float]:
    return (c.redF(), c.greenF(), c.blueF())


def apply_highlight_like(page: fitz.Page, rect: fitz.Rect, kind: Tool,
                         color: QColor) -> Optional[fitz.Annot]:
    """Highlight every word in `rect`. Returns the new annotation or None."""
    words = page.get_text("words", clip=rect)
    if not words:
        # Fall back to highlighting the rect itself
        quads = [rect.quad]
    else:
        quads = []
        for w in words:
            wr = fitz.Rect(w[:4])
            if rect.intersects(wr):
                quads.append(wr.quad)
        if not quads:
            return None
    if kind == Tool.HIGHLIGHT:
        annot = page.add_highlight_annot(quads)
    elif kind == Tool.UNDERLINE:
        annot = page.add_underline_annot(quads)
    elif kind == Tool.STRIKEOUT:
        annot = page.add_strikeout_annot(quads)
    elif kind == Tool.SQUIGGLY:
        annot = page.add_squiggly_annot(quads)
    else:
        return None
    annot.set_colors(stroke=qcolor_to_tuple(color))
    annot.update()
    return annot


def apply_shape(page: fitz.Page, rect: fitz.Rect, kind: Tool,
                stroke: QColor, fill: Optional[QColor], width: float) -> fitz.Annot:
    if kind == Tool.RECT:
        annot = page.add_rect_annot(rect)
    elif kind == Tool.ELLIPSE:
        annot = page.add_circle_annot(rect)
    else:
        raise ValueError(kind)
    colors = {"stroke": qcolor_to_tuple(stroke)}
    if fill is not None and fill.alpha() > 0:
        colors["fill"] = qcolor_to_tuple(fill)
    annot.set_colors(**colors)
    annot.set_border(width=width)
    if fill is not None:
        annot.set_opacity(fill.alphaF())
    annot.update()
    return annot


def apply_line(page: fitz.Page, p1: fitz.Point, p2: fitz.Point,
               stroke: QColor, width: float, arrow: bool) -> fitz.Annot:
    annot = page.add_line_annot(p1, p2)
    annot.set_colors(stroke=qcolor_to_tuple(stroke))
    annot.set_border(width=width)
    if arrow:
        annot.set_line_ends(fitz.PDF_ANNOT_LE_NONE, fitz.PDF_ANNOT_LE_OPEN_ARROW)
    annot.update()
    return annot


def apply_ink(page: fitz.Page, strokes: list[list[fitz.Point]],
              color: QColor, width: float) -> fitz.Annot:
    # PyMuPDF expects sequences of (x, y) float pairs, not Point objects.
    normalized = [[(float(p.x), float(p.y)) for p in stroke] for stroke in strokes if stroke]
    annot = page.add_ink_annot(normalized)
    annot.set_colors(stroke=qcolor_to_tuple(color))
    annot.set_border(width=width)
    annot.update()
    return annot


def apply_freetext(page: fitz.Page, rect: fitz.Rect, text: str,
                   font_size: float, color: QColor, border: QColor) -> fitz.Annot:
    annot = page.add_freetext_annot(
        rect, text,
        fontsize=font_size,
        text_color=qcolor_to_tuple(color),
        align=fitz.TEXT_ALIGN_LEFT,
    )
    try:
        annot.set_border(width=0.5)
        annot.set_colors(stroke=qcolor_to_tuple(border))
    except Exception:
        pass
    annot.update()
    return annot


def apply_note(page: fitz.Page, point: fitz.Point, text: str) -> fitz.Annot:
    annot = page.add_text_annot(point, text)
    annot.update()
    return annot


def apply_redact_mark(page: fitz.Page, rect: fitz.Rect) -> fitz.Annot:
    annot = page.add_redact_annot(rect, fill=(0, 0, 0))
    annot.update()
    return annot


def insert_text_at(page: fitz.Page, point: fitz.Point, text: str,
                   font_size: float, font_name: str, color: QColor) -> None:
    from .text_edit import safe_insert_text
    safe_insert_text(page, point, text, fontsize=font_size,
                     font_alias=font_name, color=qcolor_to_tuple(color))


def insert_textbox(page: fitz.Page, rect: fitz.Rect, text: str,
                   font_size: float, font_name: str, color: QColor,
                   align: int = 0) -> None:
    from .text_edit import safe_insert_textbox
    safe_insert_textbox(page, rect, text, fontsize=font_size,
                        font_alias=font_name, color=qcolor_to_tuple(color),
                        align=align)


def insert_image(page: fitz.Page, rect: fitz.Rect, path: str) -> None:
    page.insert_image(rect, filename=path, keep_proportion=True)


def add_link(page: fitz.Page, rect: fitz.Rect, *, uri: Optional[str] = None,
             page_to: Optional[int] = None) -> None:
    if uri:
        page.insert_link({"kind": fitz.LINK_URI, "from": rect, "uri": uri})
    elif page_to is not None:
        page.insert_link({"kind": fitz.LINK_GOTO, "from": rect, "page": page_to,
                          "to": fitz.Point(0, 0)})
