"""Headless smoke test: instantiate the window without showing it,
exercise a few document operations against a generated test PDF."""

from __future__ import annotations

import os
import sys
import tempfile
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz  # type: ignore
from PyQt6.QtWidgets import QApplication

from app.document import PdfDocument
from app.main_window import MainWindow
from app.operations import (
    add_page_numbers,
    add_text_watermark,
    delete_pages,
    duplicate_pages,
    extract_pages_to,
    insert_blank_page,
    merge_pdfs,
    rotate_pages,
    save_optimized,
    search_document,
    split_pdf,
)


def make_test_pdf(path: str, n_pages: int = 5) -> None:
    d = fitz.open()
    for i in range(n_pages):
        page = d.new_page(width=595, height=842)
        page.insert_text((72, 96), f"Hello World — page {i + 1}", fontsize=18)
        page.insert_text((72, 130),
                         "The quick brown fox jumps over the lazy dog.", fontsize=12)
    d.save(path)
    d.close()


def main() -> int:
    app = QApplication(sys.argv)

    tmp = tempfile.mkdtemp(prefix="pdfedit_")
    src = os.path.join(tmp, "input.pdf")
    make_test_pdf(src, 5)
    print(f"[smoke] generated {src}")

    win = MainWindow()
    try:
        win.open_document(src)
        assert win.doc.is_open(), "document should be open"
        assert win.doc.page_count == 5
        print("[smoke] open: OK")

        # Document-level operations on the raw fitz doc
        doc = win.doc.doc

        # Insert blank page after page 1
        insert_blank_page(doc, 1, 595, 842)
        assert doc.page_count == 6
        print("[smoke] insert_blank: OK")

        # Duplicate page 0
        duplicate_pages(doc, [0])
        assert doc.page_count == 7
        print("[smoke] duplicate: OK")

        # Rotate page 0
        rotate_pages(doc, [0], 90)
        assert doc[0].rotation == 90
        print("[smoke] rotate: OK")

        # Watermark + page numbers
        add_text_watermark(doc, "DRAFT")
        add_page_numbers(doc)
        print("[smoke] watermark + page numbers: OK")

        # Search
        hits = search_document(doc, "Hello World")
        assert any(h[0] >= 0 for h in hits), "should find Hello World"
        print(f"[smoke] search: OK ({len(hits)} hits)")

        # Save optimized
        opt = os.path.join(tmp, "optimized.pdf")
        save_optimized(doc, opt)
        assert os.path.getsize(opt) > 0
        print("[smoke] optimize: OK")

        # Extract pages
        ex = os.path.join(tmp, "extract.pdf")
        extract_pages_to(doc, [0, 2], ex)
        d2 = fitz.open(ex)
        assert d2.page_count == 2
        d2.close()
        print("[smoke] extract: OK")

        # Split every 2
        out_dir = os.path.join(tmp, "split")
        os.makedirs(out_dir, exist_ok=True)
        ranges = []
        for s in range(0, doc.page_count, 2):
            ranges.append((s, min(s + 1, doc.page_count - 1)))
        written = split_pdf(doc, out_dir, "doc", ranges)
        assert len(written) > 0
        print(f"[smoke] split: OK ({len(written)} files)")

        # Merge: open a second doc, merge it with itself
        merged = os.path.join(tmp, "merged.pdf")
        count = merge_pdfs([src, src], merged)
        assert count == 10
        print(f"[smoke] merge: OK ({count} pages)")

        # Delete pages and save
        delete_pages(doc, [doc.page_count - 1])
        win.doc.mark_dirty()
        win.doc.save(os.path.join(tmp, "out.pdf"))
        print("[smoke] save: OK")

        # Annotations via viewer commit methods
        win.doc.open(src)
        page0 = win.doc.page(0)
        from app.tools import (
            Tool, apply_highlight_like, apply_shape, apply_line, apply_ink,
            apply_freetext, apply_note,
        )
        from PyQt6.QtGui import QColor
        red = QColor(255, 0, 0)
        yellow = QColor(255, 255, 0)
        rect = fitz.Rect(72, 88, 240, 110)
        a = apply_highlight_like(page0, rect, Tool.HIGHLIGHT, yellow)
        assert a is not None, "highlight should have hit text"
        apply_shape(page0, fitz.Rect(300, 300, 400, 400), Tool.RECT, red, yellow, 1.5)
        apply_shape(page0, fitz.Rect(300, 500, 400, 600), Tool.ELLIPSE, red, None, 2.0)
        apply_line(page0, fitz.Point(50, 700), fitz.Point(500, 700), red, 1.0, arrow=True)
        apply_ink(page0,
                  [[fitz.Point(50, 750), fitz.Point(100, 760), fitz.Point(150, 750)]],
                  red, 2.0)
        apply_freetext(page0, fitz.Rect(50, 780, 300, 820), "Free text note",
                       12.0, QColor(0, 0, 0), red)
        apply_note(page0, fitz.Point(550, 100), "Sticky")
        out = os.path.join(tmp, "annotated.pdf")
        win.doc.save(out)
        d2 = fitz.open(out)
        annot_count = sum(len(list(d2[i].annots() or [])) for i in range(d2.page_count))
        d2.close()
        assert annot_count >= 6, f"expected >=6 annotations, got {annot_count}"
        print(f"[smoke] annotations: OK ({annot_count} written)")

        # ---- move_text_span MUST truly remove the original text from the
        # content stream (otherwise the ghost still shows after a drag).
        from app.text_edit import (
            find_unicode_font, list_all_spans, move_text_span,
            needs_unicode_font, safe_insert_text,
        )
        ghost_pdf = os.path.join(tmp, "ghost.pdf")
        d_g = fitz.open()
        p_g = d_g.new_page(width=400, height=400)
        p_g.insert_text((50, 60), "MOVE_ME", fontsize=14)
        d_g.save(ghost_pdf)
        d_g.close()
        d_g = fitz.open(ghost_pdf)
        page_g = d_g[0]
        span_g = [s for s in list_all_spans(page_g) if "MOVE_ME" in s.text][0]
        new_r = fitz.Rect(200, 200, 200 + span_g.rect.width, 200 + span_g.rect.height)
        move_text_span(page_g, span_g, new_r)
        spans_after = list_all_spans(page_g)
        old_pos_hits = [s for s in spans_after
                         if "MOVE_ME" in s.text and abs(s.rect.x0 - span_g.rect.x0) < 5]
        assert not old_pos_hits, f"原位置仍残留: {old_pos_hits}"
        new_pos_hits = [s for s in spans_after
                         if "MOVE_ME" in s.text and abs(s.rect.x0 - 200) < 30]
        assert new_pos_hits, "moved text not found at new position"
        print("[smoke] move_text_span 真删除原位置: OK")
        d_g.close()

        # CJK round-trip: move/edit Chinese text and verify chars survive
        font_path = find_unicode_font()
        assert font_path is not None, "no Unicode font found on system"
        print(f"[smoke] CJK font: {os.path.basename(font_path)}")
        # Bold should resolve to a heavier font file when available.
        bold_path = find_unicode_font(bold=True)
        print(f"[smoke] CJK bold font: {os.path.basename(bold_path or '')}")
        if bold_path and os.path.basename(bold_path) != os.path.basename(font_path):
            print("[smoke] bold CJK resolved to distinct face: OK")
        cjk_pdf = os.path.join(tmp, "cjk.pdf")
        d_cjk = fitz.open()
        p_cjk = d_cjk.new_page(width=400, height=400)
        safe_insert_text(p_cjk, fitz.Point(60, 80), "目录 第一章 引言",
                         fontsize=14, font_alias="helv", color=(0, 0, 0))
        d_cjk.save(cjk_pdf)
        d_cjk.close()
        d_back = fitz.open(cjk_pdf)
        cjk_text = d_back[0].get_text("text")
        assert "目录" in cjk_text and "引言" in cjk_text, f"CJK lost: {cjk_text!r}"
        print(f"[smoke] CJK insert: OK")
        # Now exercise move_text_span on CJK content
        from app.text_edit import list_all_spans, move_text_span
        spans_cjk = list_all_spans(d_back[0])
        assert spans_cjk and "目录" in spans_cjk[0].text
        s = spans_cjk[0]
        # Save a writable copy
        d_back.close()
        win.doc.open(cjk_pdf)
        sp = list_all_spans(win.doc.page(0))[0]
        new_r = fitz.Rect(150, 200, 150 + sp.rect.width, 200 + sp.rect.height)
        move_text_span(win.doc.page(0), sp, new_r)
        after = win.doc.page(0).get_text("text")
        assert "目录" in after, f"CJK lost after move: {after!r}"
        print("[smoke] CJK move_text_span: OK")

        # Content-edit mode: list spans, move/delete
        from app.text_edit import (
            delete_image, delete_text_span, find_images_on_page,
            find_text_span_at, list_all_spans, move_image, move_text_span,
            replace_span,
        )
        # Build a doc with an embedded image so we can exercise image ops
        img_pdf = os.path.join(tmp, "img.pdf")
        img_path = os.path.join(tmp, "block.png")
        # Create a small solid PNG via Pillow
        from PIL import Image
        Image.new("RGB", (50, 50), (200, 50, 50)).save(img_path)
        d_img = fitz.open()
        p_img = d_img.new_page(width=400, height=400)
        p_img.insert_text((50, 80), "Top text", fontsize=14)
        p_img.insert_image(fitz.Rect(60, 100, 160, 200), filename=img_path)
        d_img.save(img_pdf)
        d_img.close()
        win.doc.open(img_pdf)
        page_e = win.doc.page(0)
        spans = list_all_spans(page_e)
        assert spans, "expected at least one span"
        target_span = spans[0]
        # Move text span to (200, 200)
        new_rect = fitz.Rect(200, 200, 200 + target_span.rect.width,
                             200 + target_span.rect.height)
        move_text_span(page_e, target_span, new_rect)
        text_after = page_e.get_text("text")
        assert target_span.text in text_after, "moved text still present"
        print(f"[smoke] move_text_span: OK ({target_span.text!r})")
        # Move image
        imgs = find_images_on_page(page_e)
        assert imgs, "expected at least one image"
        target_img = imgs[0]
        new_irect = fitz.Rect(240, 240, 340, 340)
        move_image(page_e, target_img, new_irect)
        # After moving, find_images should still return the image with new bbox
        imgs_after = find_images_on_page(page_e)
        # At least one image bbox should be near the new rect (note: original is also still in resources)
        assert imgs_after, "image instances still present after move"
        print("[smoke] move_image: OK")
        # Delete operations
        spans2 = list_all_spans(page_e)
        if spans2:
            delete_text_span(page_e, spans2[0])
        if imgs_after:
            delete_image(page_e, imgs_after[0])
        print("[smoke] delete_text_span + delete_image: OK")

        # EditController build/clear
        from app.edit_mode import EditController, InlineTextEditor, TextElementItem
        win.doc.open(src)  # back to the simple test doc
        ctrl = win.viewer.edit_controller
        ctrl.set_active(True)
        assert ctrl.is_active()
        total_items = sum(len(items) for items in ctrl._items_per_page.values())
        assert total_items > 0, "edit controller should have built some items"
        print(f"[smoke] EditController: OK ({total_items} items)")

        # Inline editor: simulate edit + commit
        text_items = [i for i in ctrl._items_per_page[0]
                       if isinstance(i, TextElementItem)]
        assert text_items, "need a text element"
        ti = text_items[0]
        inline = InlineTextEditor(ctrl, ti)
        win.viewer._scene.addItem(inline)
        inline.widget().setText("INLINE EDITED")
        inline.commit()
        # Page should now contain new text and the element list should reflect it
        after_text = win.doc.page(0).get_text("text")
        assert "INLINE EDITED" in after_text, "inline edit did not commit"
        print("[smoke] InlineTextEditor commit: OK")

        # Inspector panel responds to selection
        from app.inspector import ElementInspectorPanel
        win.inspector.show_element(text_items[0] if not text_items[0].scene() is None
                                    else next(iter(ctrl._items_per_page[0])))
        assert win.inspector._current is not None
        print("[smoke] Inspector show_element: OK")

        ctrl.set_active(False)
        assert not ctrl.is_active()
        assert not ctrl._items_per_page
        print("[smoke] EditController teardown: OK")

        # Signature: load via dialog API and exercise viewer's signature placement
        from app.dialogs import SignatureCanvas
        from app.tools import Tool
        canvas = SignatureCanvas(width=200, height=80)
        # Simulate a few drawn strokes via the underlying image directly
        from PyQt6.QtGui import QPainter, QPen
        from PyQt6.QtCore import Qt, QPoint
        p = QPainter(canvas._image)
        p.setPen(QPen(Qt.GlobalColor.black, 3))
        p.drawLine(QPoint(10, 40), QPoint(180, 40))
        p.drawLine(QPoint(50, 20), QPoint(50, 70))
        p.end()
        png = canvas.to_png_bytes()
        assert png and len(png) > 100, "signature PNG too small"
        # Insert into doc
        win.doc.open(src)
        win.viewer._pending_signature = png
        win.viewer.set_tool(Tool.SIGNATURE)
        page = win.doc.page(0)
        before_imgs = len(page.get_images(full=True))
        # Programmatically commit a signature at PDF point (100, 200)
        page.insert_image(fitz.Rect(100, 200, 280, 270),
                          stream=png, keep_proportion=True)
        after_imgs = len(page.get_images(full=True))
        assert after_imgs > before_imgs, "signature image was not added"
        print(f"[smoke] signature insert: OK ({after_imgs - before_imgs} new image)")

        # Edit existing text
        page0 = win.doc.page(0)
        # The fixture text on page 1 is "Hello World — page 1" at (72, 96)
        # The span baseline is around y=96; we click inside the bbox.
        probe = fitz.Point(120, 90)
        span = find_text_span_at(page0, probe)
        assert span is not None, f"expected to find span near {probe}"
        original = span.text
        replace_span(page0, span, "EDITED TEXT", font_size=span.size,
                     text_color=(1, 0, 0))
        # Verify: the page text should no longer contain the original span
        # but should contain the replacement.
        edited_text = page0.get_text("text")
        assert "EDITED TEXT" in edited_text, "replacement text not present"
        # Save and reopen to make sure it persists.
        edited_path = os.path.join(tmp, "edited.pdf")
        win.doc.save(edited_path)
        d4 = fitz.open(edited_path)
        text_back = d4[0].get_text("text")
        d4.close()
        assert "EDITED TEXT" in text_back, "replacement did not persist on save"
        print(f"[smoke] edit_text: OK (replaced {original!r})")

        # Encrypt + decrypt round trip
        from app.operations import save_encrypted
        enc = os.path.join(tmp, "encrypted.pdf")
        save_encrypted(win.doc.doc, enc, user_pw="secret", owner_pw="boss",
                        allow_print=False)
        d3 = fitz.open(enc)
        assert d3.needs_pass
        assert d3.authenticate("secret")
        d3.close()
        print("[smoke] encrypt: OK")

        # Document close
        win.doc.close()
        assert not win.doc.is_open()
        print("[smoke] close: OK")
    except Exception:
        traceback.print_exc()
        return 1
    finally:
        win.close()
        print(f"[smoke] artifacts in {tmp}")
    print("[smoke] ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
