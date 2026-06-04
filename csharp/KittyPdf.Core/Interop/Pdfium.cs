using System.Runtime.InteropServices;

namespace KittyPdf.Core.Interop;

/// <summary>
/// Raw P/Invoke surface for Google's PDFium (the PDF engine inside
/// Chrome).  We bind only what the editor needs.  All entry points use
/// the documented public C ABI from fpdfview.h / fpdf_edit.h /
/// fpdf_text.h / fpdf_save.h.
///
/// The native library is supplied by the bblanchon.PDFium.Win32 NuGet
/// package as <c>pdfium.dll</c>.
///
/// Why PDFium and not MuPDF: PDFium's FPDFEdit API lets us mutate the
/// *actual page objects* — move a text run with FPDFPageObj_Transform,
/// change its string with FPDFText_SetText, delete it with
/// FPDFPage_RemoveObject — all WITHOUT re-choosing a font.  The font
/// resource the object references is left untouched, so bold / italic /
/// the exact embedded face survive every edit.  That is the whole
/// reason for the rewrite.
/// </summary>
internal static unsafe class Pdfium
{
    private const string Dll = "pdfium";
    private const CallingConvention Conv = CallingConvention.Cdecl;

    // ---- Page object type codes (FPDFPageObj_GetType) ----
    public const int FPDF_PAGEOBJ_UNKNOWN = 0;
    public const int FPDF_PAGEOBJ_TEXT = 1;
    public const int FPDF_PAGEOBJ_PATH = 2;
    public const int FPDF_PAGEOBJ_IMAGE = 3;
    public const int FPDF_PAGEOBJ_SHADING = 4;
    public const int FPDF_PAGEOBJ_FORM = 5;

    // ---- Bitmap pixel formats (FPDFBitmap_CreateEx) ----
    public const int FPDFBitmap_Gray = 1;
    public const int FPDFBitmap_BGR = 2;
    public const int FPDFBitmap_BGRx = 3;
    public const int FPDFBitmap_BGRA = 4;

    // ---- Render flags (FPDF_RenderPageBitmap) ----
    public const int FPDF_ANNOT = 0x01;       // render annotations
    public const int FPDF_LCD_TEXT = 0x02;
    public const int FPDF_GRAYSCALE = 0x08;
    public const int FPDF_REVERSE_BYTE_ORDER = 0x10;

    // ---- Save flags (FPDF_SaveAsCopy) ----
    public const int FPDF_INCREMENTAL = 1;
    public const int FPDF_NO_INCREMENTAL = 2;
    public const int FPDF_REMOVE_SECURITY = 3;

    // ------------------------------------------------------------------
    // Library lifecycle
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDF_InitLibrary();

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDF_DestroyLibrary();

    // ------------------------------------------------------------------
    // Document creation (used by tests / blank-doc feature)
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDF_CreateNewDocument();

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFPage_New(IntPtr document, int page_index,
        double width, double height);

    // ------------------------------------------------------------------
    // Document
    // ------------------------------------------------------------------
    // Load from memory so Unicode file paths (Chinese filenames!) never
    // touch the ANSI-only FPDF_LoadDocument path.  data_buf must stay
    // alive for the document's whole lifetime.
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDF_LoadMemDocument(void* data_buf, int size,
        [MarshalAs(UnmanagedType.LPStr)] string? password);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDF_CloseDocument(IntPtr document);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern int FPDF_GetPageCount(IntPtr document);

    // ------------------------------------------------------------------
    // Page
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDF_LoadPage(IntPtr document, int page_index);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDF_ClosePage(IntPtr page);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern float FPDF_GetPageWidthF(IntPtr page);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern float FPDF_GetPageHeightF(IntPtr page);

