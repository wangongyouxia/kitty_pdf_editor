"""Document-level operations: merge, split, watermark, page numbers,
encrypt/decrypt, compress, export, OCR-free text/image extraction.
"""

from __future__ import annotations

import os
from typing import Iterable, Optional

import fitz

from .text_edit import safe_insert_text, safe_insert_textbox


# ----------------------------------------------------------------------
# Page manipulation
# ----------------------------------------------------------------------
def insert_blank_page(doc: fitz.Document, at: int, width: float = 595.0,
                      height: float = 842.0) -> None:
    doc.new_page(pno=at, width=width, height=height)


def delete_pages(doc: fitz.Document, indices: list[int]) -> None:
    for i in sorted(set(indices), reverse=True):
        if 0 <= i < doc.page_count:
            doc.delete_page(i)


def duplicate_pages(doc: fitz.Document, indices: list[int]) -> None:
    # Inserting changes indexes; process from highest to lowest so earlier
    # indices remain valid.
    for i in sorted(set(indices), reverse=True):
        if 0 <= i < doc.page_count:
            doc.fullcopy_page(i, to=i)


def rotate_pages(doc: fitz.Document, indices: list[int], delta: int) -> None:
    for i in set(indices):
        if 0 <= i < doc.page_count:
            page = doc[i]
            new_rot = (page.rotation + delta) % 360
            page.set_rotation(new_rot)


def reorder_pages(doc: fitz.Document, new_order: list[int]) -> fitz.Document:
    """Return a new document with pages in `new_order` (list of indices)."""
    new = fitz.open()
    for src_idx in new_order:
        new.insert_pdf(doc, from_page=src_idx, to_page=src_idx)
    # Copy TOC if possible
    try:
        new.set_toc(doc.get_toc())
    except Exception:
        pass
    return new


def extract_pages_to(doc: fitz.Document, indices: list[int], out_path: str) -> None:
    new = fitz.open()
    for i in sorted(set(indices)):
        new.insert_pdf(doc, from_page=i, to_page=i)
    new.save(out_path, garbage=3, deflate=True)
    new.close()


def crop_page(doc: fitz.Document, index: int, rect: fitz.Rect) -> None:
    page = doc[index]
    # set_cropbox uses the original (non-rotated) coordinates.
    page.set_cropbox(rect)


# ----------------------------------------------------------------------
# Multi-document operations
# ----------------------------------------------------------------------
def merge_pdfs(paths: Iterable[str], out_path: str,
               passwords: Optional[dict[str, str]] = None) -> int:
    merged = fitz.open()
    count = 0
    for p in paths:
        d = fitz.open(p)
        if d.needs_pass:
            pwd = (passwords or {}).get(p, "")
            if not d.authenticate(pwd):
                d.close()
                raise PermissionError(f"Password required for {p}")
        merged.insert_pdf(d)
        count += d.page_count
        d.close()
    merged.save(out_path, garbage=3, deflate=True)
    merged.close()
    return count


def split_pdf(doc: fitz.Document, out_dir: str, basename: str,
              ranges: list[tuple[int, int]]) -> list[str]:
    """Each range is (start, end) inclusive 0-based. Returns paths written."""
    written = []
    for idx, (start, end) in enumerate(ranges, 1):
        new = fitz.open()
        new.insert_pdf(doc, from_page=start, to_page=end)
        path = os.path.join(out_dir, f"{basename}_part{idx}.pdf")
        new.save(path, garbage=3, deflate=True)
        new.close()
        written.append(path)
    return written


def split_every(doc: fitz.Document, n: int) -> list[tuple[int, int]]:
    ranges = []
    for start in range(0, doc.page_count, n):
        end = min(start + n - 1, doc.page_count - 1)
        ranges.append((start, end))
    return ranges


