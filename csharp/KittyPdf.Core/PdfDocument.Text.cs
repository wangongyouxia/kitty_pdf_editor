using KittyPdf.Core.Interop;

namespace KittyPdf.Core;

/// <summary>
/// Text-insertion features: insert a text run, watermark, page numbers.
/// New text needs a font; for CJK we load a system TrueType CID font so
/// Chinese / Japanese / Korean render instead of dropping to boxes.
/// </summary>
public sealed partial class PdfDocument
{
    // Cache loaded FPDF_FONT handles per (path|bold) for this document.
    private readonly Dictionary<string, IntPtr> _fontCache = new();

    private static readonly string[] CjkFontCandidates =
    {
        "msyh.ttc", "msyhbd.ttc", "simfang.ttf", "simsun.ttc", "simhei.ttf", "simkai.ttf",
    };

    private static string? FindSystemFont(string fileName)
    {
        string? win = Environment.GetEnvironmentVariable("WINDIR");
        if (win == null) return null;
        string p = Path.Combine(win, "Fonts", fileName);
        return File.Exists(p) ? p : null;
    }

    private static string? FindCjkFontPath(bool bold)
    {
        // Prefer a bold face when bold requested.
        if (bold)
        {
            var b = FindSystemFont("msyhbd.ttc") ?? FindSystemFont("simhei.ttf");
            if (b != null) return b;
        }
        foreach (var name in CjkFontCandidates)
        {
            var p = FindSystemFont(name);
            if (p != null) return p;
        }
        return null;
    }

    private unsafe IntPtr GetCidFontFromBytes(string key, byte[] data)
    {
        if (_fontCache.TryGetValue(key, out var cached)) return cached;
        IntPtr handle = IntPtr.Zero;
        try
        {
            fixed (byte* p = data)
            {
                handle = Pdfium.FPDFText_LoadFont(_doc, p, (uint)data.Length, 2, true);
            }
        }
        catch { handle = IntPtr.Zero; }
        _fontCache[key] = handle;
        return handle;
    }

    private IntPtr GetCidFont(string path)
    {
        try { return GetCidFontFromBytes(path, File.ReadAllBytes(path)); }
        catch { return IntPtr.Zero; }
    }

    // Embedded-font cache shared across documents (the bytes are immutable).
    private static readonly Dictionary<string, byte[]?> _embeddedFonts = new();

    private static byte[]? LoadEmbeddedFont(string logicalName)
    {
        if (_embeddedFonts.TryGetValue(logicalName, out var c)) return c;
        byte[]? data = null;
        try
        {
            using var s = typeof(PdfDocument).Assembly.GetManifestResourceStream(logicalName);
            if (s != null) { using var ms = new MemoryStream(); s.CopyTo(ms); data = ms.ToArray(); }
        }
        catch { data = null; }
        _embeddedFonts[logicalName] = data;
        return data;
    }

    /// <summary>Resolve a CJK font handle: bundled (embedded) first, else system.</summary>
    private IntPtr ResolveCjkFont(bool bold)
    {
        string res = bold ? "KittyPdf.Core.Fonts.msyhbd.ttc" : "KittyPdf.Core.Fonts.msyh.ttc";
        var bytes = LoadEmbeddedFont(res);
        if (bytes != null) return GetCidFontFromBytes(res, bytes);
        string? fp = FindCjkFontPath(bold);
        return fp != null ? GetCidFont(fp) : IntPtr.Zero;
    }

    private static bool HasNonLatin(string text)
    {
        foreach (char c in text) if (c > 0xFF) return true;
        return false;
    }

    // Map an original font family (by PSName) to a system font file that
    // has FULL coverage, so edited text keeps the original look while
    // rendering newly-typed characters the embedded subset lacks.
    private static readonly (string[] keys, string file, string boldFile)[] FamilyMap =
    {
        (new[] { "simsun", "songti", "song", "宋", "mingliu", "newsongti" }, "simsun.ttc", "simsun.ttc"),
        (new[] { "simhei", "heiti", "黑", "hei" }, "simhei.ttf", "simhei.ttf"),
        (new[] { "fangsong", "simfang", "仿", "fang" }, "simfang.ttf", "simfang.ttf"),
        (new[] { "kaiti", "simkai", "楷", "kai" }, "simkai.ttf", "simkai.ttf"),
        (new[] { "yahei", "雅黑", "msyh", "微软雅黑" }, "msyh.ttc", "msyhbd.ttc"),
    };

    private static string NormalizeFontName(string? name)
    {
        if (string.IsNullOrEmpty(name)) return "";
        string n = name;
        int plus = n.IndexOf('+');
        if (plus is >= 1 and <= 7) n = n[(plus + 1)..];   // strip "ABCDEF+" subset prefix
        return n.ToLowerInvariant().Replace(" ", "").Replace("-", "").Replace("_", "");
    }

    /// <summary>
    /// Resolve a font handle that fully covers <paramref name="text"/>, trying
    /// to match the original family; CJK falls back to the bundled YaHei,
    /// Latin to base-14 (returns Zero → caller uses a standard font).
    /// </summary>
    private IntPtr ResolveStyledFont(string? familyName, bool bold, string text)
    {
        string norm = NormalizeFontName(familyName);
        if (norm.Length > 0)
        {
            foreach (var (keys, file, boldFile) in FamilyMap)
            {
                if (!keys.Any(k => norm.Contains(NormalizeFontName(k)))) continue;
                string? path = FindSystemFont(bold ? boldFile : file) ?? FindSystemFont(file);
                if (path != null)
                {
                    var h = GetCidFont(path);
                    if (h != IntPtr.Zero) return h;
                }
                break;
            }
        }
        return HasNonLatin(text) ? ResolveCjkFont(bold) : IntPtr.Zero;
    }

