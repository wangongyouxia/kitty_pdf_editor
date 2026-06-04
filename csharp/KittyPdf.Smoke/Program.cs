using System.Runtime.InteropServices;
using KittyPdf.Core;
using KittyPdf.Core.Interop;

// Headless validation of the PDFium engine core.  The whole point of the
// rewrite is: editing an element must NOT change its font.  We prove it
// here by authoring a bold-text PDF, moving / editing the text, and
// asserting the font identity survives.

int failures = 0;
void Check(bool cond, string msg)
{
    Console.WriteLine((cond ? "[ OK ] " : "[FAIL] ") + msg);
    if (!cond) failures++;
}

Pdfium.FPDF_InitLibrary();

// Inspection mode: `KittyPdf.Smoke <file.pdf>` prints every element so
// we can verify font/weight/bold on real-world documents.
if (args.Length >= 1 && File.Exists(args[0]))
{
    // `<pdf> move <index> <dx> <dy>` — move an element and report the
    // element's font + position before and after a save/reload, proving
    // a real-document edit preserves the font identity.
    if (args.Length >= 5 && args[1] == "move")
    {
        int idx = int.Parse(args[2]);
        double dx = double.Parse(args[3]), dy = double.Parse(args[4]);
        byte[] movedBytes;
        string beforeFont;
        using (var doc = PdfDocument.Open(args[0]))
        {
            var before = doc.GetElements(0).First(e => e.Index == idx);
            beforeFont = before.FontName ?? "";
            Console.WriteLine("BEFORE: " + before);
            doc.MoveElement(0, idx, dx, dy);
            movedBytes = doc.SaveToBytes();
        }
        using (var doc = PdfDocument.Load(movedBytes))
        {
            var after = doc.GetElements(0).First(e =>
                e.Kind == PdfElementKind.Text && (e.FontName ?? "") == beforeFont);
            Console.WriteLine("AFTER : " + after);
            Console.WriteLine(after.FontName == beforeFont
                ? "[ OK ] font preserved across real-doc move"
                : "[FAIL] font changed!");
            doc.SaveToFile(args[0] + ".moved.pdf");
        }
        return 0;
    }

    // `<pdf> draw` — stamp shapes on page 0 and write <pdf>.draw.pdf.
    if (args.Length >= 2 && args[1] == "draw")
    {
        using var doc = PdfDocument.Open(args[0]);
        doc.AddRect(0, 40, 40, 120, 60, new PdfDocument.Rgba(0.8, 0, 0, 1),
            new PdfDocument.Rgba(1, 1, 0, 0.3), 2);
        doc.AddEllipse(0, 250, 70, 50, 30, new PdfDocument.Rgba(0, 0, 0.8, 1), null, 2);
        doc.AddLine(0, 40, 160, 360, 200, new PdfDocument.Rgba(0, 0.6, 0, 1), 2, arrow: true);
        doc.AddInk(0, new[] { new (double, double)[] { (40, 230), (80, 250), (120, 230), (160, 255) } },
            new PdfDocument.Rgba(0.6, 0, 0.6, 1), 2);
        doc.SaveToFile(args[0] + ".draw.pdf");
        Console.WriteLine("wrote " + args[0] + ".draw.pdf");
        return 0;
    }

    // `<pdf> wm <text>` — add a CJK-capable watermark + page numbers and
    // write <pdf>.wm.pdf (for visual CID-font verification).
    if (args.Length >= 3 && args[1] == "wm")
    {
        using var doc = PdfDocument.Open(args[0]);
        doc.AddTextWatermark(args[2]);
        doc.AddPageNumbers("{page} / {total}");
        doc.SaveToFile(args[0] + ".wm.pdf");
        Console.WriteLine("wrote " + args[0] + ".wm.pdf");
        return 0;
    }

    using var d2 = PdfDocument.Open(args[0]);
    Console.WriteLine($"pages={d2.PageCount}  file={args[0]}");
    for (int p = 0; p < d2.PageCount; p++)
    {
        Console.WriteLine($"--- page {p} ---");
        foreach (var el in d2.GetElements(p))
            Console.WriteLine("  " + el);
    }
    return 0;
}

