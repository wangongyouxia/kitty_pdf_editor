using KittyPdf.Core.Interop;

namespace KittyPdf.Core;

/// <summary>
/// Shape / ink / image insertion.  Shapes are committed as content path
/// objects (not annotations): they render reliably without appearance
/// streams AND become first-class editable elements in edit mode.
/// All coordinates are PDF points, y-up.
/// </summary>
public sealed partial class PdfDocument
{
    public readonly record struct Rgba(double R, double G, double B, double A)
    {
        public uint Ri => (uint)Math.Clamp(Math.Round(R * 255), 0, 255);
        public uint Gi => (uint)Math.Clamp(Math.Round(G * 255), 0, 255);
        public uint Bi => (uint)Math.Clamp(Math.Round(B * 255), 0, 255);
        public uint Ai => (uint)Math.Clamp(Math.Round(A * 255), 0, 255);
    }

    private void OnPage(int pageIndex, Action<IntPtr> body)
    {
        var page = Pdfium.FPDF_LoadPage(_doc, pageIndex);
        if (page == IntPtr.Zero) return;
        try { body(page); }
        finally { Pdfium.FPDF_ClosePage(page); }
    }

    public void AddRect(int pageIndex, double x, double y, double w, double h,
        Rgba stroke, Rgba? fill, double width) => OnPage(pageIndex, page =>
    {
        var obj = Pdfium.FPDFPageObj_CreateNewRect((float)x, (float)y, (float)w, (float)h);
        if (obj == IntPtr.Zero) return;
        StyleShape(obj, stroke, fill, width);
        Pdfium.FPDFPage_InsertObject(page, obj);
        Pdfium.FPDFPage_GenerateContent(page);
    });

    public void AddHighlight(int pageIndex, double x, double y, double w, double h,
        (double r, double g, double b) color) =>
        AddRect(pageIndex, x, y, w, h, new Rgba(0, 0, 0, 0),
            new Rgba(color.r, color.g, color.b, 0.35), 0);

    public void AddLine(int pageIndex, double x1, double y1, double x2, double y2,
        Rgba stroke, double width, bool arrow) => OnPage(pageIndex, page =>
    {
        var obj = Pdfium.FPDFPageObj_CreateNewPath((float)x1, (float)y1);
        if (obj == IntPtr.Zero) return;
        Pdfium.FPDFPath_LineTo(obj, (float)x2, (float)y2);
        if (arrow)
        {
            double ang = Math.Atan2(y2 - y1, x2 - x1);
            double len = 10 + width * 2;
            double a1 = ang + Math.PI - Math.PI / 7, a2 = ang + Math.PI + Math.PI / 7;
            Pdfium.FPDFPath_MoveTo(obj, (float)x2, (float)y2);
            Pdfium.FPDFPath_LineTo(obj, (float)(x2 + len * Math.Cos(a1)), (float)(y2 + len * Math.Sin(a1)));
            Pdfium.FPDFPath_MoveTo(obj, (float)x2, (float)y2);
            Pdfium.FPDFPath_LineTo(obj, (float)(x2 + len * Math.Cos(a2)), (float)(y2 + len * Math.Sin(a2)));
        }
        StyleShape(obj, stroke, null, width);
        Pdfium.FPDFPage_InsertObject(page, obj);
        Pdfium.FPDFPage_GenerateContent(page);
    });