    /// <summary>
    /// Edit a text object's string.  When <paramref name="subsetSafe"/> is
    /// true (every new char was already in the run) we keep the exact
    /// embedded font via FPDFText_SetText.  Otherwise we rebuild the run
    /// with a full family-matched font — same matrix (position/size/skew),
    /// colour and weight — so newly-typed glyphs render instead of boxes.
    /// </summary>
    public void ReplaceText(int pageIndex, int objectIndex, string newText,
        bool subsetSafe, string? fontName, double sizePt, bool bold)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
    {
        if (Pdfium.FPDFPageObj_GetType(obj) != Pdfium.FPDF_PAGEOBJ_TEXT) return;
        if (subsetSafe)
        {
            Pdfium.FPDFText_SetText(obj, newText);
            Pdfium.FPDFPage_GenerateContent(page);
            return;
        }
        // Capture the original transform + fill colour, then replace.
        Pdfium.FPDFPageObj_GetMatrix(obj, out var m);
        if (!Pdfium.FPDFPageObj_GetFillColor(obj, out uint r, out uint g, out uint b, out uint a))
        { r = g = b = 0; a = 255; }
        if (Pdfium.FPDFPage_RemoveObject(page, obj))
            Pdfium.FPDFPageObj_Destroy(obj);

        IntPtr font = ResolveStyledFont(fontName, bold, newText);
        IntPtr nobj = font != IntPtr.Zero
            ? Pdfium.FPDFPageObj_CreateTextObj(_doc, font, (float)sizePt)
            : Pdfium.FPDFPageObj_NewTextObj(_doc, bold ? "Helvetica-Bold" : "Helvetica", (float)sizePt);
        if (nobj != IntPtr.Zero)
        {
            Pdfium.FPDFText_SetText(nobj, newText);
            Pdfium.FPDFPageObj_SetFillColor(nobj, r, g, b, a);
            Pdfium.FPDFPageObj_SetMatrix(nobj, m);   // exact original placement
            Pdfium.FPDFPage_InsertObject(page, nobj);
        }
        Pdfium.FPDFPage_GenerateContent(page);
    });

    /// <summary>
    /// Insert a text run at PDF baseline (x,y) (y-up), optionally rotated.
    /// Uses a CJK CID font when the text needs one; otherwise a base-14
    /// standard font.
    /// </summary>
    public void InsertText(int pageIndex, string text, double x, double y,
        double sizePt, (double r, double g, double b, double a) color,
        bool bold = false, double rotationDeg = 0)
    {
        if (string.IsNullOrEmpty(text)) return;
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) return;
        try
        {
            IntPtr obj;
            if (HasNonLatin(text))
            {
                IntPtr font = ResolveCjkFont(bold);
                obj = font != IntPtr.Zero
                    ? Pdfium.FPDFPageObj_CreateTextObj(_doc, font, (float)sizePt)
                    : Pdfium.FPDFPageObj_NewTextObj(_doc, "Helvetica", (float)sizePt);
            }
            else
            {
                obj = Pdfium.FPDFPageObj_NewTextObj(_doc,
                    bold ? "Helvetica-Bold" : "Helvetica", (float)sizePt);
            }
            if (obj == IntPtr.Zero) return;

            Pdfium.FPDFText_SetText(obj, text);
            Pdfium.FPDFPageObj_SetFillColor(obj,
                (uint)Math.Round(color.r * 255), (uint)Math.Round(color.g * 255),
                (uint)Math.Round(color.b * 255), (uint)Math.Round(color.a * 255));

            double rad = rotationDeg * Math.PI / 180.0;
            double cos = Math.Cos(rad), sin = Math.Sin(rad);
            Pdfium.FPDFPageObj_Transform(obj, cos, sin, -sin, cos, x, y);

            Pdfium.FPDFPage_InsertObject(page, obj);
            Pdfium.FPDFPage_GenerateContent(page);
        }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    public void AddTextWatermark(string text, double opacity = 0.18,
        double fontSize = 60, double rotationDeg = 45,
        (double r, double g, double b)? color = null)
    {
        var c = color ?? (0.6, 0.6, 0.6);
        for (int i = 0; i < PageCount; i++)
        {
            var (w, h) = GetPageSize(i);
            double estW = text.Length * fontSize * 0.55;
            double cx = w / 2, cy = h / 2;
            double rad = rotationDeg * Math.PI / 180.0;
            // Offset the origin back along the rotated baseline so the run
            // is roughly centred on the page.
            double ox = cx - Math.Cos(rad) * estW / 2;
            double oy = cy - Math.Sin(rad) * estW / 2;
            InsertText(i, text, ox, oy, fontSize, (c.r, c.g, c.b, opacity),
                bold: false, rotationDeg: rotationDeg);
        }
    }

    public void AddPageNumbers(string format = "{page} / {total}",
        double fontSize = 10, double margin = 28, bool top = false)
    {
        int total = PageCount;
        for (int i = 0; i < PageCount; i++)
        {
            var (w, h) = GetPageSize(i);
            string text = format.Replace("{page}", (i + 1).ToString())
                                 .Replace("{total}", total.ToString());
            double estW = text.Length * fontSize * 0.5;
            double x = w / 2 - estW / 2;
            double y = top ? h - margin : margin;
            InsertText(i, text, x, y, fontSize, (0, 0, 0, 1));
        }
    }
}
