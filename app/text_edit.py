"""Editing existing text in a PDF page.

PDFs do not store text as editable paragraphs — they store positioned
glyph-drawing operations. The standard approach to "editing" text is:

  1. Locate the text span at a point (via the page's text dict).
  2. Cover the original glyphs with a filled rectangle in the page's
     background colour (typically white).
  3. Re-insert the new text at the same baseline using a font that
     approximates the original.

Limitations: the embedded original font is usually subsetted and not
re-usable by name, so we map to one of PyMuPDF's built-in base-14 fonts.
Latin text in standard fonts replaces well; complex scripts, unusual
fonts, and coloured / image backgrounds will not match perfectly.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional

import fitz


# ----------------------------------------------------------------------
# Unicode font handling — base-14 cannot render CJK / Cyrillic / Greek.
# When text contains any non-Latin-1 codepoint, we embed a system font
# that does.  The first existing candidate from this list is used and
# cached per process.
# ----------------------------------------------------------------------
# File name candidates, in priority order, grouped by weight/slant.
_UNICODE_FONT_CANDIDATES = {
    "regular": (
        # Windows
        "msyh.ttc", "msyhl.ttc",
        "simhei.ttf", "simsun.ttc", "simfang.ttf", "simkai.ttf",
        "mingliu.ttc", "arialuni.ttf",
        # macOS
        "PingFang.ttc", "STHeiti Light.ttc", "STHeiti Medium.ttc",
        "Hiragino Sans GB.ttc", "Songti.ttc",
        # Linux
        "NotoSansCJK-Regular.ttc",
        "NotoSansCJKsc-Regular.otf", "NotoSansCJK-Regular.otf",
        "NotoSansSC-Regular.otf", "NotoSans-Regular.ttf",
        "DroidSansFallbackFull.ttf", "DroidSansFallback.ttf",
        "wqy-microhei.ttc", "wqy-zenhei.ttc",
    ),
    "bold": (
        # Windows
        "msyhbd.ttc",                   # Microsoft YaHei Bold
        "simhei.ttf",                   # SimHei reads as bold-ish
        "simsunb.ttf",                  # SimSun Bold
        # macOS
        "PingFang.ttc",                 # PingFang has Bold inside .ttc
        "STHeiti Medium.ttc",
        # Linux
        "NotoSansCJK-Bold.ttc",
        "NotoSansCJKsc-Bold.otf", "NotoSansSC-Bold.otf",
        "NotoSans-Bold.ttf",
    ),
}

# Cache: key = (bold, italic) → resolved path or None.
_unicode_font_cache: dict[tuple[bool, bool], Optional[str]] = {}


def _candidate_font_dirs() -> list[str]:
    """Where on-disk font files might live, ordered by likelihood."""
    dirs: list[str] = []
    if sys.platform.startswith("win"):
        win = os.environ.get("WINDIR")
        if win:
            dirs.append(os.path.join(win, "Fonts"))
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    elif sys.platform == "darwin":
        dirs.extend([
            "/System/Library/Fonts",
            "/System/Library/Fonts/Supplemental",
            "/Library/Fonts",
            os.path.expanduser("~/Library/Fonts"),
        ])
    else:  # linux / *bsd
        dirs.extend([
            "/usr/share/fonts",
            "/usr/share/fonts/opentype",
            "/usr/share/fonts/truetype",
            "/usr/local/share/fonts",
            os.path.expanduser("~/.fonts"),
            os.path.expanduser("~/.local/share/fonts"),
        ])
    return [d for d in dirs if os.path.isdir(d)]


def find_unicode_font(bold: bool = False, italic: bool = False) -> Optional[str]:
    """Path to an installed Unicode-capable font matching the weight hint.

    CJK fonts rarely ship dedicated italic faces — `italic=True` simply
    falls back to the regular face.  Bold has Windows / mac / Linux
    candidates and we prefer those when requested.
    """
    key = (bool(bold), bool(italic))
    if key in _unicode_font_cache:
        return _unicode_font_cache[key]

    candidate_dirs = _candidate_font_dirs()
    # Pick name list by weight.  We always fall through to "regular".
    name_lists = []
    if bold:
        name_lists.append(_UNICODE_FONT_CANDIDATES["bold"])
    name_lists.append(_UNICODE_FONT_CANDIDATES["regular"])

    for names in name_lists:
        # Direct match first (fast path).
        for fd in candidate_dirs:
            for name in names:
                p = os.path.join(fd, name)
                if os.path.isfile(p):
                    _unicode_font_cache[key] = p
                    return p
        # Recursive search (mac/linux often nest fonts).
        if not sys.platform.startswith("win"):
            cand_set = {n.lower() for n in names}
            for fd in candidate_dirs:
                for root, _dirs, files in os.walk(fd):
                    for f in files:
                        if f.lower() in cand_set:
                            p = os.path.join(root, f)
                            _unicode_font_cache[key] = p
                            return p
    _unicode_font_cache[key] = None
    return None


def needs_unicode_font(text: str) -> bool:
    """True when `text` has characters base-14 (WinAnsi) cannot encode."""
    return any(ord(c) > 0xFF for c in text)


def _alias_weights(alias: str) -> tuple[bool, bool]:
    """Decode bold/italic from a PyMuPDF base-14 alias like 'hebi'."""
    suffix = (alias or "")[-2:]
    bold = suffix in ("bo", "bi")
    italic = suffix in ("it", "bi")
    return bold, italic


def _unique_font_alias(path: str) -> str:
    """A page-unique fontname for an embedded TTF.

    Including the file basename means bold/regular use different aliases
    and PyMuPDF won't accidentally reuse the wrong embedded font.
    """
    return "u-" + os.path.basename(path).replace(".", "_").lower()


def safe_insert_text(page: fitz.Page, point: fitz.Point, text: str, *,
                     fontsize: float, font_alias: str,
                     color: tuple[float, float, float],
                     font_file: Optional[str] = None,
                     font_files: Optional[list[str]] = None) -> None:
    """Insert `text` trying each font in `font_files` (in order) and
    falling back through:

      1. Every entry in `font_files` (plus the legacy `font_file` arg).
         These are the "this-is-what-the-user-wanted" candidates,
         starting with the original PDF's embedded font and ending
         with a bundled best-match.
      2. The system CJK font when `text` has non-Latin-1 chars.
      3. The base-14 alias.

    The new `font_files` plural is what callers should use; the
    singular `font_file` stays for backward compatibility.
    """
    bold, italic = _alias_weights(font_alias)

    candidates: list[str] = []
    if font_files:
        candidates.extend([p for p in font_files if p])
    if font_file:
        candidates.append(font_file)

    for fp in candidates:
        if not fp or not os.path.isfile(fp):
            continue
        try:
            page.insert_text(point, text, fontsize=fontsize,
                             fontname=_unique_font_alias(fp),
                             fontfile=fp, color=color)
            return
        except Exception:
            continue

    if needs_unicode_font(text):
        path = find_unicode_font(bold=bold, italic=italic)
        if path:
            try:
                page.insert_text(point, text, fontsize=fontsize,
                                 fontname=_unique_font_alias(path),
                                 fontfile=path,
                                 color=color)
                return
            except Exception:
                pass
    try:
        page.insert_text(point, text, fontsize=fontsize,
                         fontname=font_alias, color=color)
    except Exception:
        page.insert_text(point, text, fontsize=fontsize,
                         fontname="helv", color=color)


def safe_insert_textbox(page: fitz.Page, rect: fitz.Rect, text: str, *,
                        fontsize: float, font_alias: str,
                        color: tuple[float, float, float],
                        align: int = 0,
                        rotate: int = 0,
                        fill_opacity: float = 1.0,
                        stroke_opacity: float = 1.0,
                        font_file: Optional[str] = None,
                        font_files: Optional[list[str]] = None) -> None:
    bold, italic = _alias_weights(font_alias)
    candidates: list[str] = []
    if font_files:
        candidates.extend([p for p in font_files if p])
    if font_file:
        candidates.append(font_file)
    for fp in candidates:
        if not fp or not os.path.isfile(fp):
            continue
        try:
            page.insert_textbox(
                rect, text, fontsize=fontsize,
                fontname=_unique_font_alias(fp), fontfile=fp,
                color=color, align=align, rotate=rotate,
                fill_opacity=fill_opacity, stroke_opacity=stroke_opacity,
            )
            return
        except Exception:
            continue
    if needs_unicode_font(text):
        path = find_unicode_font(bold=bold, italic=italic)
        if path:
            try:
                page.insert_textbox(
                    rect, text, fontsize=fontsize,
                    fontname=_unique_font_alias(path), fontfile=path,
                    color=color, align=align, rotate=rotate,
                    fill_opacity=fill_opacity, stroke_opacity=stroke_opacity,
                )
                return
            except Exception:
                pass
    try:
        page.insert_textbox(
            rect, text, fontsize=fontsize, fontname=font_alias,
            color=color, align=align, rotate=rotate,
            fill_opacity=fill_opacity, stroke_opacity=stroke_opacity,
        )
    except Exception:
        page.insert_textbox(
            rect, text, fontsize=fontsize, fontname="helv",
            color=color, align=align, rotate=rotate,
            fill_opacity=fill_opacity, stroke_opacity=stroke_opacity,
        )


# PyMuPDF span flag bits
F_SUPERSCRIPT = 1
F_ITALIC = 2
F_SERIF = 4
F_MONO = 8
F_BOLD = 16


@dataclass
class TextSpan:
    page_index: int
    rect: fitz.Rect          # bounding box of the span
    text: str                # original glyph string
    font: str                # original font name (often subsetted)
    size: float              # font size in pt
    color_rgb: tuple[float, float, float]  # 0..1
    origin: fitz.Point       # baseline origin
    flags: int               # font characteristics bit-field
    ascender: float
    descender: float

    @property
    def is_bold(self) -> bool:
        return bool(self.flags & F_BOLD) or "bold" in self.font.lower()

    @property
    def is_italic(self) -> bool:
        return bool(self.flags & F_ITALIC) or any(
            s in self.font.lower() for s in ("italic", "oblique"))

    @property
    def is_mono(self) -> bool:
        return bool(self.flags & F_MONO) or any(
            s in self.font.lower() for s in ("mono", "courier", "consol", "code"))

    @property
    def is_serif(self) -> bool:
        if self.is_mono:
            return False
        if self.flags & F_SERIF:
            return True
        lower = self.font.lower()
        return any(s in lower for s in (
            "serif", "times", "roman", "georgia", "garamond",
            "minion", "cambria", "palatino", "merriweather",
        ))


def _int_color_to_rgb(value) -> tuple[float, float, float]:
    """PyMuPDF stores span colour as a packed sRGB integer."""
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return tuple(float(v) for v in value)  # type: ignore[return-value]
    try:
        v = int(value)
    except Exception:
        return (0.0, 0.0, 0.0)
    return (((v >> 16) & 0xFF) / 255.0,
            ((v >> 8) & 0xFF) / 255.0,
            (v & 0xFF) / 255.0)


def _is_covered(rect: fitz.Rect, covered_rects) -> bool:
    """Returns True if `rect` is "logically deleted" — i.e. its centre
    lies inside one of the covered rectangles the editor has stamped
    on this page during the session.  Using the rect centre (rather
    than full containment or intersection) gives forgiving behaviour
    when bboxes drift slightly between operations.
    """
    if not covered_rects:
        return False
    cx = (rect.x0 + rect.x1) / 2.0
    cy = (rect.y0 + rect.y1) / 2.0
    for cr in covered_rects:
        if cr.x0 <= cx <= cr.x1 and cr.y0 <= cy <= cr.y1:
            return True
    return False


def find_text_span_at(page: fitz.Page, point: fitz.Point,
                      covered_rects=None) -> Optional[TextSpan]:
    """Return the text span that contains `point`, or None."""
    data = page.get_text("dict")
    best: Optional[TextSpan] = None
    best_area = float("inf")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text") or ""
                if not text.strip():
                    continue
                bbox = span.get("bbox")
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                if not rect.contains(point):
                    continue
                if _is_covered(rect, covered_rects):
                    continue
                area = max(1.0, rect.get_area())
                if area >= best_area:
                    continue
                origin = span.get("origin") or (rect.x0, rect.y1)
                best = TextSpan(
                    page_index=page.number,
                    rect=rect,
                    text=text,
                    font=span.get("font") or "",
                    size=float(span.get("size") or 11.0),
                    color_rgb=_int_color_to_rgb(span.get("color", 0)),
                    origin=fitz.Point(origin),
                    flags=int(span.get("flags") or 0),
                    ascender=float(span.get("ascender") or 0.8),
                    descender=float(span.get("descender") or -0.2),
                )
                best_area = area
    return best


def find_text_spans_in_rect(page: fitz.Page, rect: fitz.Rect) -> list[TextSpan]:
    """All spans whose bbox intersects `rect`, sorted reading order."""
    out: list[TextSpan] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text") or ""
                if not text:
                    continue
                bbox = span.get("bbox")
                if not bbox:
                    continue
                sr = fitz.Rect(bbox)
                if not sr.intersects(rect):
                    continue
                origin = span.get("origin") or (sr.x0, sr.y1)
                out.append(TextSpan(
                    page_index=page.number,
                    rect=sr,
                    text=text,
                    font=span.get("font") or "",
                    size=float(span.get("size") or 11.0),
                    color_rgb=_int_color_to_rgb(span.get("color", 0)),
                    origin=fitz.Point(origin),
                    flags=int(span.get("flags") or 0),
                    ascender=float(span.get("ascender") or 0.8),
                    descender=float(span.get("descender") or -0.2),
                ))
    out.sort(key=lambda s: (round(s.rect.y0, 1), s.rect.x0))
    return out


def map_to_base14(span: TextSpan) -> str:
    """Pick a PyMuPDF built-in font alias closest to `span`'s original."""
    bold = span.is_bold
    italic = span.is_italic
    if span.is_mono:
        return "cobi" if bold and italic else ("cobo" if bold else ("coit" if italic else "cour"))
    if span.is_serif:
        return "tibi" if bold and italic else ("tibo" if bold else ("tiit" if italic else "tiro"))
    return "hebi" if bold and italic else ("hebo" if bold else ("heit" if italic else "helv"))