    public void AddEllipse(int pageIndex, double cx, double cy, double rx, double ry,
        Rgba stroke, Rgba? fill, double width) => OnPage(pageIndex, page =>
    {
        const double k = 0.5522847498307936; // 4/3 * (sqrt(2)-1)
        double ox = rx * k, oy = ry * k;
        var obj = Pdfium.FPDFPageObj_CreateNewPath((float)(cx + rx), (float)cy);
        if (obj == IntPtr.Zero) return;
        Pdfium.FPDFPath_BezierTo(obj, (float)(cx + rx), (float)(cy + oy), (float)(cx + ox), (float)(cy + ry), (float)cx, (float)(cy + ry));
        Pdfium.FPDFPath_BezierTo(obj, (float)(cx - ox), (float)(cy + ry), (float)(cx - rx), (float)(cy + oy), (float)(cx - rx), (float)cy);
        Pdfium.FPDFPath_BezierTo(obj, (float)(cx - rx), (float)(cy - oy), (float)(cx - ox), (float)(cy - ry), (float)cx, (float)(cy - ry));
        Pdfium.FPDFPath_BezierTo(obj, (float)(cx + ox), (float)(cy - ry), (float)(cx + rx), (float)(cy - oy), (float)(cx + rx), (float)cy);
        Pdfium.FPDFPath_Close(obj);
        StyleShape(obj, stroke, fill, width);
        Pdfium.FPDFPage_InsertObject(page, obj);
        Pdfium.FPDFPage_GenerateContent(page);
    });

    public void AddInk(int pageIndex, IReadOnlyList<IReadOnlyList<(double x, double y)>> strokes,
        Rgba stroke, double width) => OnPage(pageIndex, page =>
    {
        foreach (var s in strokes)
        {
            if (s.Count < 2) continue;
            var obj = Pdfium.FPDFPageObj_CreateNewPath((float)s[0].x, (float)s[0].y);
            if (obj == IntPtr.Zero) continue;
            for (int i = 1; i < s.Count; i++)
                Pdfium.FPDFPath_LineTo(obj, (float)s[i].x, (float)s[i].y);
            StyleShape(obj, stroke, null, width);
            Pdfium.FPDFPage_InsertObject(page, obj);
        }
        Pdfium.FPDFPage_GenerateContent(page);
    });

    private static void StyleShape(IntPtr obj, Rgba stroke, Rgba? fill, double width)
    {
        bool doStroke = width > 0 && stroke.A > 0;
        int fillMode = fill.HasValue && fill.Value.A > 0 ? 2 /*winding*/ : 0;
        if (fill.HasValue && fill.Value.A > 0)
            Pdfium.FPDFPageObj_SetFillColor(obj, fill.Value.Ri, fill.Value.Gi, fill.Value.Bi, fill.Value.Ai);
        if (doStroke)
        {
            Pdfium.FPDFPageObj_SetStrokeColor(obj, stroke.Ri, stroke.Gi, stroke.Bi, stroke.Ai);
            Pdfium.FPDFPageObj_SetStrokeWidth(obj, (float)width);
        }
        Pdfium.FPDFPath_SetDrawMode(obj, fillMode, doStroke);
    }

    /// <summary>
    /// Insert a 32-bit BGRA image. (xPt,yPt) is the bottom-left corner in
    /// PDF points; the image is scaled to (wPt,hPt).
    /// </summary>
    public unsafe void InsertImage(int pageIndex, byte[] bgra, int wPx, int hPx,
        double xPt, double yPt, double wPt, double hPt) => OnPage(pageIndex, page =>
    {
        fixed (byte* bp = bgra)
        {
            IntPtr bmp = Pdfium.FPDFBitmap_CreateEx(wPx, hPx, Pdfium.FPDFBitmap_BGRA, bp, wPx * 4);
            if (bmp == IntPtr.Zero) return;
            try
            {
                IntPtr obj = Pdfium.FPDFPageObj_NewImageObj(_doc);
                if (obj == IntPtr.Zero) return;
                Pdfium.FPDFImageObj_SetBitmap(null, 0, obj, bmp);
                // Image space is the unit square; map it to (wPt,hPt)@(xPt,yPt).
                Pdfium.FPDFPageObj_Transform(obj, wPt, 0, 0, hPt, xPt, yPt);
                Pdfium.FPDFPage_InsertObject(page, obj);
                Pdfium.FPDFPage_GenerateContent(page);
            }
            finally { Pdfium.FPDFBitmap_Destroy(bmp); }
        }
    });
}
