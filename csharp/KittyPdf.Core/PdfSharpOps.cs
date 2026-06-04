using PdfSharp.Pdf;
using PdfSharp.Pdf.IO;
using PdfSharp.Pdf.Security;
using PdfSharpDoc = PdfSharp.Pdf.PdfDocument;

namespace KittyPdf.Core;

/// <summary>
/// Operations PDFium's public API can't write: encryption / decryption
/// and document metadata.  Implemented with PdfSharp on the document
/// bytes, independent of the PDFium layer.
/// </summary>
public static class PdfSharpOps
{
    public sealed record DocInfo(string Title, string Author, string Subject,
        string Keywords, string Creator);

    public static DocInfo GetInfo(byte[] src)
    {
        using var ms = new MemoryStream(src);
        using var doc = PdfReader.Open(ms, PdfDocumentOpenMode.Import);
        var i = doc.Info;
        return new DocInfo(i.Title ?? "", i.Author ?? "", i.Subject ?? "",
            i.Keywords ?? "", i.Creator ?? "");
    }

    public static byte[] SetInfo(byte[] src, DocInfo info)
    {
        using var inMs = new MemoryStream(src);
        using var doc = PdfReader.Open(inMs, PdfDocumentOpenMode.Modify);
        doc.Info.Title = info.Title;
        doc.Info.Author = info.Author;
        doc.Info.Subject = info.Subject;
        doc.Info.Keywords = info.Keywords;
        doc.Info.Creator = info.Creator;
        using var outMs = new MemoryStream();
        doc.Save(outMs);
        return outMs.ToArray();
    }

    public static void EncryptToFile(byte[] src, string outPath,
        string userPassword, string ownerPassword,
        bool allowPrint = true, bool allowCopy = true,
        bool allowModify = true, bool allowAnnotate = true)
    {
        using var inMs = new MemoryStream(src);
        using var doc = PdfReader.Open(inMs, PdfDocumentOpenMode.Modify);
        var s = doc.SecuritySettings;
        if (!string.IsNullOrEmpty(userPassword)) s.UserPassword = userPassword;
        s.OwnerPassword = string.IsNullOrEmpty(ownerPassword) ? userPassword : ownerPassword;
        s.PermitPrint = allowPrint;
        s.PermitFullQualityPrint = allowPrint;
        s.PermitExtractContent = allowCopy;
        s.PermitModifyDocument = allowModify;
        s.PermitAssembleDocument = allowModify;
        s.PermitAnnotations = allowAnnotate;
        s.PermitFormsFill = allowAnnotate;
        doc.SecurityHandler.SetEncryption(PdfDefaultEncryption.V5);   // AES-256
        doc.Save(outPath);
    }

    public static byte[] DecryptToBytes(byte[] src, string password)
    {
        using var inMs = new MemoryStream(src);
        using PdfSharpDoc doc = PdfReader.Open(inMs, password, PdfDocumentOpenMode.Modify);
        doc.SecurityHandler.SetEncryption(PdfDefaultEncryption.None);
        using var outMs = new MemoryStream();
        doc.Save(outMs);
        return outMs.ToArray();
    }
}