def cover_rect(page: fitz.Page, rect: fitz.Rect,
                color: tuple[float, float, float] = (1.0, 1.0, 1.0),
                pad: float = 0.0) -> None:
    """Truly remove the text inside `rect` from the page content stream.

    Uses `apply_redactions` with the most conservative settings:

      * **pad=0** — exact span bbox, no encroachment into neighbours.
      * **text=0 (default)** — center-based char removal: a glyph is
        only deleted if its CENTRE lies inside the redaction rect,
        so an adjacent span whose centre is even a fraction of a
        point outside the rect survives untouched.
      * **graphics=0** — vector drawings (underlines, table rules,
        signatures…) are left alone.
      * **images=0** — raster images are left alone.

    Any pre-existing redaction annotations the user had marked are
    stashed first and re-added afterwards, so this only commits OUR
    redaction.  On any error we fall back to `draw_rect` overpaint
    (and PdfDocument's covered_rects tracking acts as a safety net
    for the overlay).
    """
    r = fitz.Rect(rect)
    if pad:
        r = fitz.Rect(r.x0 - pad, r.y0 - pad, r.x1 + pad, r.y1 + pad)

    # Stash any pre-existing redact annotations the user had marked
    # (via the redact tool) so apply_redactions only touches ours.
    stash: list[dict] = []
    try:
        annots = list(page.annots() or [])
    except Exception:
        annots = []
    for annot in annots:
        try:
            t = annot.type
        except Exception:
            continue
        if t and t[0] == fitz.PDF_ANNOT_REDACT:
            try:
                fill = dict(annot.colors or {}).get("fill")
            except Exception:
                fill = None
            stash.append({"rect": fitz.Rect(annot.rect), "fill": fill})
            try:
                page.delete_annot(annot)
            except Exception:
                pass

    redacted = False
    try:
        # fill=None → don't paint a coloured box over the area; we
        # only want the text removed, so any drawings underneath
        # (page background colour, table lines, etc.) stay visible.
        page.add_redact_annot(r, fill=None)
        try:
            page.apply_redactions(images=0, graphics=0)
        except TypeError:
            # Older PyMuPDF without the per-kind flags.
            page.apply_redactions()
        redacted = True
    except Exception:
        pass

    if not redacted:
        # Last-resort visual overpaint.  The original glyphs survive
        # in the stream but are hidden; PdfDocument's covered_rects
        # tracking still filters them from the editable overlay.
        try:
            page.draw_rect(r, color=None, fill=color, overlay=True)
        except Exception:
            pass

    # Re-add the stashed redactions so the user's pending marks survive.
    for s in stash:
        try:
            page.add_redact_annot(s["rect"], fill=s["fill"] or (0, 0, 0))
        except Exception:
            pass


