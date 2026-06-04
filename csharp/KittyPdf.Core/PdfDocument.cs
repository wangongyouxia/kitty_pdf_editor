using System.Runtime.InteropServices;
using System.Text;
using KittyPdf.Core.Interop;

namespace KittyPdf.Core;

/// <summary>
/// Managed wrapper over a PDFium document.  Owns the pinned file bytes
/// (PDFium reads lazily from them) and exposes element-level editing.
///
/// Threading: not thread-safe; drive from one thread (the UI thread is
/// fine — rendering a page is fast).
/// </summary>
public sealed class PdfDocument : IDisposable
{
    private static bool _libReady;
    private static readonly object _libLock = new();

    private IntPtr _doc;
    private GCHandle _pin;          // keeps the file bytes alive for PDFium
    private byte[]? _bytes;
    private bool _disposed;

    public int PageCount { get; private set; }

    private PdfDocument() { }

    private static void EnsureLibrary()
    {
        if (_libReady) return;
        lock (_libLock)
        {
            if (_libReady) return;
            Pdfium.FPDF_InitLibrary();
            _libReady = true;
        }
    }

    public static PdfDocument Open(string path, string? password = null)
        => Load(File.ReadAllBytes(path), password);

    public static unsafe PdfDocument Load(byte[] bytes, string? password = null)
    {
        EnsureLibrary();
        var doc = new PdfDocument { _bytes = bytes };
        doc._pin = GCHandle.Alloc(bytes, GCHandleType.Pinned);
        IntPtr handle;
        fixed (byte* p = bytes)
        {
            handle = Pdfium.FPDF_LoadMemDocument(p, bytes.Length, password);
        }
        if (handle == IntPtr.Zero)
        {
            doc._pin.Free();
            throw new InvalidOperationException(
                "PDFium failed to load the document (corrupt or wrong password).");
        }
        doc._doc = handle;
        doc.PageCount = Pdfium.FPDF_GetPageCount(handle);
        return doc;
    }

