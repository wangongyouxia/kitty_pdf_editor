# Kitty PDF Editor (C# / .NET rewrite)

A WPF PDF editor built on **PDFium** (Chrome's PDF engine) with
**element-level editing**: moving, retyping, resizing, or deleting text
operates on the actual page object via `FPDFPageObj_*`, so the original
embedded font — weight, style, the exact face — is **never** re-selected
and therefore never lost. This was the core problem with the previous
PyMuPDF build (which deleted-and-reinserted text and had to guess a font
each time).

## Projects

| Project | What it is |
|---|---|
| `KittyPdf.Core` | Engine: P/Invoke to PDFium + PdfSharp. Open/render/edit/save, page ops, text/search, shapes/images, encryption/metadata. No UI. |
| `KittyPdf.App`  | WPF desktop app (the editor). |
| `KittyPdf.Smoke`| Headless test/inspect harness. |

## Features

- **Content editing** (edit mode, on by default): click to select, drag to
  move, 8 handles to resize, click-again / double-click to retype inline,
  Delete to remove. Right-hand inspector shows the engine-read font /
  weight / bold / size. Fonts are preserved on every edit.
- **Drawing tools**: rectangle, ellipse, line, arrow, highlight, freehand
  ink, text box — committed as editable content objects.
- **Images & signature**: insert an image; draw a signature (InkCanvas) and
  stamp it.
- **Pages**: insert blank, delete, duplicate, rotate, extract, reorder,
  merge, split.
- **Document**: text watermark, page numbers (CJK-capable), AES-256
  encryption / password removal, document properties (metadata).
- **Search**, text export, per-page PNG export.
- **CJK**: original embedded fonts render via PDFium; newly-inserted Chinese
  text uses bundled Microsoft YaHei (regular + bold), embedded in the exe.

## Build & run (needs .NET 8 SDK)

```pwsh
dotnet build  csharp/KittyPdf.sln -c Debug
dotnet run    --project csharp/KittyPdf.App     # launch the editor
dotnet run    --project csharp/KittyPdf.Smoke   # headless engine self-test
```

## Single-file Windows exe

```pwsh
dotnet publish csharp/KittyPdf.App/KittyPdf.App.csproj -c Release -r win-x64 `
  --self-contained true -p:PublishSingleFile=true `
  -p:IncludeNativeLibrariesForSelfExtract=true -p:EnableCompressionInSingleFile=true `
  -o csharp/publish
```

Produces a single ~95 MB `KittyPdfEditor.exe` (self-contained: .NET runtime
+ PDFium + bundled fonts; no install needed). Builds in seconds.
