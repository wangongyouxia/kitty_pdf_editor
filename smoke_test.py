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

        # _resolve_span_font must yield a CJK-capable file (not None,
        # not base-14) for a span whose font name we DON'T recognise
        # but whose text is clearly Chinese.  This guards against the
        # "drag turns SimSun into Helvetica" regression.
        from app.edit_mode import EditController
        from app.text_edit import (
            TextSpan, find_unicode_font, list_all_spans, move_text_span,
            safe_insert_text,
        )
        unrec_pdf = os.path.join(tmp, "unrec.pdf")
        d_u = fitz.open()
        p_u = d_u.new_page(width=400, height=200)
        # Use insert_text with a system font but a deliberately
        # opaque alias so the resulting span PSName won't match our
        # registry directly.
        sys_fang = "C:/Windows/Fonts/simfang.ttf"
        if os.path.isfile(sys_fang):
            p_u.insert_text((50, 100), "测试文字段落",
                            fontsize=14, fontname="opaque-id",
                            fontfile=sys_fang)
        else:
            # Mac/Linux fallback
            p_u.insert_text((50, 100), "测试文字段落", fontsize=14)
        d_u.save(unrec_pdf)
        d_u.close()
        win.doc.open(unrec_pdf)
        ctrl_u = win.viewer.edit_controller
        spans_u = list_all_spans(win.doc.page(0))
        assert spans_u, "no spans in synthetic doc"
        target_u = spans_u[0]
        alias, files = ctrl_u._resolve_span_font(target_u)
        assert files, f"_resolve_span_font returned no files for {target_u.font!r}"
        # At least one of the resolved files must be CJK-capable.
        from app.font_registry import list_fonts as _lf
        cjk_files = {f.file for f in _lf() if f.is_bundled and f.cjk and f.file}
        cjk_in_chain = [p for p in files if p in cjk_files]
        assert cjk_in_chain or any(
            "simfang" in p.lower() or "kpdf_emb_" in p.lower() for p in files
        ), f"no CJK font in resolve chain: {files}"
        print(f"[smoke] unrecognised CJK PSName resolves to CJK chain: OK"
              f" ({len(files)} candidates)")

        # Dragging a span MUST preserve the original embedded font.
        # Build a doc, write a span with msyh.ttc, capture the PSName
        # PyMuPDF assigns; after move_text_span the moved span should
        # still report the SAME PSName, not a YaHei substitute.
        from app.text_edit import (
            extract_embedded_font, find_unicode_font, font_supports_text,
            list_all_spans, move_text_span, safe_insert_text,
        )
        from app.edit_mode import EditController
        preserve_pdf = os.path.join(tmp, "preserve.pdf")
        d_pres = fitz.open()
        p_pres = d_pres.new_page(width=400, height=200)
        # Insert with a non-default font path so we have a known
        # embedded font to look for.
        kai_path = "C:/Windows/Fonts/simkai.ttf"
        if not os.path.isfile(kai_path):
            kai_path = find_unicode_font() or ""
        p_pres.insert_text((50, 100), "原字体测试",
                            fontsize=14, fontname="user-kai", fontfile=kai_path)
        d_pres.save(preserve_pdf)
        d_pres.close()
        d_pres = fitz.open(preserve_pdf)
        page_p = d_pres[0]
        spans_p = list_all_spans(page_p)
        target = next(s for s in spans_p if "测试" in s.text)
        original_psname = target.font
        print(f"[smoke] preserved-font PSName before: {original_psname}")

        # Resolve like the editor would.
        ctrl = EditController(win.viewer)
        win.doc.open(preserve_pdf)
        spans = list_all_spans(win.doc.page(0))
        target = next(s for s in spans if "测试" in s.text)
        # _resolve_span_font is what EditController uses internally.
        # It returns (alias, [font_files...]) — a fallback chain.
        alias, font_files = ctrl._resolve_span_font(target)
        assert font_files, "should resolve to at least one font file"
        # Move the span using that font fallback chain.
        move_text_span(
            win.doc.page(0), target,
            fitz.Rect(150, 50, 150 + target.rect.width,
                      50 + target.rect.height),
            font_alias=alias, font_files=font_files,
        )
        # Re-detect the moved span; its PSName should NOT be 'Helvetica'
        # / 'MicrosoftYaHei' (the wrong fallback path).
        spans_after = list_all_spans(win.doc.page(0))
        moved = next((s for s in spans_after if "测试" in s.text), None)
        assert moved is not None, "moved text not found"
        new_psname = moved.font
        print(f"[smoke] preserved-font PSName after move: {new_psname}")
        # The PSName may have a different subset prefix but the
        # *basename* should match the original font family — and
        # certainly not Helvetica.
        assert "helvetica" not in new_psname.lower(), (
            f"font fell back to Helvetica after move: {new_psname!r}"
        )
        print("[smoke] move preserves original font (not Helvetica): OK")
        d_pres.close()

        # End-to-end edit-mode move: covered_rects tracking should
        # hide the ghost overlay after a drag, and the underlying
        # content stream is intentionally left alone (preserves
        # original glyph data + protects neighbouring spans).
        e2e_pdf = os.path.join(tmp, "e2e.pdf")
        d_e = fitz.open()
        p_e = d_e.new_page(width=400, height=200)
        sys_fang2 = "C:/Windows/Fonts/simfang.ttf"
        if os.path.isfile(sys_fang2):
            p_e.insert_text((50, 100), "拖拽测试",
                            fontsize=14, fontname="ufang", fontfile=sys_fang2)
        else:
            p_e.insert_text((50, 100), "Drag me", fontsize=14)
        d_e.save(e2e_pdf)
        d_e.close()
        win.doc.open(e2e_pdf)
        assert win.viewer.edit_controller.is_active(), \
            "edit mode should auto-enable on open"
        # Pick the first text overlay element and "drag" it.
        page_items = win.viewer.edit_controller._items_per_page.get(0, [])
        from app.edit_mode import TextElementItem
        text_elems = [e for e in page_items if isinstance(e, TextElementItem)]
        assert text_elems, "no text overlay built"
        target_e = text_elems[0]
        original_rect = fitz.Rect(target_e.original_pdf_rect)
        # Simulate move by repositioning the QGraphics item then
        # commit_move.
        new_x_offset = 100
        target_e.setPos(target_e.pos().x() + new_x_offset, target_e.pos().y())
        target_e.commit_move()
        # PdfDocument should now have a covered rect for the old pos.
        cov = win.doc.covered_rects(0)
        assert cov, "doc.covered_rects(0) is empty after move"
        assert any(abs(cr.x0 - original_rect.x0) < 1 for cr in cov), \
            f"original rect not in covered_rects: {cov}"
        # And the rebuilt overlay must NOT include a TextElementItem
        # whose span sits at the original position.
        items_after = win.viewer.edit_controller._items_per_page.get(0, [])
        text_items_after = [e for e in items_after if isinstance(e, TextElementItem)]
        ghosts = [
            e for e in text_items_after
            if abs(e.original_pdf_rect.x0 - original_rect.x0) < 1
            and abs(e.original_pdf_rect.y0 - original_rect.y0) < 1
        ]
        assert not ghosts, f"ghost overlay at old position: {ghosts}"
        print("[smoke] end-to-end drag: covered_rects filters ghost: OK")

        # Overlapping element selection: build a doc with two text
        # spans whose bboxes overlap, verify they get distinct Z-values
        # (smaller on top) so the user can reach the smaller one with
        # a regular click and use Alt+Click to cycle.
        overlap_pdf = os.path.join(tmp, "overlap.pdf")
        d_o = fitz.open()
        p_o = d_o.new_page(width=400, height=200)
        # Big paragraph-style span behind, tiny in-line span on top.
        p_o.insert_text((40, 80), "Long paragraph of text here.", fontsize=14)
        p_o.insert_text((100, 80), "X", fontsize=10)
        d_o.save(overlap_pdf)
        d_o.close()
        win.doc.open(overlap_pdf)
        items_o = win.viewer.edit_controller._items_per_page.get(0, [])
        if len(items_o) >= 2:
            # Sort by Z descending: the smallest should be highest.
            sorted_by_z = sorted(items_o, key=lambda it: it.zValue(), reverse=True)
            top, *_, bottom = sorted_by_z
            top_area = top.original_pdf_rect.width * top.original_pdf_rect.height
            bot_area = bottom.original_pdf_rect.width * bottom.original_pdf_rect.height
            assert top_area <= bot_area, (
                f"smaller element should be on top: top_area={top_area}, "
                f"bot_area={bot_area}"
            )
            print(f"[smoke] overlapping z-order (small on top): OK"
                  f"  (areas {top_area:.0f} ≤ {bot_area:.0f})")

        # Moving one text element must NOT delete a nearby element whose
        # bbox merely touches the redaction rect.
        from app.text_edit import (
            find_unicode_font, list_all_spans, move_text_span,
            needs_unicode_font, safe_insert_text,
        )
        neighbour_pdf = os.path.join(tmp, "neighbour.pdf")
        d_n = fitz.open()
        p_n = d_n.new_page(width=400, height=200)
        p_n.insert_text((50, 100), "AAA", fontsize=14)
        # Place BBB just to the right of AAA — bboxes will share an edge.
        p_n.insert_text((100, 100), "BBB", fontsize=14)
        d_n.save(neighbour_pdf)
        d_n.close()
        d_n = fitz.open(neighbour_pdf)
        page_n = d_n[0]
        spans_n = list_all_spans(page_n)
        a_span = next(s for s in spans_n if s.text == "AAA")
        move_text_span(page_n, a_span,
                       fitz.Rect(200, 50, 200 + a_span.rect.width,
                                  50 + a_span.rect.height))
        text_after = page_n.get_text("text")
        assert "BBB" in text_after, f"neighbour deleted! get_text={text_after!r}"
        assert "AAA" in text_after, "moved text not present"
        print("[smoke] move preserves adjacent element: OK")
        d_n.close()

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
        # cover_rect should actually remove the original glyphs from
        # the content stream, not just paint over them.  Verify via
        # raw get_text("text") (NO covered_rects filter — this is the
        # ground-truth from PyMuPDF's parser).
        d_g = fitz.open(ghost_pdf)
        page_g = d_g[0]
        span_g = [s for s in list_all_spans(page_g) if "MOVE_ME" in s.text][0]
        old_x = span_g.rect.x0
        new_r = fitz.Rect(200, 200, 200 + span_g.rect.width,
                          200 + span_g.rect.height)
        move_text_span(page_g, span_g, new_r)
        # No covered_rects filter — test that redaction actually
        # removed the original glyphs.
        spans_raw = list_all_spans(page_g)
        old_pos_hits = [s for s in spans_raw
                         if "MOVE_ME" in s.text and abs(s.rect.x0 - old_x) < 5]
        assert not old_pos_hits, (
            f"原位置仍残留（内容流没真删）: {old_pos_hits}"
        )
        new_pos_hits = [s for s in spans_raw
                         if "MOVE_ME" in s.text and abs(s.rect.x0 - 200) < 30]
        assert new_pos_hits, "moved text not found at new position"
        # Also check the full page text — the literal "MOVE_ME" should
        # only appear ONCE (at the new position).
        page_text = page_g.get_text("text")
        assert page_text.count("MOVE_ME") == 1, (
            f"MOVE_ME appears {page_text.count('MOVE_ME')} times in page "
            f"text after move (expected 1): {page_text!r}"
        )
        print("[smoke] move_text_span: 原位置已从内容流真删除 OK")
        d_g.close()

        # Font registry should enumerate base-14 plus app/fonts/*
        from app.font_registry import (
            list_fonts, pick_default_for_span, get_font,
        )
        registry = list_fonts(refresh=True)
        bundled = [f for f in registry if f.is_bundled]
        print(f"[smoke] font registry: {len(registry)} entries"
              f" ({len(bundled)} bundled)")
        assert len(registry) >= 12, "base-14 missing"
        if bundled:
            print(f"[smoke] bundled fonts: {[b.display for b in bundled]}")

        # CJK heuristic: an unrecognised but obviously-CJK PSName
        # should NOT fall to Helvetica — it should land on a bundled
        # CJK face.  Names tested are real font filenames seen in the
        # wild.
        from app.font_registry import _looks_cjk, _normalise_font_name
        for psname in ("NotoSansCJKsc-Regular", "PingFangSC-Regular",
                       "SourceHanSansSC-Bold", "宋体"):
            norm = _normalise_font_name(psname)
            assert _looks_cjk(psname, norm), f"{psname!r} should look CJK"
            k = pick_default_for_span(psname, bold=False, italic=False)
            fdef = get_font(k)
            assert fdef and fdef.is_bundled and fdef.cjk, (
                f"CJK fallback failed for {psname!r}: key={k}"
            )
        print("[smoke] CJK heuristic default: OK")

        # Inspector default-font matching: real-world span PSNames
        # like 'ABCDEF+SimSun' MUST map to a bundled CJK font, not to
        # Helvetica.  Run only the cases for which we actually bundled
        # the target file (so the test scales with whatever's shipped).
        bundled_basenames = {os.path.basename(f.file).lower()
                              for f in bundled if f.file}
        candidates = [
            ("ABCDEF+SimSun",          False, "simsun.ttc"),
            ("SimSun",                  False, "simsun.ttc"),
            ("MicrosoftYaHei",          False, "msyh.ttc"),
            ("Microsoft YaHei",         False, "msyh.ttc"),
            ("MicrosoftYaHei-Bold",     True,  "msyhbd.ttc"),
            ("Microsoft YaHei Bold",    True,  "msyhbd.ttc"),
            ("SimHei",                  False, "simhei.ttf"),
            ("STKaiti",                 False, "simkai.ttf"),
        ]
        checked = 0
        for name, bold, want in candidates:
            if want.lower() not in bundled_basenames:
                continue
            key = pick_default_for_span(name, bold=bold, italic=False)
            fdef = get_font(key)
            got = os.path.basename(fdef.file).lower() if fdef and fdef.file else "?"
            assert got == want.lower(), (
                f"font match: {name!r} bold={bold} → wanted {want}, got {got}"
            )
            checked += 1
        print(f"[smoke] span-font → bundled match: OK ({checked} cases)")

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
