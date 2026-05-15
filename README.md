# 🐱 Kitty PDF Editor

A desktop PDF viewer + editor built with **PyQt6** and **PyMuPDF**.
Single-file Windows executable, with full Chinese / English UI.

![cat icon](app/cat.png)

## Features

### View
- Open / save / save-as / new blank PDF, recent files
- Multi-page continuous viewer with **lazy rendering** (only visible
  pages are rasterised — opens 200-page docs instantly)
- Zoom in / out, fit width, fit page, full-screen
- Thumbnail panel with drag-and-drop reorder
- Outline / bookmarks (view + add / rename / remove)
- Search across the document with click-to-jump results

### Edit
- **Content Edit mode** (default when a document opens, Ctrl+E to
  toggle) — every text span and embedded image becomes a selectable
  element with resize handles
  - Click an element → select; click again → in-place inline edit
  - Drag to move · corner handles to resize · Del to delete
  - Right-side **Element Inspector** for text / font / size / colour
- Real content removal via redaction when moving / deleting (no
  ghost copies left behind)
- **Unicode font embedding** — CJK / Cyrillic / Greek text round-trips
  through edits (Microsoft YaHei / SimSun / Noto CJK / PingFang…)
- Bold / Italic actually picks the bold-face system font for CJK

### Annotations & drawing
Highlight, underline, strikethrough, squiggly, sticky notes,
free-text, rectangles, ellipses, lines, arrows, freehand ink,
eraser, **redaction** (mark + apply), link.

### Document ops
- Insert blank page · insert pages from another PDF
- Duplicate / delete / rotate / extract / crop pages
- Merge / split (every N pages or custom ranges)
- Add text or image **watermarks**
- Add page numbers (6 positions, custom format, custom start)
- Add header / footer
- **Optimize / compress** (garbage collect + deflate)
- **Encrypt** (AES-256, per-permission flags) / decrypt
- **Forms** — list, edit, flatten

### Signatures
- Hand-draw with the mouse, or load from PNG / JPG
- Click anywhere on a page to drop
- Auto-cropped to actual drawing area + 6 px margin

### Export
- Plain text · HTML · per-page images (PNG / JPG, custom DPI)
- Extract every embedded image

### Niceties
- 中文 ↔ English language toggle (top-right, live switch, persisted)
- Donate button bundling a payment QR
- Persistent recent-files list

---

## Run from source

```bash
pip install -r requirements.txt
python main.py
# optional: open a file directly
python main.py path/to/file.pdf
```

## Build a single-file Windows exe

```bash
python -m PyInstaller --noconfirm PDFEditor.spec
# → dist/PDFEditor.exe   (≈63 MB, self-contained)
```

The build script bundles:
- `app/cat.ico` (window / taskbar icon)
- `app/cat.png` (fallback)
- `app/donate.png` (donation QR shown by the ❤ button)

## Project layout

```
.
├── main.py                # entry point
├── PDFEditor.spec         # PyInstaller (--onefile) spec
├── requirements.txt
├── smoke_test.py          # 25+ automated checks
├── tools/
│   └── make_icon.py       # regenerates app/cat.ico
└── app/
    ├── main_window.py     # menus, toolbars, signals wiring
    ├── viewer.py          # PdfView (graphics scene, tools)
    ├── document.py        # PdfDocument wrapper around PyMuPDF
    ├── edit_mode.py       # WPS-like content-edit overlay
    ├── inspector.py       # right-side element property panel
    ├── text_edit.py       # span detection, replace/move helpers,
    │                      # Unicode-font autodetect
    ├── tools.py           # tool definitions + commit helpers
    ├── operations.py      # merge / split / watermark / encrypt / etc.
    ├── dialogs.py         # all common dialogs (signature, donate …)
    ├── panels.py          # thumbnails / outline / search
    ├── i18n.py            # zh ↔ en translation walker
    ├── cat.{ico,png}      # app icon
    └── donate.png         # QR shown by donate button
```

## Tested with

- Windows 11 + Python 3.12 + PyQt6 6.11 + PyMuPDF 1.27
- Source is cross-platform; rebuild the spec on macOS / Linux for
  those platforms.

## License

Released under the MIT License. Personal use, contributions welcome.
