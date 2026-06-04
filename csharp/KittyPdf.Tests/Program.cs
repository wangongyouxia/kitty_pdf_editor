using System.Runtime.InteropServices;
using KittyPdf.Core;
using KittyPdf.Core.Interop;

// ======================================================================
// KittyPdf editing test suite — 100+ cases across text / size / image /
// signature / page / document operations.  Each Check is one case.
// Exit code is non-zero if any case fails.
// ======================================================================

int pass = 0, fail = 0;
var failures = new List<string>();
void Check(bool cond, string msg)
{
    if (cond) pass++;
    else { fail++; failures.Add(msg); }
    Console.WriteLine((cond ? "[ OK ] " : "[FAIL] ") + msg);
}
void Section(string s) => Console.WriteLine($"\n==== {s} ====");

Pdfium.FPDF_InitLibrary();

string Fix(string n) => Path.Combine(AppContext.BaseDirectory, "testfixtures", n);
byte[] FixBytes(string n) => File.ReadAllBytes(Fix(n));

// --- author a 1-page Latin doc with one text run (raw PDFium) ---
byte[] MakeLatin(string font, string text, double x, double y, double size = 20)
{
    IntPtr doc = Pdfium.FPDF_CreateNewDocument();
    IntPtr page = Pdfium.FPDFPage_New(doc, 0, 400, 200);
    IntPtr obj = Pdfium.FPDFPageObj_NewTextObj(doc, font, (float)size);
    Pdfium.FPDFText_SetText(obj, text);
    Pdfium.FPDFPageObj_Transform(obj, 1, 0, 0, 1, x, y);
    Pdfium.FPDFPage_InsertObject(page, obj);
    Pdfium.FPDFPage_GenerateContent(page);
    var ms = new MemoryStream();
    WriteBlockFn w = (_, d, s) => { var c = new byte[s]; Marshal.Copy(d, c, 0, (int)s); ms.Write(c, 0, c.Length); return 1; };
    var fw = new FPDF_FILEWRITE { version = 1, WriteBlock = Marshal.GetFunctionPointerForDelegate(w) };
    Pdfium.FPDF_SaveAsCopy(doc, ref fw, Pdfium.FPDF_NO_INCREMENTAL);
    GC.KeepAlive(w);
    Pdfium.FPDF_CloseDocument(doc);
    return ms.ToArray();
}

List<PdfElement> Texts(PdfDocument d, int p = 0) =>
    d.GetElements(p).Where(e => e.Kind == PdfElementKind.Text).ToList();
List<PdfElement> Images(PdfDocument d, int p = 0) =>
    d.GetElements(p).Where(e => e.Kind == PdfElementKind.Image).ToList();

// ======================================================================
Section("A. Text MOVE preserves font + shifts exactly");
var moveFonts = new[] { "Helvetica", "Helvetica-Bold", "Times-Roman", "Courier", "Times-BoldItalic", "Courier-Bold" };
var moveDeltas = new (double dx, double dy)[] { (60, 0), (0, 45), (-30, -20), (100, -55) };
int mi = 0;
foreach (var f in moveFonts)
{
    var (dx, dy) = moveDeltas[mi % moveDeltas.Length]; mi++;
    byte[] doc = MakeLatin(f, "Sample", 60, 100);
    PdfElement before;
    using (var d = PdfDocument.Load(doc)) before = Texts(d).First();
    byte[] moved;
    using (var d = PdfDocument.Load(doc)) { d.MoveElement(0, before.Index, dx, dy); moved = d.SaveToBytes(); }
    using var r = PdfDocument.Load(moved);
    var after = Texts(r).First();
    Check(after.FontName == before.FontName, $"move[{f}] font preserved ({before.FontName})");
    Check(Math.Abs((after.Left - before.Left) - dx) < 1.0 && Math.Abs((after.Bottom - before.Bottom) - dy) < 1.0,
        $"move[{f}] shifted by ({dx},{dy})  got ({after.Left - before.Left:0.#},{after.Bottom - before.Bottom:0.#})");
}