def replace_span(page: fitz.Page, span: TextSpan, new_text: str, *,
                 font_alias: Optional[str] = None,
                 font_file: Optional[str] = None,
                 font_files: Optional[list[str]] = None,
                 font_size: Optional[float] = None,
                 text_color: Optional[tuple[float, float, float]] = None,
                 background: tuple[float, float, float] = (1.0, 1.0, 1.0),
                 cover_pad: float = 0.5) -> None:
    """Cover the original span and write `new_text` at the same baseline."""
    cover_rect(page, span.rect, color=background, pad=cover_pad)
    if not new_text:
        return
    alias = font_alias or map_to_base14(span)
    size = font_size if font_size is not None else span.size
    color = text_color if text_color is not None else span.color_rgb
    safe_insert_text(page, span.origin, new_text,
                     fontsize=size, font_alias=alias, color=color,
                     font_file=font_file, font_files=font_files)


def list_all_spans(page: fitz.Page, covered_rects=None) -> list[TextSpan]:
    """Every non-empty text span on the page in reading order.

    `covered_rects` (optional) is the list of rectangles the editor
    has "logically deleted" — spans whose centre falls inside one of
    these are filtered out so they don't appear as ghost overlays
    after a move / inline-edit.
    """
    out: list[TextSpan] = []
    data = page.get_text("dict")
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text") or ""
                if not text.strip():
                    continue
                bbox = span.get("bbox")
                if not bbox:
                    continue
                sr = fitz.Rect(bbox)
                if sr.is_empty or sr.is_infinite:
                    continue
                if _is_covered(sr, covered_rects):
                    continue
                origin = span.get("origin") or (sr.x0, sr.y1)
                out.append(TextSpan(
                    page_index=page.number,
                    rect=sr,
                    text=text,
                    font=span.get("font") or "",
                    size=float(span.get("size") or 11.0),
                    color_rgb=_int_color_to_rgb(span.get("color", 0)),
                    origin=fitz.Point(origin),
                    flags=int(span.get("flags") or 0),
                    ascender=float(span.get("ascender") or 0.8),
                    descender=float(span.get("descender") or -0.2),
                ))
    out.sort(key=lambda s: (round(s.rect.y0, 1), s.rect.x0))
    return out


