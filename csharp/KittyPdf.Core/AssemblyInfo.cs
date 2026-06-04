using System.Runtime.CompilerServices;

// The headless smoke test drives the raw PDFium interop to author a
// known test document (bold text), so it needs access to internals.
[assembly: InternalsVisibleTo("KittyPdf.Smoke")]
[assembly: InternalsVisibleTo("KittyPdf.Tests")]