# ----------------------------------------------------------------------
# Watermark / header / footer / page numbers
# ----------------------------------------------------------------------
def add_text_watermark(doc: fitz.Document, text: str, *,
                       opacity: float = 0.25,
                       font_size: float = 60.0,
                       color: tuple[float, float, float] = (0.7, 0.7, 0.7),
                       rotate: float = 45.0,
                       only_pages: Optional[list[int]] = None) -> None:
    pages = only_pages if only_pages is not None else range(doc.page_count)
    for i in pages:
        page = doc[i]
        rect = page.rect
        # Build a temp rect roughly centered
        w, h = rect.width, rect.height
        # Insert text using a transformation matrix
        cx, cy = w / 2, h / 2
        # Render the watermark via insert_text with a fillopacity in a fresh
        # XObject-like overlay: we approximate by drawing rotated text.
        safe_insert_textbox(
            page,
            fitz.Rect(0, cy - font_size, w, cy + font_size),
            text,
            fontsize=font_size,
            font_alias="helv",
            color=color,
            align=fitz.TEXT_ALIGN_CENTER,
            rotate=int(rotate) if rotate in (0, 90, 180, 270) else 0,
            fill_opacity=opacity,
            stroke_opacity=opacity,
        )


def add_image_watermark(doc: fitz.Document, image_path: str, *,
                        opacity: float = 0.3,
                        width_pct: float = 0.6,
                        only_pages: Optional[list[int]] = None) -> None:
    pages = only_pages if only_pages is not None else range(doc.page_count)
    for i in pages:
        page = doc[i]
        rect = page.rect
        target_w = rect.width * width_pct
        target_h = target_w  # square-ish; insert_image keeps proportion
        cx, cy = rect.width / 2, rect.height / 2
        box = fitz.Rect(cx - target_w / 2, cy - target_h / 2,
                        cx + target_w / 2, cy + target_h / 2)
        page.insert_image(box, filename=image_path, keep_proportion=True,
                          overlay=True)


def add_page_numbers(doc: fitz.Document, *, position: str = "bottom-center",
                     fmt: str = "{page} / {total}",
                     font_size: float = 10.0,
                     color: tuple[float, float, float] = (0, 0, 0),
                     margin: float = 24.0,
                     start_at: int = 1) -> None:
    total = doc.page_count
    for i in range(doc.page_count):
        page = doc[i]
        text = fmt.format(page=i + start_at, total=total)
        w, h = page.rect.width, page.rect.height
        if "top" in position:
            y = margin
        else:
            y = h - margin
        if "left" in position:
            x = margin
            align = fitz.TEXT_ALIGN_LEFT
        elif "right" in position:
            x = w - margin
            align = fitz.TEXT_ALIGN_RIGHT
        else:
            x = w / 2
            align = fitz.TEXT_ALIGN_CENTER
        # Use a textbox so alignment works.
        box_h = font_size + 4
        if align == fitz.TEXT_ALIGN_LEFT:
            box = fitz.Rect(x, y - box_h / 2, x + 200, y + box_h / 2)
        elif align == fitz.TEXT_ALIGN_RIGHT:
            box = fitz.Rect(x - 200, y - box_h / 2, x, y + box_h / 2)
        else:
            box = fitz.Rect(x - 200, y - box_h / 2, x + 200, y + box_h / 2)
        safe_insert_textbox(page, box, text, fontsize=font_size,
                            font_alias="helv", color=color, align=align)


def add_header_footer(doc: fitz.Document, *, header: Optional[str] = None,
                      footer: Optional[str] = None,
                      font_size: float = 10.0,
                      color: tuple[float, float, float] = (0, 0, 0),
                      margin: float = 24.0) -> None:
    for i in range(doc.page_count):
        page = doc[i]
        w, h = page.rect.width, page.rect.height
        if header:
            box = fitz.Rect(margin, margin - font_size, w - margin, margin + 2)
            safe_insert_textbox(page, box, header, fontsize=font_size,
                                font_alias="helv", color=color,
                                align=fitz.TEXT_ALIGN_CENTER)
        if footer:
            box = fitz.Rect(margin, h - margin - 2, w - margin, h - margin + font_size)
            safe_insert_textbox(page, box, footer, fontsize=font_size,
                                font_alias="helv", color=color,
                                align=fitz.TEXT_ALIGN_CENTER)


# ----------------------------------------------------------------------
# Security
# ----------------------------------------------------------------------
def save_encrypted(doc: fitz.Document, out_path: str, *,
                   user_pw: str = "", owner_pw: str = "",
                   allow_print: bool = True,
                   allow_copy: bool = True,
                   allow_modify: bool = True,
                   allow_annotate: bool = True) -> None:
    perm = 0
    if allow_print:
        perm |= fitz.PDF_PERM_PRINT
    if allow_copy:
        perm |= fitz.PDF_PERM_COPY
    if allow_modify:
        perm |= fitz.PDF_PERM_MODIFY
    if allow_annotate:
        perm |= fitz.PDF_PERM_ANNOTATE
    doc.save(
        out_path,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw=user_pw,
        owner_pw=owner_pw or user_pw,
        permissions=perm,
        garbage=3,
        deflate=True,
    )