@dataclass
class ImageInstance:
    """One occurrence of an embedded image drawn on a page."""
    page_index: int
    xref: int
    rect: fitz.Rect


def find_images_on_page(page: fitz.Page) -> list[ImageInstance]:
    """All visible occurrences of every embedded image on `page`.

    Uses `get_image_rects` (PyMuPDF ≥ 1.18) so an image that is drawn
    in several places yields several `ImageInstance` entries.
    """
    out: list[ImageInstance] = []
    try:
        infos = page.get_images(full=True)
    except Exception:
        infos = []
    seen: set[tuple[int, float, float, float, float]] = set()
    for info in infos:
        xref = int(info[0])
        rects: list[fitz.Rect] = []
        try:
            for r in page.get_image_rects(xref):
                rects.append(fitz.Rect(r))
        except Exception:
            rects = []
        if not rects:
            try:
                bbox = page.get_image_bbox(info)
                if bbox and not bbox.is_empty and not bbox.is_infinite:
                    rects = [fitz.Rect(bbox)]
            except Exception:
                rects = []
        for r in rects:
            if r.is_empty or r.is_infinite:
                continue
            key = (xref, round(r.x0, 2), round(r.y0, 2), round(r.x1, 2), round(r.y1, 2))
            if key in seen:
                continue
            seen.add(key)
            out.append(ImageInstance(
                page_index=page.number,
                xref=xref,
                rect=r,
            ))
    return out