    // ------------------------------------------------------------------
    // Page geometry
    // ------------------------------------------------------------------
    public (double Width, double Height) GetPageSize(int pageIndex)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) throw new InvalidOperationException($"load page {pageIndex} failed");
        try
        {
            return (Pdfium.FPDF_GetPageWidthF(page), Pdfium.FPDF_GetPageHeightF(page));
        }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    // ------------------------------------------------------------------
    // Render a page to a 32-bit BGRA buffer at the given scale.
    // Returns (pixels, widthPx, heightPx, stride).  Top-down rows.
    // ------------------------------------------------------------------
    public unsafe RenderedPage RenderPage(int pageIndex, double scale,
        bool withAnnotations = true)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) throw new InvalidOperationException($"load page {pageIndex} failed");
        try
        {
            double wPt = Pdfium.FPDF_GetPageWidthF(page);
            double hPt = Pdfium.FPDF_GetPageHeightF(page);
            int wPx = Math.Max(1, (int)Math.Round(wPt * scale));
            int hPx = Math.Max(1, (int)Math.Round(hPt * scale));
            int stride = wPx * 4;
            var buffer = new byte[stride * hPx];
            fixed (byte* bp = buffer)
            {
                IntPtr bmp = Pdfium.FPDFBitmap_CreateEx(wPx, hPx, Pdfium.FPDFBitmap_BGRA,
                    bp, stride);
                if (bmp == IntPtr.Zero) throw new InvalidOperationException("bitmap alloc failed");
                try
                {
                    // White background.
                    Pdfium.FPDFBitmap_FillRect(bmp, 0, 0, wPx, hPx, 0xFFFFFFFF);
                    int flags = withAnnotations ? Pdfium.FPDF_ANNOT : 0;
                    Pdfium.FPDF_RenderPageBitmap(bmp, page, 0, 0, wPx, hPx, 0, flags);
                }
                finally { Pdfium.FPDFBitmap_Destroy(bmp); }
            }
            return new RenderedPage(buffer, wPx, hPx, stride, wPt, hPt);
        }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    // ------------------------------------------------------------------
    // Enumerate page objects with their attributes.
    // ------------------------------------------------------------------
    public unsafe IReadOnlyList<PdfElement> GetElements(int pageIndex)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) throw new InvalidOperationException($"load page {pageIndex} failed");
        IntPtr textPage = Pdfium.FPDFText_LoadPage(page);
        var list = new List<PdfElement>();
        try
        {
            int n = Pdfium.FPDFPage_CountObjects(page);
            for (int i = 0; i < n; i++)
            {
                IntPtr obj = Pdfium.FPDFPage_GetObject(page, i);
                if (obj == IntPtr.Zero) continue;
                int type = Pdfium.FPDFPageObj_GetType(obj);
                Pdfium.FPDFPageObj_GetBounds(obj, out float l, out float b, out float r, out float t);

                string? text = null, fontName = null;
                float fontSize = 0;
                int weight = 0;
                bool bold = false, italic = false;
                (double, double, double, double) color = (0, 0, 0, 1);

                if (type == Pdfium.FPDF_PAGEOBJ_TEXT)
                {
                    text = ReadObjectText(obj, textPage);
                    Pdfium.FPDFTextObj_GetFontSize(obj, out fontSize);
                    IntPtr font = Pdfium.FPDFTextObj_GetFont(obj);
                    if (font != IntPtr.Zero)
                    {
                        fontName = ReadFontName(font);
                        weight = Pdfium.FPDFFont_GetWeight(font);
                        int flags = Pdfium.FPDFFont_GetFlags(font);
                        // PDF font descriptor: bit 19 (0x40000) = ForceBold,
                        // bit 7 (0x40) = Italic.
                        bool forceBold = (flags & 0x40000) != 0;
                        bool italicFlag = (flags & 0x40) != 0;
                        // Name-based hints cover non-embedded base-14 faces
                        // (Helvetica-Bold etc.) where weight/flags are 0.
                        string nm = fontName ?? "";
                        bool nameBold = nm.Contains("bold", StringComparison.OrdinalIgnoreCase)
                            || nm.Contains("black", StringComparison.OrdinalIgnoreCase)
                            || nm.Contains("heavy", StringComparison.OrdinalIgnoreCase)
                            || nm.Contains("semibold", StringComparison.OrdinalIgnoreCase);
                        bool nameItalic = nm.Contains("italic", StringComparison.OrdinalIgnoreCase)
                            || nm.Contains("oblique", StringComparison.OrdinalIgnoreCase);
                        bold = weight >= 600 || forceBold || nameBold;
                        if (Pdfium.FPDFFont_GetItalicAngle(font, out int angle))
                            italic = angle != 0 || italicFlag || nameItalic;
                        else
                            italic = italicFlag || nameItalic;
                    }
                    if (Pdfium.FPDFPageObj_GetFillColor(obj, out uint cr, out uint cg, out uint cb, out uint ca))
                        color = (cr / 255.0, cg / 255.0, cb / 255.0, ca / 255.0);
                }

                list.Add(new PdfElement
                {
                    PageIndex = pageIndex,
                    Index = i,
                    Kind = (PdfElementKind)type,
                    Left = l, Bottom = b, Right = r, Top = t,
                    Text = text,
                    FontName = fontName,
                    FontSize = fontSize,
                    FontWeight = weight,
                    IsBold = bold,
                    IsItalic = italic,
                    Color = color,
                });
            }
        }
        finally
        {
            if (textPage != IntPtr.Zero) Pdfium.FPDFText_ClosePage(textPage);
            Pdfium.FPDF_ClosePage(page);
        }
        return list;
    }

    private static unsafe string? ReadObjectText(IntPtr obj, IntPtr textPage)
    {
        uint units = Pdfium.FPDFTextObj_GetText(obj, textPage, null, 0);
        if (units == 0) return null;
        var buf = new byte[units * 2];
        fixed (byte* bp = buf)
        {
            Pdfium.FPDFTextObj_GetText(obj, textPage, bp, units);
        }
        // UTF-16LE incl. trailing NUL.
        string s = Encoding.Unicode.GetString(buf);
        int nul = s.IndexOf('\0');
        if (nul >= 0) s = s[..nul];
        return s;
    }

    private static unsafe string? ReadFontName(IntPtr font)
    {
        uint len = Pdfium.FPDFFont_GetBaseFontName(font, null, 0);
        if (len == 0)
        {
            len = Pdfium.FPDFFont_GetFamilyName(font, null, 0);
            if (len == 0) return null;
            var fb = new byte[len];
            fixed (byte* p = fb) Pdfium.FPDFFont_GetFamilyName(font, p, len);
            return Encoding.ASCII.GetString(fb, 0, (int)len).TrimEnd('\0');
        }
        var buf = new byte[len];
        fixed (byte* p = buf) Pdfium.FPDFFont_GetBaseFontName(font, p, len);
        return Encoding.ASCII.GetString(buf, 0, (int)len).TrimEnd('\0');
    }

    // ------------------------------------------------------------------
    // Element edits.  Each takes the element's Index, re-finds the live
    // object, mutates it, and regenerates the page content stream.
    // The font resource is never re-selected, so style is preserved.
    // ------------------------------------------------------------------

    /// <summary>Translate an object by (dx, dy) in PDF points (y-up).</summary>
    public void MoveElement(int pageIndex, int objectIndex, double dx, double dy)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
        {
            Pdfium.FPDFPageObj_Transform(obj, 1, 0, 0, 1, dx, dy);
            Pdfium.FPDFPage_GenerateContent(page);
        });

    /// <summary>
    /// Set an object's affine matrix outright (used for move+scale during
    /// resize).  Matrix maps object space → page space.
    /// </summary>
    public void SetElementMatrix(int pageIndex, int objectIndex,
        double a, double b, double c, double d, double e, double f)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
        {
            var m = new FS_MATRIX { a = (float)a, b = (float)b, c = (float)c, d = (float)d, e = (float)e, f = (float)f };
            Pdfium.FPDFPageObj_SetMatrix(obj, m);
            Pdfium.FPDFPage_GenerateContent(page);
        });

    /// <summary>Replace a text object's string, keeping its font object.</summary>
    public void SetElementText(int pageIndex, int objectIndex, string newText)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
        {
            if (Pdfium.FPDFPageObj_GetType(obj) != Pdfium.FPDF_PAGEOBJ_TEXT) return;
            Pdfium.FPDFText_SetText(obj, newText);
            Pdfium.FPDFPage_GenerateContent(page);
        });

    /// <summary>Set a text object's fill colour (0..255 RGBA).</summary>
    public void SetElementColor(int pageIndex, int objectIndex, uint r, uint g, uint b, uint a)
        => WithObject(pageIndex, objectIndex, (page, obj) =>
        {
            Pdfium.FPDFPageObj_SetFillColor(obj, r, g, b, a);
            Pdfium.FPDFPage_GenerateContent(page);
        });

    /// <summary>Remove an object from the page entirely.</summary>
    public void DeleteElement(int pageIndex, int objectIndex)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) throw new InvalidOperationException($"load page {pageIndex} failed");
        try
        {
            IntPtr obj = Pdfium.FPDFPage_GetObject(page, objectIndex);
            if (obj == IntPtr.Zero) return;
            if (Pdfium.FPDFPage_RemoveObject(page, obj))
                Pdfium.FPDFPageObj_Destroy(obj);  // RemoveObject transfers ownership back to us
            Pdfium.FPDFPage_GenerateContent(page);
        }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    private void WithObject(int pageIndex, int objectIndex, Action<IntPtr, IntPtr> action)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) throw new InvalidOperationException($"load page {pageIndex} failed");
        try
        {
            IntPtr obj = Pdfium.FPDFPage_GetObject(page, objectIndex);
            if (obj == IntPtr.Zero) return;
            action(page, obj);
        }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    // ------------------------------------------------------------------
    // Save
    // ------------------------------------------------------------------
    public byte[] SaveToBytes()
    {
        var ms = new MemoryStream();

        // Keep the delegate rooted for the duration of the call.
        WriteBlockFn writer = (ignored, data, size) =>
        {
            var chunk = new byte[size];
            Marshal.Copy(data, chunk, 0, (int)size);
            ms.Write(chunk, 0, chunk.Length);
            return 1; // non-zero = success
        };
        var fw = new FPDF_FILEWRITE
        {
            version = 1,
            WriteBlock = Marshal.GetFunctionPointerForDelegate(writer),
        };
        bool ok = Pdfium.FPDF_SaveAsCopy(_doc, ref fw, Pdfium.FPDF_NO_INCREMENTAL);
        GC.KeepAlive(writer);
        if (!ok) throw new InvalidOperationException("FPDF_SaveAsCopy failed");
        return ms.ToArray();
    }

    public void SaveToFile(string path) => File.WriteAllBytes(path, SaveToBytes());

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    private delegate int WriteBlockFn(IntPtr pThis, IntPtr data, uint size);

    // ------------------------------------------------------------------
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true;
        if (_doc != IntPtr.Zero)
        {
            Pdfium.FPDF_CloseDocument(_doc);
            _doc = IntPtr.Zero;
        }
        if (_pin.IsAllocated) _pin.Free();
        _bytes = null;
    }
}

/// <summary>A rendered page bitmap: 32-bit BGRA, top-down rows.</summary>
public sealed record RenderedPage(byte[] Pixels, int WidthPx, int HeightPx, int Stride,
    double WidthPt, double HeightPt);