// ======================================================================
Section("B. Text RESIZE (scale) preserves font, changes size");
var scales = new (double sx, double sy)[] { (2.0, 2.0), (0.5, 0.5), (1.5, 1.0), (1.0, 2.0), (3.0, 3.0), (0.75, 0.75) };
foreach (var (sx, sy) in scales)
{
    byte[] doc = MakeLatin("Helvetica", "ResizeMe", 60, 100);
    PdfElement b;
    using (var d = PdfDocument.Load(doc)) b = Texts(d).First();
    double nL = b.Left, nB = b.Bottom, nR = b.Left + b.Width * sx, nT = b.Bottom + b.Height * sy;
    byte[] res;
    using (var d = PdfDocument.Load(doc)) { d.TransformElementToRect(0, b.Index, b.Left, b.Bottom, b.Right, b.Top, nL, nB, nR, nT); res = d.SaveToBytes(); }
    using var r = PdfDocument.Load(res);
    var a = Texts(r).First();
    Check(a.FontName == b.FontName, $"resize x{sx}/{sy} font preserved");
    Check(Math.Abs(a.Width - b.Width * sx) < Math.Max(2, b.Width * sx * 0.15),
        $"resize x{sx} width≈{b.Width * sx:0.#} got {a.Width:0.#}");
}

