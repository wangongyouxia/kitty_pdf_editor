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

    // Map an original font family (by PSName) to a bundled/system font with
    // FULL coverage, so edited text keeps the original look while rendering
    // newly-typed characters the embedded subset lacks.  `res`/`boldRes`
    // are embedded-resource font files (preferred); they also double as the
    // system-font filename to look up if the resource is somehow missing.
    // ORDER MATTERS: compound names are checked before short ones so a
    // greedy substring can't mis-match (e.g. "fang*song*" must not hit the
    // SimSun "song" key; "ya*hei*" must not hit the SimHei "hei" key).
    // First family whose any key is a substring of the normalised name wins.
    private static readonly (string[] keys, string res, string boldRes)[] FamilyMap =
    {
        (new[] { "yahei", "雅黑", "msyh", "微软雅黑", "dengxian", "等线" }, "msyh.ttc", "msyhbd.ttc"),
        (new[] { "fangsong", "simfang", "仿宋", "仿", "fang", "stfangsong" }, "simfang.ttf", "simfang.ttf"),
        (new[] { "kaiti", "simkai", "楷体", "楷", "kai", "stkaiti" }, "simkai.ttf", "simkai.ttf"),
        (new[] { "simhei", "heiti", "黑体", "黑", "hei", "stxihei" }, "simhei.ttf", "simhei.ttf"),
        (new[] { "simsun", "songti", "宋体", "宋", "song", "stsong", "mingliu", "newsongti" }, "simsun.ttc", "simsun.ttc"),
    };

    internal static string NormalizeFontName(string? name)
    {
        if (string.IsNullOrEmpty(name)) return "";
        string n = name;
        int plus = n.IndexOf('+');
        if (plus is >= 1 and <= 7) n = n[(plus + 1)..];   // strip "ABCDEF+" subset prefix
        return n.ToLowerInvariant().Replace(" ", "").Replace("-", "").Replace("_", "");
    }

    /// <summary>
    /// Family-match a PSName to a bundled font filename (or null for no
    /// match → caller falls back to YaHei/base-14).  Pure + testable.
    /// </summary>
    internal static string? MatchFamilyFile(string? familyName, bool bold)
    {
        string norm = NormalizeFontName(familyName);
        if (norm.Length == 0) return null;
        foreach (var (keys, res, boldRes) in FamilyMap)
            if (keys.Any(k => norm.Contains(NormalizeFontName(k))))
                return bold ? boldRes : res;
        return null;
    }

    private IntPtr LoadBundledOrSystem(string file)
    {
        var bytes = LoadEmbeddedFont("KittyPdf.Core.Fonts." + file);
        if (bytes != null) return GetCidFontFromBytes("res:" + file, bytes);
        string? path = FindSystemFont(file);
        return path != null ? GetCidFont(path) : IntPtr.Zero;
    }

    /// <summary>
    /// Resolve a font handle that fully covers <paramref name="text"/>, trying
    /// to match the original family from the bundled fonts; CJK falls back
    /// to bundled YaHei, Latin to base-14 (returns Zero → standard font).
    /// </summary>
    private IntPtr ResolveStyledFont(string? familyName, bool bold, string text)
    {
        var file = MatchFamilyFile(familyName, bold);
        if (file != null)
        {
            var h = LoadBundledOrSystem(file);
            if (h == IntPtr.Zero && bold)
            {
                var regular = MatchFamilyFile(familyName, false);
                if (regular != null) h = LoadBundledOrSystem(regular);
            }
            if (h != IntPtr.Zero) return h;
        }
        return HasNonLatin(text) ? ResolveCjkFont(bold) : IntPtr.Zero;
    }

    private void AddTextObjectAt(IntPtr page, string text, string? fontName,
        double sizePt, bool bold, uint r, uint g, uint b, uint a, FS_MATRIX matrix)
    {
        IntPtr font = ResolveStyledFont(fontName, bold, text);
        IntPtr nobj = font != IntPtr.Zero
            ? Pdfium.FPDFPageObj_CreateTextObj(_doc, font, (float)sizePt)
            : Pdfium.FPDFPageObj_NewTextObj(_doc, bold ? "Helvetica-Bold" : "Helvetica", (float)sizePt);
        if (nobj == IntPtr.Zero) return;
        Pdfium.FPDFText_SetText(nobj, text);
        Pdfium.FPDFPageObj_SetFillColor(nobj, r, g, b, a);
        Pdfium.FPDFPageObj_SetMatrix(nobj, matrix);
        Pdfium.FPDFPage_InsertObject(page, nobj);
    }

    /// <summary>
    /// Edit a text run.  Three strategies, in order of fidelity:
    ///   1. Every new char was already in the run → keep the EXACT embedded
    ///      font/weight (FPDFText_SetText on the same object).
    ///   2. Pure append (new = old + suffix) → leave the original object
    ///      completely untouched (font + weight perfectly preserved) and add
    ///      ONLY the suffix as a new run in a family-matched full font.
    ///   3. Otherwise → rebuild the whole run in a family-matched font,
    ///      re-applying the original matrix/colour (weight is best-effort).
    /// </summary>
    public void EditText(int pageIndex, int objectIndex, string newText, string oldText,
        string? fontName, double sizePt, bool bold)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
    {
        if (Pdfium.FPDFPageObj_GetType(obj) != Pdfium.FPDF_PAGEOBJ_TEXT) return;

        var oldSet = new HashSet<char>(oldText ?? "");
        bool subsetSafe = newText.All(c => oldSet.Contains(c));
        if (subsetSafe)
        {
            Pdfium.FPDFText_SetText(obj, newText);
            Pdfium.FPDFPage_GenerateContent(page);
            return;
        }

        Pdfium.FPDFPageObj_GetMatrix(obj, out var m);
        Pdfium.FPDFPageObj_GetBounds(obj, out float l, out float bot, out float right, out float top);
        if (!Pdfium.FPDFPageObj_GetFillColor(obj, out uint r, out uint g, out uint b, out uint a))
        { r = g = b = 0; a = 255; }

        if (!string.IsNullOrEmpty(oldText) && newText.StartsWith(oldText, StringComparison.Ordinal))
        {
            // Pure append: keep the original run, add only the suffix at its
            // right edge on the same baseline — original font/weight intact.
            string suffix = newText[oldText.Length..];
            var suffixMatrix = new FS_MATRIX { a = m.a, b = m.b, c = m.c, d = m.d, e = right, f = m.f };
            AddTextObjectAt(page, suffix, fontName, sizePt, bold, r, g, b, a, suffixMatrix);
            Pdfium.FPDFPage_GenerateContent(page);
            return;
        }

        // Full rebuild in a family-matched font.
        if (Pdfium.FPDFPage_RemoveObject(page, obj))
            Pdfium.FPDFPageObj_Destroy(obj);
        AddTextObjectAt(page, newText, fontName, sizePt, bold, r, g, b, a, m);
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