def save_decrypted(doc: fitz.Document, out_path: str) -> None:
    doc.save(out_path, encryption=fitz.PDF_ENCRYPT_NONE, garbage=3, deflate=True)


# ----------------------------------------------------------------------
# Compression / optimization
# ----------------------------------------------------------------------
def save_optimized(doc: fitz.Document, out_path: str) -> None:
    doc.save(out_path, garbage=4, deflate=True, deflate_images=True,
             deflate_fonts=True, clean=True)


# ----------------------------------------------------------------------
# Export
# ----------------------------------------------------------------------
def export_text(doc: fitz.Document, out_path: str) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        for i in range(doc.page_count):
            f.write(doc[i].get_text())
            f.write("\n\n")


def export_html(doc: fitz.Document, out_path: str) -> None:
    parts = ["<!DOCTYPE html><html><body>"]
    for i in range(doc.page_count):
        parts.append(f"<!-- page {i+1} -->")
        parts.append(doc[i].get_text("html"))
    parts.append("</body></html>")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def export_page_images(doc: fitz.Document, out_dir: str, *, fmt: str = "png",
                       dpi: int = 150) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    scale = dpi / 72
    mat = fitz.Matrix(scale, scale)
    for i in range(doc.page_count):
        pix = doc[i].get_pixmap(matrix=mat, alpha=False)
        path = os.path.join(out_dir, f"page_{i+1:04d}.{fmt}")
        pix.save(path)
        written.append(path)
    return written


def extract_all_images(doc: fitz.Document, out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    seen = set()
    for i in range(doc.page_count):
        for img in doc.get_page_images(i, full=True):
            xref = img[0]
            if xref in seen:
                continue
            seen.add(xref)
            base = doc.extract_image(xref)
            if not base:
                continue
            ext = base.get("ext", "png")
            path = os.path.join(out_dir, f"img_p{i+1:03d}_x{xref}.{ext}")
            with open(path, "wb") as f:
                f.write(base["image"])
            written.append(path)
    return written


# ----------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------
def search_document(doc: fitz.Document, query: str, *,
                    quads: bool = False) -> list[tuple[int, fitz.Rect, str]]:
    results = []
    for i in range(doc.page_count):
        page = doc[i]
        rects = page.search_for(query, quads=False)
        if not rects:
            continue
        text = page.get_text("text")
        lower = text.lower()
        q = query.lower()
        for r in rects:
            idx = lower.find(q)
            snippet = query
            if idx >= 0:
                start = max(0, idx - 24)
                end = min(len(text), idx + len(query) + 24)
                snippet = text[start:end].replace("\n", " ")
            results.append((i, r, snippet))
    return results


# ----------------------------------------------------------------------
# Form operations
# ----------------------------------------------------------------------
def list_form_fields(doc: fitz.Document) -> list[dict]:
    fields = []
    for i in range(doc.page_count):
        for w in doc[i].widgets() or []:
            fields.append({
                "page": i,
                "name": w.field_name or "",
                "type": w.field_type_string,
                "value": w.field_value,
                "rect": w.rect,
            })
    return fields


def flatten_form(doc: fitz.Document) -> None:
    """Bake form fields into the page content (no longer editable)."""
    for i in range(doc.page_count):
        page = doc[i]
        for w in page.widgets() or []:
            try:
                w.update()
            except Exception:
                pass
    # Use bake_widgets for newer PyMuPDF; fall back gracefully
    try:
        doc.bake()  # type: ignore[attr-defined]
    except Exception:
        pass


# ----------------------------------------------------------------------
# Redaction (after the user marks regions)
# ----------------------------------------------------------------------
def apply_redactions(doc: fitz.Document) -> int:
    count = 0
    for i in range(doc.page_count):
        n = doc[i].apply_redactions()
        try:
            count += int(n) if n is not None else 0
        except Exception:
            pass
    return count