// ======================================================================
Section("C. Text EDIT subset-safe keeps exact font (Latin base-14 covers all)");
var subsetCases = new[]
{
    ("Helvetica", "ABCDEF", "FEDCBA"),
    ("Helvetica", "ABCDEF", "ABC"),
    ("Times-Roman", "Hello", "Hellooo"),
    ("Courier", "12345", "54321"),
    ("Helvetica-Bold", "ABAB", "BABA"),   // reorder, all chars present
    ("Times-Italic", "abc", "cba"),
};
foreach (var (font, old, neu) in subsetCases)
{
    byte[] doc = MakeLatin(font, old, 60, 100);
    PdfElement b; using (var d = PdfDocument.Load(doc)) b = Texts(d).First();
    byte[] ed;
    using (var d = PdfDocument.Load(doc)) { d.EditText(0, b.Index, neu, old, b.FontName, b.FontSize, b.IsBold, b.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed);
    var ts = Texts(r);
    Check(ts.Count == 1 && ts[0].Text == neu, $"edit[{font}] '{old}'→'{neu}' text set (1 run)");
    Check(ts.Count == 1 && ts[0].FontName == b.FontName, $"edit[{font}] subset-safe font kept ({b.FontName})");
}

// ======================================================================
Section("D. Text APPEND on CJK subset: ONE element, family-matched font, pos kept");
var cjk = FixBytes("cjk_subset.pdf");
var cjkRuns = new (string token, string famToken, string expectFont)[]
{
    ("粗体标题示例", "yahei", "yahei"), ("宋体正文内容", "sun", "simsun"), ("仿宋公文样式", "fang", "fangsong"),
    ("黑体小标题", "hei", "simhei"), ("楷体注释文字", "kai", "kaiti"),
};
string NormName(string? s) => PdfDocument.NormalizeFontName(s);
foreach (var (token, famToken, expectFont) in cjkRuns)
{
    PdfElement orig;
    using (var d = PdfDocument.Load(cjk)) orig = Texts(d).First(e => (e.Text ?? "").Contains(token));
    int beforeCount; using (var d = PdfDocument.Load(cjk)) beforeCount = Texts(d).Count;
    string newText = (orig.Text ?? "") + "X";
    byte[] ed;
    using (var d = PdfDocument.Load(cjk)) { d.EditText(0, orig.Index, newText, orig.Text ?? "", orig.FontName, orig.FontSize, orig.IsBold, orig.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed);
    var ts = Texts(r);
    var run = ts.FirstOrDefault(e => e.Text == newText);
    Check(ts.Count == beforeCount, $"append[{famToken}] stays ONE element (count {ts.Count} == {beforeCount})");
    Check(run != null, $"append[{famToken}] run holds full new text '{newText}'");
    Check(run != null && Math.Abs(run.Left - orig.Left) < 1 && Math.Abs(run.Bottom - orig.Bottom) < 2,
        $"append[{famToken}] position kept");
    Check(run != null && NormName(run.FontName).Contains(expectFont),
        $"append[{famToken}] font family matched ({run?.FontName})");
}

// ======================================================================
Section("E. Text full REPLACE on CJK subset rebuilds in matched family (one element)");
foreach (var (token, famToken, expectFont) in cjkRuns.Take(4))
{
    PdfElement orig;
    using (var d = PdfDocument.Load(cjk)) orig = Texts(d).First(e => (e.Text ?? "").Contains(token));
    int beforeCount; using (var d = PdfDocument.Load(cjk)) beforeCount = Texts(d).Count;
    string newText = "全新内容";
    byte[] ed;
    using (var d = PdfDocument.Load(cjk)) { d.EditText(0, orig.Index, newText, orig.Text ?? "", orig.FontName, orig.FontSize, orig.IsBold, orig.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed);
    var ts = Texts(r);
    var rep = ts.FirstOrDefault(e => e.Text == newText);
    Check(ts.Count == beforeCount, $"replace[{famToken}] stays ONE element");
    Check(rep != null && NormName(rep.FontName).Contains(expectFont), $"replace[{famToken}] family matched ({rep?.FontName})");
}

// ======================================================================
Section("F. Text DELETE removes the run");
for (int k = 0; k < 4; k++)
{
    byte[] doc = MakeLatin("Helvetica", $"Del{k}", 60, 100);
    PdfElement b; using (var d = PdfDocument.Load(doc)) b = Texts(d).First();
    byte[] del;
    using (var d = PdfDocument.Load(doc)) { d.DeleteElement(0, b.Index); del = d.SaveToBytes(); }
    using var r = PdfDocument.Load(del);
    Check(Texts(r).Count == 0, $"delete case {k}: run removed");
}

// ======================================================================
Section("G. Text COLOR change persists");
var colors = new (uint r, uint g, uint b)[] { (255, 0, 0), (0, 128, 0), (0, 0, 255), (200, 100, 50) };
foreach (var (cr, cg, cb) in colors)
{
    byte[] doc = MakeLatin("Helvetica", "Colored", 60, 100);
    PdfElement b; using (var d = PdfDocument.Load(doc)) b = Texts(d).First();
    byte[] col;
    using (var d = PdfDocument.Load(doc)) { d.SetElementColor(0, b.Index, cr, cg, cb, 255); col = d.SaveToBytes(); }
    using var r = PdfDocument.Load(col);
    var a = Texts(r).First();
    Check(Math.Abs(a.Color.R - cr / 255.0) < 0.03 && Math.Abs(a.Color.G - cg / 255.0) < 0.03 && Math.Abs(a.Color.B - cb / 255.0) < 0.03,
        $"color ({cr},{cg},{cb}) persisted got ({a.Color.R:0.##},{a.Color.G:0.##},{a.Color.B:0.##})");
}

// ======================================================================
Section("H. IMAGE insert / move / resize / delete / signature(alpha)");
byte[] SolidBgra(int w, int h, byte r, byte g, byte b, byte a)
{
    var px = new byte[w * h * 4];
    for (int i = 0; i < px.Length; i += 4) { px[i] = b; px[i + 1] = g; px[i + 2] = r; px[i + 3] = a; }
    return px;
}
{
    byte[] doc = MakeLatin("Helvetica", "Doc", 40, 160);
    var img = SolidBgra(8, 8, 0, 0, 255, 255);
    byte[] withImg;
    using (var d = PdfDocument.Load(doc)) { d.InsertImage(0, img, 8, 8, 50, 50, 40, 40); withImg = d.SaveToBytes(); }
    PdfElement im;
    using (var d = PdfDocument.Load(withImg))
    {
        var ims = Images(d);
        Check(ims.Count == 1, $"image inserted (count {ims.Count})");
        im = ims.First();
        Check(Math.Abs(im.Left - 50) < 3 && Math.Abs(im.Width - 40) < 3, $"image bounds ≈(50,40w) got ({im.Left:0.#},{im.Width:0.#})");
    }
    byte[] moved;
    using (var d = PdfDocument.Load(withImg)) { var i = Images(d).First(); d.MoveElement(0, i.Index, 120, 30); moved = d.SaveToBytes(); }
    using (var d = PdfDocument.Load(moved)) { var i = Images(d).First(); Check(Math.Abs(i.Left - (im.Left + 120)) < 3 && Math.Abs(i.Bottom - (im.Bottom + 30)) < 3, $"image moved +120,+30 (got {i.Left - im.Left:0.#},{i.Bottom - im.Bottom:0.#})"); }
    byte[] sz;
    using (var d = PdfDocument.Load(withImg)) { var i = Images(d).First(); d.TransformElementToRect(0, i.Index, i.Left, i.Bottom, i.Right, i.Top, i.Left, i.Bottom, i.Left + i.Width * 2, i.Bottom + i.Height * 2); sz = d.SaveToBytes(); }
    using (var d = PdfDocument.Load(sz)) { var i = Images(d).First(); Check(Math.Abs(i.Width - im.Width * 2) < 4, $"image resized x2 width≈{im.Width * 2:0.#} got {i.Width:0.#}"); }
    byte[] del;
    using (var d = PdfDocument.Load(withImg)) { var i = Images(d).First(); d.DeleteElement(0, i.Index); del = d.SaveToBytes(); }
    using (var d = PdfDocument.Load(del)) Check(Images(d).Count == 0, "image deleted");
    var sig = SolidBgra(16, 16, 0, 0, 0, 255);
    for (int yy = 0; yy < 4; yy++) for (int xx = 0; xx < 4; xx++) sig[(yy * 16 + xx) * 4 + 3] = 0;
    byte[] withSig;
    using (var d = PdfDocument.Load(doc)) { d.InsertImage(0, sig, 16, 16, 80, 60, 60, 60); withSig = d.SaveToBytes(); }
    using (var d = PdfDocument.Load(withSig)) Check(Images(d).Count == 1, "signature(alpha) image inserted");
}
for (int k = 0; k < 6; k++)
{
    byte[] doc = MakeLatin("Helvetica", "P", 10, 10);
    double x = 20 + k * 15, y = 20 + k * 10, w = 30 + k * 8, h = 20 + k * 6;
    var img = SolidBgra(6, 6, (byte)(40 * k), 100, 200, 255);
    byte[] wi;
    using (var d = PdfDocument.Load(doc)) { d.InsertImage(0, img, 6, 6, x, y, w, h); wi = d.SaveToBytes(); }
    using var r = PdfDocument.Load(wi);
    var i = Images(r).First();
    Check(Math.Abs(i.Left - x) < 3 && Math.Abs(i.Width - w) < 3, $"image#{k} at ({x:0},{y:0}) {w:0}x{h:0} ok");
}

// ======================================================================
Section("I. PAGE operations");
var multi = FixBytes("multi.pdf");
using (var d = PdfDocument.Load(multi)) Check(d.PageCount == 4, $"fixture multi has 4 pages (got {d.PageCount})");
foreach (int deg in new[] { 90, 180, 270, -90 })
{
    using var d = PdfDocument.Load(multi);
    d.RotatePages(new[] { 0 }, deg);
    using var r = PdfDocument.Load(d.SaveToBytes());
    Check(r.PageCount == 4, $"rotate {deg}° keeps 4 pages");
}
foreach (var idxs in new[] { new[] { 0 }, new[] { 1, 2 } })
{
    using var d = PdfDocument.Load(multi);
    d.DeletePages(idxs);
    Check(d.PageCount == 4 - idxs.Length, $"delete {idxs.Length} page(s) → {4 - idxs.Length}");
}
foreach (int at in new[] { 0, 2, 4 })
{
    using var d = PdfDocument.Load(multi);
    d.InsertBlankPage(at, 300, 300);
    Check(d.PageCount == 5, $"insert blank at {at} → 5 pages");
}
using (var d = PdfDocument.Load(multi))
{
    using var r = PdfDocument.Load(d.DuplicatePagesToBytes(new[] { 1 }));
    Check(r.PageCount == 5, "duplicate page 1 → 5 pages");
}
foreach (var order in new[] { new[] { 3, 2, 1, 0 }, new[] { 0, 0, 1 } })
{
    using var d = PdfDocument.Load(multi);
    using var r = PdfDocument.Load(d.ReorderToBytes(order));
    Check(r.PageCount == order.Length, $"reorder [{string.Join(",", order)}] → {order.Length} pages");
    var firstText = Texts(r, 0).First().Text;
    Check(firstText == $"PAGE-{(char)('A' + order[0])}", $"reorder first page is {(char)('A' + order[0])} (got {firstText})");
}
using (var d = PdfDocument.Load(multi))
{
    string tmp = Path.Combine(Path.GetTempPath(), "kpdf_extract.pdf");
    d.ExtractPagesToFile(new[] { 1, 3 }, tmp);
    using var r = PdfDocument.Load(File.ReadAllBytes(tmp));
    Check(r.PageCount == 2, "extract 2 pages");
    File.Delete(tmp);
}
using (var d = PdfDocument.Load(multi))
{
    string dir = Path.Combine(Path.GetTempPath(), "kpdf_split_" + Guid.NewGuid().ToString("N")[..6]);
    Directory.CreateDirectory(dir);
    var ranges = new List<(int, int)> { (0, 1), (2, 3) };
    var written = d.SplitToFiles(ranges, dir, "doc");
    Check(written.Count == 2, $"split into 2 files (got {written.Count})");
    Check(written.All(f => { using var r = PdfDocument.Load(File.ReadAllBytes(f)); return r.PageCount == 2; }), "each split part has 2 pages");
    Directory.Delete(dir, true);
}
{
    var a = MakeLatin("Helvetica", "MA", 50, 100);
    var b = MakeLatin("Helvetica", "MB", 50, 100);
    using var r2 = PdfDocument.Load(PdfDocument.MergeToBytes(new[] { a, b }));
    Check(r2.PageCount == 2, "merge 2 docs → 2 pages");
    using var r3 = PdfDocument.Load(PdfDocument.MergeToBytes(new[] { a, b, multi }));
    Check(r3.PageCount == 6, "merge 2 + 4-page fixture → 6 pages");
}

// ======================================================================
Section("J. DOCUMENT operations");
foreach (var wm in new[] { "DRAFT", "机密文件" })
{
    using var d = PdfDocument.Load(multi);
    d.AddTextWatermark(wm);
    using var r = PdfDocument.Load(d.SaveToBytes());
    Check(r.GetPageText(0).Contains(wm), $"watermark '{wm}' present");
}
foreach (var fmt in new[] { "{page} / {total}", "第 {page} 页" })
{
    using var d = PdfDocument.Load(multi);
    d.AddPageNumbers(fmt);
    using var r = PdfDocument.Load(d.SaveToBytes());
    Check(r.GetPageText(0).Contains("1"), $"page-number '{fmt}' present");
}
{
    string enc = Path.Combine(Path.GetTempPath(), "kpdf_enc.pdf");
    PdfSharpOps.EncryptToFile(multi, enc, "u", "owner", allowPrint: false);
    var encB = File.ReadAllBytes(enc);
    bool blocked = false; try { PdfDocument.Load(encB); } catch { blocked = true; }
    Check(blocked, "encrypted blocks open without password");
    using var r = PdfDocument.Load(PdfSharpOps.DecryptToBytes(encB, "owner"));
    Check(r.PageCount == 4, "decrypt with owner pw → 4 pages");
    File.Delete(enc);
}
foreach (var (t, au) in new[] { ("Title", "Author"), ("论文标题", "张三") })
{
    var ed = PdfSharpOps.SetInfo(multi, new PdfSharpOps.DocInfo(t, au, "subj", "kw", "KittyPDF"));
    var info = PdfSharpOps.GetInfo(ed);
    Check(info.Title == t && info.Author == au, $"metadata '{t}'/'{au}' round-trips");
}

// ======================================================================
Section("K. SEARCH + text extraction");
using (var d = PdfDocument.Load(multi))
{
    Check(d.Search("PAGE-A").Count == 1, "search PAGE-A → 1 hit");
    Check(d.Search("page index").Count == 4, "search 'page index' → 4 hits");
    Check(d.GetPageText(2).Contains("PAGE-C"), "page 2 text has PAGE-C");
    Check(d.GetAllText().Contains("PAGE-D"), "all-text has PAGE-D");
}

// ======================================================================
Section("L. Font family matching (greedy-substring safe)");
var famCases = new (string name, bool bold, string expect)[]
{
    ("SimSun", false, "simsun.ttc"), ("ABCDEF+SimSun", false, "simsun.ttc"),
    ("宋体", false, "simsun.ttc"), ("STSong", false, "simsun.ttc"),
    ("FangSong", false, "simfang.ttf"), ("仿宋", false, "simfang.ttf"),
    ("ABCDEF+FangSong", false, "simfang.ttf"),
    ("KaiTi", false, "simkai.ttf"), ("楷体", false, "simkai.ttf"), ("STKaiti", false, "simkai.ttf"),
    ("SimHei", false, "simhei.ttf"), ("黑体", false, "simhei.ttf"),
    ("MicrosoftYaHei", false, "msyh.ttc"), ("Microsoft YaHei", false, "msyh.ttc"),
    ("微软雅黑", false, "msyh.ttc"), ("MicrosoftYaHei", true, "msyhbd.ttc"),
    ("DengXian", false, "msyh.ttc"),
};
foreach (var (name, bold, expect) in famCases)
{
    var got = PdfDocument.MatchFamilyFile(name, bold);
    Check(got == expect, $"family '{name}'{(bold ? " bold" : "")} → {expect} (got {got ?? "null"})");
}
Check(PdfDocument.MatchFamilyFile("Helvetica", false) == null, "Helvetica → no CJK family");
Check(PdfDocument.MatchFamilyFile("Arial", false) == null, "Arial → no CJK family");

// ======================================================================
Section("M. Round-trip integrity (edit → save → reload → save)");
for (int k = 0; k < 4; k++)
{
    byte[] doc = MakeLatin("Helvetica", "RoundTrip", 60, 100);
    byte[] r1; using (var d = PdfDocument.Load(doc)) { d.MoveElement(0, Texts(d).First().Index, 10 * k, 5 * k); r1 = d.SaveToBytes(); }
    byte[] r2; using (var d = PdfDocument.Load(r1)) r2 = d.SaveToBytes();
    using var r = PdfDocument.Load(r2);
    Check(r.PageCount == 1 && Texts(r).Count == 1 && Texts(r)[0].Text == "RoundTrip", $"round-trip {k} stable");
}

// ======================================================================
Section("N. Latin subset edit: ONE element, family + bold matched (user's case)");
var latin = FixBytes("latin_subset.pdf");
{
    // Append "s" to subset "Anti-productive" (Times New Roman Bold).
    PdfElement orig; using (var d = PdfDocument.Load(latin)) orig = Texts(d).First(e => (e.Text ?? "").Contains("Anti"));
    int before; using (var d = PdfDocument.Load(latin)) before = Texts(d).Count;
    string nt = (orig.Text ?? "") + "s";
    byte[] ed; using (var d = PdfDocument.Load(latin)) { d.EditText(0, orig.Index, nt, orig.Text ?? "", orig.FontName, orig.FontSize, orig.IsBold, orig.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed); var ts = Texts(r);
    // (the fixture's hyphen is U+00AD; the rebuild normalises it, so match
    // on the stable substring rather than the exact string)
    var run = ts.FirstOrDefault(e => (e.Text ?? "").Contains("Anti"));
    Check(ts.Count == before, $"latin append 's' stays ONE element ({ts.Count}=={before})");
    Check(run != null && run.Text!.Contains("productive") && run.Text!.EndsWith("s"),
        $"latin append run holds full text ({run?.Text})");
    Check(run != null && NormName(run.FontName).Contains("times"), $"latin append matched Times ({run?.FontName})");
    Check(run != null && run.IsBold, $"latin append kept BOLD ({run?.FontName})");
    Check(run != null && Math.Abs(run.Left - orig.Left) < 1, "latin append position kept");
}
{
    // Replace Arial "Workplace" with new word.
    PdfElement orig; using (var d = PdfDocument.Load(latin)) orig = Texts(d).First(e => (e.Text ?? "").Contains("Workplace"));
    string nt = "Newword";
    byte[] ed; using (var d = PdfDocument.Load(latin)) { d.EditText(0, orig.Index, nt, orig.Text ?? "", orig.FontName, orig.FontSize, orig.IsBold, orig.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed);
    var run = Texts(r).FirstOrDefault(e => e.Text == nt);
    Check(run != null && NormName(run.FontName).Contains("arial"), $"latin replace matched Arial ({run?.FontName})");
}
// Full (non-subset) fonts keep their EXACT face even when new glyphs are added.
foreach (var bf in new[] { "Times-Bold", "Helvetica", "Courier-Bold" })
{
    byte[] doc = MakeLatin(bf, "Word", 60, 100);
    PdfElement b; using (var d = PdfDocument.Load(doc)) b = Texts(d).First();
    string nt = "Words!";
    byte[] ed; using (var d = PdfDocument.Load(doc)) { d.EditText(0, b.Index, nt, "Word", b.FontName, b.FontSize, b.IsBold, b.IsItalic); ed = d.SaveToBytes(); }
    using var r = PdfDocument.Load(ed); var ts = Texts(r);
    Check(ts.Count == 1 && ts[0].Text == nt && ts[0].FontName == b.FontName,
        $"full font '{bf}' append keeps exact font, one element (got {ts.FirstOrDefault()?.FontName})");
}

// ======================================================================
Console.WriteLine($"\n================  {pass} passed, {fail} failed  ================");
if (fail > 0)
{
    Console.WriteLine("FAILURES:");
    foreach (var f in failures) Console.WriteLine("  - " + f);
}
return fail == 0 ? 0 : 1;

[UnmanagedFunctionPointer(CallingConvention.Cdecl)]
delegate int WriteBlockFn(IntPtr pThis, IntPtr data, uint size);