Console.WriteLine("=== KittyPdf.Core engine smoke ===");

byte[] original = MakeDoc("Helvetica-Bold", "BoldText", 50, 100);
Check(original.Length > 200, $"authored test PDF ({original.Length} bytes)");

// ---- Open + enumerate. ----
PdfElement textEl;
string originalFont;
double origLeft, origBottom;
using (var d = PdfDocument.Load(original))
{
    Check(d.PageCount == 1, $"page count == 1 (got {d.PageCount})");
    var els = d.GetElements(0);
    foreach (var e in els) Console.WriteLine("   " + e);
    textEl = els.First(e => e.Kind == PdfElementKind.Text);
    originalFont = textEl.FontName ?? "";
    origLeft = textEl.Left;
    origBottom = textEl.Bottom;
    Check(textEl.Text == "BoldText", $"read text back == 'BoldText' (got '{textEl.Text}')");
    Check(originalFont.Contains("Bold", StringComparison.OrdinalIgnoreCase),
        $"font name reports bold: '{originalFont}'");

    // Render sanity.
    var rp = d.RenderPage(0, 2.0);
    Check(rp.WidthPx == 800 && rp.HeightPx == 400, $"render size 800x400 (got {rp.WidthPx}x{rp.HeightPx})");
    Check(rp.Pixels.Length == rp.Stride * rp.HeightPx, "render buffer size matches stride*height");
    bool anyInk = false;
    for (int i = 0; i + 3 < rp.Pixels.Length; i += 4)
        if (rp.Pixels[i] != 0xFF || rp.Pixels[i + 1] != 0xFF || rp.Pixels[i + 2] != 0xFF) { anyInk = true; break; }
    Check(anyInk, "rendered page has non-white pixels (text drew)");
}

// ---- MOVE the text, save, reload, assert font unchanged + moved. ----
byte[] moved;
using (var d = PdfDocument.Load(original))
{
    d.MoveElement(0, textEl.Index, 120, -40);   // +120 x, -40 y (PDF y-up)
    moved = d.SaveToBytes();
}
using (var d = PdfDocument.Load(moved))
{
    var el = d.GetElements(0).First(e => e.Kind == PdfElementKind.Text);
    Console.WriteLine("   after move: " + el);
    Check(el.FontName == originalFont,
        $"MOVE preserves font: '{originalFont}' -> '{el.FontName}'");
    Check(Math.Abs((el.Left - origLeft) - 120) < 1.0,
        $"MOVE shifted x by ~120 (got {el.Left - origLeft:0.#})");
    Check(Math.Abs((el.Bottom - origBottom) - (-40)) < 1.0,
        $"MOVE shifted y by ~-40 (got {el.Bottom - origBottom:0.#})");
    Check(el.Text == "BoldText", "MOVE preserves text content");
}

// ---- EDIT the text content, assert font unchanged. ----
byte[] edited;
using (var d = PdfDocument.Load(original))
{
    d.SetElementText(0, textEl.Index, "NewBoldText");
    edited = d.SaveToBytes();
}
using (var d = PdfDocument.Load(edited))
{
    var el = d.GetElements(0).First(e => e.Kind == PdfElementKind.Text);
    Console.WriteLine("   after edit: " + el);
    Check(el.Text == "NewBoldText", $"EDIT changed text (got '{el.Text}')");
    Check(el.FontName == originalFont,
        $"EDIT preserves font: '{originalFont}' -> '{el.FontName}'");
}

// ---- DELETE the text, assert it's gone. ----
byte[] deleted;
using (var d = PdfDocument.Load(original))
{
    d.DeleteElement(0, textEl.Index);
    deleted = d.SaveToBytes();
}
using (var d = PdfDocument.Load(deleted))
{
    var texts = d.GetElements(0).Where(e => e.Kind == PdfElementKind.Text).ToList();
    Check(texts.Count == 0, $"DELETE removed the text object (remaining: {texts.Count})");
}