def move_image(page: fitz.Page, instance: ImageInstance, new_rect: fitz.Rect,
               background: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
    """Cover an image's existing draw and re-draw it at `new_rect`."""
    cover_rect(page, instance.rect, color=background, pad=0.5)
    page.insert_image(new_rect, xref=instance.xref, keep_proportion=False, overlay=True)


def delete_image(page: fitz.Page, instance: ImageInstance,
                 background: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
    cover_rect(page, instance.rect, color=background, pad=0.5)


def delete_text_span(page: fitz.Page, span: TextSpan,
                     background: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
    cover_rect(page, span.rect, color=background, pad=0.5)


def move_text_span(page: fitz.Page, span: TextSpan, new_rect: fitz.Rect, *,
                   font_alias: Optional[str] = None,
                   font_file: Optional[str] = None,
                   font_files: Optional[list[str]] = None,
                   font_size: Optional[float] = None,
                   text_color: Optional[tuple[float, float, float]] = None,
                   background: tuple[float, float, float] = (1.0, 1.0, 1.0)) -> None:
    """Move (and optionally resize) a text span to `new_rect`.

    Font size scales with the rect's height ratio when `font_size` is
    not given.  Origin (baseline) is re-computed by preserving the
    relative offset within the original rect.
    """
    cover_rect(page, span.rect, color=background)
    orig_w = max(span.rect.width, 0.01)
    orig_h = max(span.rect.height, 0.01)
    new_w = max(new_rect.width, 0.01)
    new_h = max(new_rect.height, 0.01)
    # Use the smaller of width / height scale so the rendered text fits.
    scale_w = new_w / orig_w
    scale_h = new_h / orig_h
    scale = min(scale_w, scale_h)
    size = font_size if font_size is not None else span.size * scale
    # Map original origin offset proportionally
    rel_x = span.origin.x - span.rect.x0
    rel_y = span.origin.y - span.rect.y0
    new_origin = fitz.Point(new_rect.x0 + rel_x * scale_w,
                            new_rect.y0 + rel_y * scale_h)
    alias = font_alias or map_to_base14(span)
    color = text_color if text_color is not None else span.color_rgb
    safe_insert_text(page, new_origin, span.text,
                     fontsize=size, font_alias=alias, color=color,
                     font_file=font_file, font_files=font_files)


# ----------------------------------------------------------------------
# Reuse the original font from the PDF's own resources.
#
# When we move or re-edit a span we'd ideally insert the new text with
# the *exact* same font face — not a YaHei stand-in.  PyMuPDF lets us
# pull the embedded font bytes via Document.extract_font(xref); we
# write them to a temp file and pass the path through safe_insert_text.
# Most CJK PDFs embed the font as a TTF/OTF/TTC subset.  Subset fonts
# may not have glyphs for characters the user newly types, so we also
# expose `font_supports_text()` to verify before committing.
# ----------------------------------------------------------------------
import hashlib as _hashlib
import tempfile as _tempfile

# Cache: (id(doc), font psname) → path or None.  Same font extracted
# repeatedly returns the same temp file.
_embedded_font_cache: dict[tuple, Optional[str]] = {}


def extract_embedded_font(page: fitz.Page, font_psname: str) -> Optional[str]:
    """Return a temp-file path to the PDF's own embedded copy of
    `font_psname`, or None when it can't be extracted.
    """
    if not font_psname:
        return None
    doc = page.parent  # the fitz.Document this page belongs to
    cache_key = (id(doc), font_psname)
    if cache_key in _embedded_font_cache:
        cached = _embedded_font_cache[cache_key]
        if cached is None or os.path.isfile(cached):
            return cached
        # Stale (temp got cleaned); fall through and re-extract.

    target = font_psname.strip()
    target_low = target.lower()
    # Strip the standard '+'-prefix subset marker for comparison.
    if "+" in target:
        bn_low = target.split("+", 1)[1].lower()
    else:
        bn_low = target_low

    try:
        fonts = page.get_fonts()
    except Exception:
        _embedded_font_cache[cache_key] = None
        return None

    for fo in fonts:
        try:
            xref = fo[0]
            basename = (fo[3] if len(fo) > 3 else "") or ""
            name = (fo[4] if len(fo) > 4 else "") or ""
        except Exception:
            continue
        if name.lower() != target_low and basename.lower() != bn_low:
            continue
        try:
            info = doc.extract_font(xref)
        except Exception:
            continue
        if not info:
            continue
        # extract_font returns either a dict OR (legacy) a tuple
        # (basename, ext, type, content).
        if isinstance(info, dict):
            ext = (info.get("ext") or "ttf").lower()
            content = info.get("content") or b""
        else:
            try:
                ext = (info[1] or "ttf").lower()
                content = info[3] or b""
            except Exception:
                continue
        if not content or ext not in ("ttf", "otf", "ttc", "cff"):
            continue
        digest = _hashlib.md5(content[:4096]).hexdigest()[:12]
        path = os.path.join(
            _tempfile.gettempdir(), f"kpdf_emb_{digest}.{ext}",
        )
        if not os.path.isfile(path):
            try:
                with open(path, "wb") as f:
                    f.write(content)
            except OSError:
                continue
        _embedded_font_cache[cache_key] = path
        return path

    _embedded_font_cache[cache_key] = None
    return None


def font_supports_text(font_path: str, text: str) -> bool:
    """Whether the TTF/OTF at `font_path` has a glyph for every char
    in `text`.  Subset fonts often lack glyphs for *new* characters
    the user types during inline edit — in that case we must fall back
    to a bundled full-coverage font.
    """
    if not font_path or not os.path.isfile(font_path):
        return False
    try:
        font = fitz.Font(fontfile=font_path)
    except Exception:
        return False
    for c in text or "":
        cp = ord(c)
        if cp < 0x20 or cp == 0x7F:
            continue  # ASCII control / DEL
        try:
            if not font.has_glyph(cp):
                return False
        except Exception:
            return False
    return True


def sample_background_color(page: fitz.Page, near: fitz.Rect,
                             margin: float = 4.0) -> tuple[float, float, float]:
    """Sample a pixel just outside `near` to guess the page background colour.

    Falls back to white when the page render fails or the sampled pixel is
    transparent.
    """
    page_rect = page.rect
    # Try a point just below the rect first, then to the right, then above.
    candidates = [
        fitz.Point(near.x0 + 1, near.y1 + margin),
        fitz.Point(near.x1 + margin, near.y0 + (near.height / 2)),
        fitz.Point(near.x0 + 1, near.y0 - margin),
    ]
    for pt in candidates:
        if not page_rect.contains(pt):
            continue
        try:
            clip = fitz.Rect(pt.x - 1, pt.y - 1, pt.x + 1, pt.y + 1)
            pix = page.get_pixmap(clip=clip, alpha=False, annots=False)
            if pix.width and pix.height:
                idx = 0
                r = pix.samples[idx]
                g = pix.samples[idx + 1]
                b = pix.samples[idx + 2]
                return (r / 255.0, g / 255.0, b / 255.0)
        except Exception:
            continue
    return (1.0, 1.0, 1.0)
