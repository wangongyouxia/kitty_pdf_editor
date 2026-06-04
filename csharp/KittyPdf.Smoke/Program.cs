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