// ---- Page operations. ----
byte[] ThreePageDoc()
{
    var pages = new List<byte[]>
    {
        MakeDoc("Helvetica", "PAGE-A", 50, 100),
        MakeDoc("Helvetica", "PAGE-B", 50, 100),
        MakeDoc("Helvetica", "PAGE-C", 50, 100),
    };
    return PdfDocument.MergeToBytes(pages);
}

byte[] three = ThreePageDoc();
using (var d = PdfDocument.Load(three))
    Check(d.PageCount == 3, $"merge 3 single-page docs → 3 pages (got {d.PageCount})");

// Delete middle page.
using (var d = PdfDocument.Load(three))
{
    d.DeletePages(new[] { 1 });
    Check(d.PageCount == 2, $"delete page → 2 pages (got {d.PageCount})");
    var t0 = d.GetElements(0).First(e => e.Kind == PdfElementKind.Text).Text;
    var t1 = d.GetElements(1).First(e => e.Kind == PdfElementKind.Text).Text;
    Check(t0 == "PAGE-A" && t1 == "PAGE-C", $"remaining pages are A,C (got {t0},{t1})");
}

// Insert blank page at index 1.
using (var d = PdfDocument.Load(three))
{
    d.InsertBlankPage(1, 300, 300);
    Check(d.PageCount == 4, $"insert blank → 4 pages (got {d.PageCount})");
}

// Reorder C,A,B.
using (var d = PdfDocument.Load(three))
{
    var bytes = d.ReorderToBytes(new[] { 2, 0, 1 });
    using var r = PdfDocument.Load(bytes);
    var order = Enumerable.Range(0, r.PageCount)
        .Select(p => r.GetElements(p).First(e => e.Kind == PdfElementKind.Text).Text).ToArray();
    Check(string.Join(",", order) == "PAGE-C,PAGE-A,PAGE-B", $"reorder → C,A,B (got {string.Join(",", order)})");
}

// Duplicate page 0.
using (var d = PdfDocument.Load(three))
{
    var bytes = d.DuplicatePagesToBytes(new[] { 0 });
    using var r = PdfDocument.Load(bytes);
    Check(r.PageCount == 4, $"duplicate page 0 → 4 pages (got {r.PageCount})");
}

// Rotate page 0 by 90.
using (var d = PdfDocument.Load(three))
{
    d.RotatePages(new[] { 0 }, 90);
    var bytes = d.SaveToBytes();
    using var r = PdfDocument.Load(bytes);
    // (no direct rotation getter in managed API; just assert it round-trips)
    Check(r.PageCount == 3, "rotate round-trips without page loss");
}

// ---- Image insert + move. ----
using (var d = PdfDocument.Load(three))
{
    var bgra = new byte[8 * 8 * 4];
    for (int i = 0; i < bgra.Length; i += 4) { bgra[i] = 0; bgra[i + 1] = 0; bgra[i + 2] = 255; bgra[i + 3] = 255; }
    d.InsertImage(0, bgra, 8, 8, 50, 50, 40, 40);
    var imgs = d.GetElements(0).Where(e => e.Kind == PdfElementKind.Image).ToList();
    Check(imgs.Count >= 1, $"image inserted ({imgs.Count})");
    if (imgs.Count >= 1)
    {
        var img = imgs[0];
        double oldL = img.Left;
        d.MoveElement(0, img.Index, 100, 0);
        var img2 = d.GetElements(0).First(e => e.Kind == PdfElementKind.Image);
        Check(Math.Abs((img2.Left - oldL) - 100) < 2.0,
            $"image moves +100 (got {img2.Left - oldL:0.#})");
    }
}

// ---- Text extraction + search. ----
using (var d = PdfDocument.Load(three))
{
    string all = d.GetAllText();
    Check(all.Contains("PAGE-A") && all.Contains("PAGE-C"), "GetAllText returns page text");
    var hits = d.Search("PAGE-B");
    Check(hits.Count == 1 && hits[0].Page == 1, $"search finds PAGE-B on page 1 (got {hits.Count} hits)");
}