    // ------------------------------------------------------------------
    // Bitmap + render
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFBitmap_CreateEx(int width, int height,
        int format, void* first_scan, int stride);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFBitmap_FillRect(IntPtr bitmap, int left, int top,
        int width, int height, uint color);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDF_RenderPageBitmap(IntPtr bitmap, IntPtr page,
        int start_x, int start_y, int size_x, int size_y, int rotate, int flags);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFBitmap_Destroy(IntPtr bitmap);

    // ------------------------------------------------------------------
    // Page objects (FPDFEdit)
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern int FPDFPage_CountObjects(IntPtr page);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFPage_GetObject(IntPtr page, int index);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern int FPDFPageObj_GetType(IntPtr page_object);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPageObj_GetBounds(IntPtr page_object,
        out float left, out float bottom, out float right, out float top);

    // The money method: apply an affine transform to a single object.
    // (1,0,0,1,dx,dy) = translate; preserves the font resource exactly.
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFPageObj_Transform(IntPtr page_object,
        double a, double b, double c, double d, double e, double f);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPageObj_GetMatrix(IntPtr page_object, out FS_MATRIX matrix);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPageObj_SetMatrix(IntPtr page_object, in FS_MATRIX matrix);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPageObj_GetFillColor(IntPtr page_object,
        out uint R, out uint G, out uint B, out uint A);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPageObj_SetFillColor(IntPtr page_object,
        uint R, uint G, uint B, uint A);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPage_RemoveObject(IntPtr page, IntPtr page_object);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFPageObj_Destroy(IntPtr page_object);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFPage_InsertObject(IntPtr page, IntPtr page_obj);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFPage_GenerateContent(IntPtr page);

    // ------------------------------------------------------------------
    // Text objects
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFPageObj_NewTextObj(IntPtr document,
        [MarshalAs(UnmanagedType.LPStr)] string font, float font_size);

    // text is UTF-16LE, NUL-terminated.
    [DllImport(Dll, CallingConvention = Conv, CharSet = CharSet.Unicode)]
    public static extern bool FPDFText_SetText(IntPtr text_object,
        [MarshalAs(UnmanagedType.LPWStr)] string text);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFTextObj_GetFontSize(IntPtr text, out float size);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFTextObj_GetFont(IntPtr text);

    // Returns number of UTF-16 code units written (incl. terminating NUL).
    // buffer is FPDF_WCHAR* (UTF-16LE).  Pass null buffer to query length.
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern uint FPDFTextObj_GetText(IntPtr text_object,
        IntPtr text_page, void* buffer, uint length);

    // ------------------------------------------------------------------
    // Font metadata — accurate style info straight from the engine.
    // No more guessing bold from PSName substrings.
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern uint FPDFFont_GetBaseFontName(IntPtr font, byte* buffer, uint length);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern uint FPDFFont_GetFamilyName(IntPtr font, byte* buffer, uint length);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern int FPDFFont_GetWeight(IntPtr font);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDFFont_GetItalicAngle(IntPtr font, out int angle);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern int FPDFFont_GetFlags(IntPtr font);

    // ------------------------------------------------------------------
    // Text page (needed by FPDFTextObj_GetText)
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern IntPtr FPDFText_LoadPage(IntPtr page);

    [DllImport(Dll, CallingConvention = Conv)]
    public static extern void FPDFText_ClosePage(IntPtr text_page);

    // ------------------------------------------------------------------
    // Save
    // ------------------------------------------------------------------
    [DllImport(Dll, CallingConvention = Conv)]
    public static extern bool FPDF_SaveAsCopy(IntPtr document, ref FPDF_FILEWRITE pFileWrite, uint flags);
}

[StructLayout(LayoutKind.Sequential)]
internal struct FS_MATRIX
{
    public float a, b, c, d, e, f;
}

[StructLayout(LayoutKind.Sequential)]
internal struct FPDF_FILEWRITE
{
    public int version;
    public IntPtr WriteBlock;   // int (*)(FPDF_FILEWRITE* pThis, const void* data, unsigned long size)
}
