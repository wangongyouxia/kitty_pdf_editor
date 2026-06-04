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

    // PDF subset fonts are tagged "ABCDEF+RealName" (6 uppercase + '+').
    // Absence of that tag means a full font that already covers its charset,
    // so editing can keep it exactly instead of rebuilding.
    internal static bool IsSubsetFont(string? name)
    {
        if (string.IsNullOrEmpty(name) || name.Length < 7 || name[6] != '+') return false;
        for (int i = 0; i < 6; i++)
            if (name[i] < 'A' || name[i] > 'Z') return false;
        return true;
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

    // Match a Latin font family name to a Windows system font file (with
    // bold/italic variant).  Windows always ships these, so an edited Latin
    // run renders in the SAME-looking typeface (Times stays Times, etc.).
    internal static string? MatchLatinSystemFile(string norm, bool bold, bool italic)
    {
        if (norm.Length == 0) return null;
        (string[] keys, string reg, string bd, string it, string bi)[] fams =
        {
            (new[] { "timesnewroman", "times" }, "times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
            (new[] { "calibri" }, "calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
            (new[] { "cambria" }, "cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
            (new[] { "georgia" }, "georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
            (new[] { "verdana" }, "verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
            (new[] { "tahoma" }, "tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
            (new[] { "couriernew", "courier", "consolas", "consol" }, "cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
            (new[] { "arial", "helvetica", "arialmt", "segoeui", "segoe" }, "arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
        };
        foreach (var f in fams)
            if (f.keys.Any(norm.Contains))
                return bold && italic ? f.bi : bold ? f.bd : italic ? f.it : f.reg;

        bool mono = norm.Contains("mono") || norm.Contains("consol") || norm.Contains("code") || norm.Contains("courier");
        bool serif = norm.Contains("serif") || norm.Contains("roman") || norm.Contains("garamond")
                     || norm.Contains("minion") || norm.Contains("georgia") || norm.Contains("cambria");
        if (mono) return bold && italic ? "courbi.ttf" : bold ? "courbd.ttf" : italic ? "couri.ttf" : "cour.ttf";
        if (serif) return bold && italic ? "timesbi.ttf" : bold ? "timesbd.ttf" : italic ? "timesi.ttf" : "times.ttf";
        return bold && italic ? "arialbi.ttf" : bold ? "arialbd.ttf" : italic ? "ariali.ttf" : "arial.ttf";
    }

    /// <summary>
    /// Resolve a full font that covers <paramref name="text"/> while matching
    /// the original typeface as closely as possible:
    ///   1. named CJK family → bundled (SimSun / FangSong / …);
    ///   2. any CJK text with no family match → bundled YaHei;
    ///   3. Latin → the matching Windows system font (Times / Arial / …);
    ///   4. otherwise base-14 (Zero → caller uses a standard font).
    /// </summary>
    private IntPtr ResolveStyledFont(string? familyName, bool bold, bool italic, string text)
    {
        var cjkFile = MatchFamilyFile(familyName, bold);
        if (cjkFile != null)
        {
            var h = LoadBundledOrSystem(cjkFile);
            if (h == IntPtr.Zero && bold)
            {
                var regular = MatchFamilyFile(familyName, false);
                if (regular != null) h = LoadBundledOrSystem(regular);
            }
            if (h != IntPtr.Zero) return h;
        }
        if (HasNonLatin(text)) return ResolveCjkFont(bold);

        string norm = NormalizeFontName(familyName);
        string? latin = MatchLatinSystemFile(norm, bold, italic);
        if (latin != null)
        {
            string? p = FindSystemFont(latin)
                     ?? FindSystemFont(MatchLatinSystemFile(norm, bold, false) ?? "")
                     ?? FindSystemFont(MatchLatinSystemFile(norm, false, false) ?? "");
            if (p != null)
            {
                var h = GetCidFont(p);
                if (h != IntPtr.Zero) return h;
            }
        }
        return IntPtr.Zero;
    }

    private static string Base14Alias(string? fontName, bool bold, bool italic)
    {
        string norm = NormalizeFontName(fontName);
        bool mono = norm.Contains("mono") || norm.Contains("courier") || norm.Contains("consol");
        bool serif = norm.Contains("times") || norm.Contains("serif") || norm.Contains("roman")
                     || norm.Contains("georgia") || norm.Contains("garamond") || norm.Contains("cambria");
        if (mono) return bold && italic ? "Courier-BoldOblique" : bold ? "Courier-Bold" : italic ? "Courier-Oblique" : "Courier";
        if (serif) return bold && italic ? "Times-BoldItalic" : bold ? "Times-Bold" : italic ? "Times-Italic" : "Times-Roman";
        return bold && italic ? "Helvetica-BoldOblique" : bold ? "Helvetica-Bold" : italic ? "Helvetica-Oblique" : "Helvetica";
    }

    private void AddTextObjectAt(IntPtr page, string text, string? fontName,
        double sizePt, bool bold, bool italic, uint r, uint g, uint b, uint a, FS_MATRIX matrix)
    {
        IntPtr font = ResolveStyledFont(fontName, bold, italic, text);
        IntPtr nobj = font != IntPtr.Zero
            ? Pdfium.FPDFPageObj_CreateTextObj(_doc, font, (float)sizePt)
            : Pdfium.FPDFPageObj_NewTextObj(_doc, Base14Alias(fontName, bold, italic), (float)sizePt);
        if (nobj == IntPtr.Zero) return;
        Pdfium.FPDFText_SetText(nobj, text);
        Pdfium.FPDFPageObj_SetFillColor(nobj, r, g, b, a);
        Pdfium.FPDFPageObj_SetMatrix(nobj, matrix);
        Pdfium.FPDFPage_InsertObject(page, nobj);
    }

    /// <summary>
    /// Edit a text run, preserving the original font as much as physically
    /// possible:
    ///   1. New text needs no new glyph (all chars already in the run) OR the
    ///      font is NOT a subset (full font, covers everything) → keep the
    ///      EXACT embedded font via FPDFText_SetText.  One element, perfect.
    ///   2. Subset font + pure append → leave the original run COMPLETELY
    ///      untouched (its exact font + weight preserved) and add only the
    ///      appended characters as a small supplement run in the closest
    ///      family-matched full font.  (The embedded subset physically lacks
    ///      the new glyphs, and no thinner match may exist, so only the new
    ///      characters can differ — the original text never changes.)
    ///   3. Subset font + non-append edit → rebuild the whole run in a
    ///      family-matched font (best effort).
    /// </summary>
    public void EditText(int pageIndex, int objectIndex, string newText, string oldText,
        string? fontName, double sizePt, bool bold, bool italic)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
    {
        if (Pdfium.FPDFPageObj_GetType(obj) != Pdfium.FPDF_PAGEOBJ_TEXT) return;

        var oldSet = new HashSet<char>(oldText ?? "");
        bool subsetSafe = newText.All(c => oldSet.Contains(c));
        if (subsetSafe || !IsSubsetFont(fontName))
        {
            Pdfium.FPDFText_SetText(obj, newText);
            Pdfium.FPDFPage_GenerateContent(page);
            return;
        }

        Pdfium.FPDFPageObj_GetMatrix(obj, out var m);
        Pdfium.FPDFPageObj_GetBounds(obj, out float _, out float _, out float right, out float _);
        if (!Pdfium.FPDFPageObj_GetFillColor(obj, out uint r, out uint g, out uint b, out uint a))
        { r = g = b = 0; a = 255; }

        if (!string.IsNullOrEmpty(oldText) && newText.StartsWith(oldText, StringComparison.Ordinal))
        {
            // Preserve the original run exactly; supplement only the new tail.
            string suffix = newText[oldText.Length..];
            var suffixMatrix = new FS_MATRIX { a = m.a, b = m.b, c = m.c, d = m.d, e = right, f = m.f };
            AddTextObjectAt(page, suffix, fontName, sizePt, bold, italic, r, g, b, a, suffixMatrix);
            Pdfium.FPDFPage_GenerateContent(page);
            return;
        }

        // Non-append change to a subset run: rebuild the whole run.
        if (Pdfium.FPDFPage_RemoveObject(page, obj))
            Pdfium.FPDFPageObj_Destroy(obj);
        AddTextObjectAt(page, newText, fontName, sizePt, bold, italic, r, g, b, a, m);
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