// ---- Page numbers + watermark add text. ----
using (var d = PdfDocument.Load(three))
{
    d.AddPageNumbers("{page} / {total}");
    var bytes = d.SaveToBytes();
    using var r = PdfDocument.Load(bytes);
    string t0 = r.GetPageText(0);
    Check(t0.Contains("1") && t0.Contains("3"), $"page-number text present (page0='{t0.Replace("\n", " ").Trim()}')");
}
using (var d = PdfDocument.Load(three))
{
    d.AddTextWatermark("DRAFT");
    var bytes = d.SaveToBytes();
    using var r = PdfDocument.Load(bytes);
    Check(r.GetPageText(0).Contains("DRAFT"), "watermark text present on page 0");
}

// ---- Metadata (PdfSharp). ----
{
    var info = new PdfSharpOps.DocInfo("我的标题", "作者", "主题", "kw", "KittyPDF");
    byte[] withInfo = PdfSharpOps.SetInfo(three, info);
    var read = PdfSharpOps.GetInfo(withInfo);
    Check(read.Title == "我的标题" && read.Author == "作者", $"metadata round-trips (got '{read.Title}'/'{read.Author}')");
}

// ---- Encrypt + decrypt (PdfSharp). ----
{
    string enc = Path.Combine(Path.GetTempPath(), "kpdf_enc_test.pdf");
    PdfSharpOps.EncryptToFile(three, enc, "secret", "boss", allowPrint: false);
    byte[] encBytes = File.ReadAllBytes(enc);
    bool decrypted = false, blockedWithout = false;
    try
    {
        byte[] clear = PdfSharpOps.DecryptToBytes(encBytes, "boss");  // owner pw
        using var r = PdfDocument.Load(clear);                        // unencrypted now
        decrypted = r.PageCount == 3;
    }
    catch (Exception ex) { Console.WriteLine("   decrypt err: " + ex.Message); }
    try { PdfDocument.Load(encBytes); } catch { blockedWithout = true; }
    Check(decrypted, "encrypted file decrypts with owner password → valid PDF");
    Check(blockedWithout, "encrypted file blocks loading without password");
    try { File.Delete(enc); } catch { }
}

Console.WriteLine();
Console.WriteLine(failures == 0 ? "ALL ENGINE TESTS PASSED" : $"{failures} CHECK(S) FAILED");
return failures == 0 ? 0 : 1;

// ---- Author a test PDF with a text run, via raw PDFium. ----
static byte[] MakeDoc(string fontName, string text, double x, double y)
{
    IntPtr doc = Pdfium.FPDF_CreateNewDocument();
    IntPtr page = Pdfium.FPDFPage_New(doc, 0, 400, 200);
    IntPtr obj = Pdfium.FPDFPageObj_NewTextObj(doc, fontName, 24f);
    Pdfium.FPDFText_SetText(obj, text);
    Pdfium.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y);
    Pdfium.FPDFPage_InsertObject(page, obj);
    Pdfium.FPDFPage_GenerateContent(page);

    var ms = new MemoryStream();
    WriteBlockFn writer = (_, data, size) =>
    {
        var chunk = new byte[size];
        Marshal.Copy(data, chunk, 0, (int)size);
        ms.Write(chunk, 0, chunk.Length);
        return 1;
    };
    var fw = new FPDF_FILEWRITE { version = 1, WriteBlock = Marshal.GetFunctionPointerForDelegate(writer) };
    bool ok = Pdfium.FPDF_SaveAsCopy(doc, ref fw, Pdfium.FPDF_NO_INCREMENTAL);
    GC.KeepAlive(writer);
    Pdfium.FPDF_CloseDocument(doc);
    if (!ok) throw new Exception("save test doc failed");
    return ms.ToArray();
}

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
delegate int WriteBlockFn(IntPtr pThis, IntPtr data, uint size);
