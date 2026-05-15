"""Catalog of fonts available to the editor.

Three sources, merged into one list:
  1. PyMuPDF's built-in **base-14** fonts (Helvetica / Times / Courier
     plus their bold / italic variants).  Always available, no embed.
  2. **Bundled** TTF / TTC / OTF files shipped in `app/fonts/`.
     Picked up automatically by PyInstaller's `datas` glob in the spec.
  3. **User-extra** font files dropped in `<exe-dir>/app/fonts/`
     (or `<source>/app/fonts/` when running from source). Same folder,
     different physical location depending on whether we're frozen.

Each entry exposes a stable `key` (str id used in saved state) and a
human-friendly `display` (shown in the inspector dropdown).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class FontDef:
    key: str
    display: str
    base14_alias: Optional[str] = None  # if set, use PyMuPDF base-14
    file: Optional[str] = None          # else absolute path to .ttf/.ttc/.otf
    bold: bool = False
    italic: bool = False
    cjk: bool = False                   # supports CJK glyphs

    @property
    def is_bundled(self) -> bool:
        return self.file is not None


# Base-14 fonts always available via PyMuPDF.
_BASE14: tuple[FontDef, ...] = (
    FontDef("helv",  "Helvetica",              base14_alias="helv"),
    FontDef("hebo",  "Helvetica Bold",         base14_alias="hebo", bold=True),
    FontDef("heit",  "Helvetica Italic",       base14_alias="heit", italic=True),
    FontDef("hebi",  "Helvetica Bold Italic",  base14_alias="hebi", bold=True, italic=True),
    FontDef("tiro",  "Times Roman",            base14_alias="tiro"),
    FontDef("tibo",  "Times Bold",             base14_alias="tibo", bold=True),
    FontDef("tiit",  "Times Italic",           base14_alias="tiit", italic=True),
    FontDef("tibi",  "Times Bold Italic",      base14_alias="tibi", bold=True, italic=True),
    FontDef("cour",  "Courier",                base14_alias="cour"),
    FontDef("cobo",  "Courier Bold",           base14_alias="cobo", bold=True),
    FontDef("coit",  "Courier Italic",         base14_alias="coit", italic=True),
    FontDef("cobi",  "Courier Bold Italic",    base14_alias="cobi", bold=True, italic=True),
)


# Filename → metadata for known bundled fonts.  Anything not in this
# table still gets registered, just with a fallback display name.
_KNOWN_BUNDLED: dict[str, tuple[str, bool, bool, bool]] = {
    # filename (lower)            display name      bold  italic cjk
    "msyh.ttc":      ("微软雅黑",          False, False, True),
    "msyhl.ttc":     ("微软雅黑 Light",    False, False, True),
    "msyhbd.ttc":    ("微软雅黑 Bold",     True,  False, True),
    "simsun.ttc":    ("宋体",              False, False, True),
    "simsunb.ttf":   ("宋体 Bold",         True,  False, True),
    "nsimsun.ttf":   ("新宋体",            False, False, True),
    "simhei.ttf":    ("黑体",              True,  False, True),
    "simkai.ttf":    ("楷体",              False, False, True),
    "simfang.ttf":   ("仿宋",              False, False, True),
    "simli.ttf":     ("隶书",              False, False, True),
    "simyou.ttf":    ("幼圆",              False, False, True),
    "stkaiti.ttf":   ("华文楷体",          False, False, True),
    "stsong.ttf":    ("华文宋体",          False, False, True),
    "stxihei.ttf":   ("华文细黑",          False, False, True),
    "stzhongs.ttf":  ("华文中宋",          False, False, True),
    "stfangso.ttf":  ("华文仿宋",          False, False, True),
    "fzstk.ttf":     ("方正舒体",          False, False, True),
    "fzyaoti.ttf":   ("方正姚体",          False, False, True),
    # Latin extras users may drop in:
    "dejavusans.ttf":         ("DejaVu Sans",         False, False, False),
    "dejavusans-bold.ttf":    ("DejaVu Sans Bold",    True,  False, False),
    "dejavuserif.ttf":        ("DejaVu Serif",        False, False, False),
    "dejavuserif-bold.ttf":   ("DejaVu Serif Bold",   True,  False, False),
    "dejavusansmono.ttf":     ("DejaVu Sans Mono",    False, False, False),
    "notosanscjksc-regular.otf": ("Noto Sans CJK SC", False, False, True),
    "notosanscjksc-bold.otf":    ("Noto Sans CJK SC Bold", True, False, True),
    "notoserifcjksc-regular.otf": ("Noto Serif CJK SC", False, False, True),
}


def _bundled_fonts_dir() -> Optional[str]:
    """Path to the read-only bundled fonts directory.

    In a PyInstaller onefile build PyInstaller unpacks `app/fonts/`
    under `sys._MEIPASS/app/fonts`.  From source it's the project
    `app/fonts` folder.
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "app", "fonts")
        if os.path.isdir(p):
            return p
    here = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(here, "fonts")
    return p if os.path.isdir(p) else None


def _user_fonts_dir() -> Optional[str]:
    """Writable fonts directory the user can drop extra TTFs into.

    Frozen build → next to the exe; source build → same as bundled.
    """
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(exe_dir, "app", "fonts")
    return _bundled_fonts_dir()


_cache: Optional[list[FontDef]] = None


def _scan_dir(d: str, seen: set[str]) -> list[FontDef]:
    out: list[FontDef] = []
    if not d or not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        lower = name.lower()
        if not lower.endswith((".ttf", ".ttc", ".otf")):
            continue
        if lower in seen:
            continue
        seen.add(lower)
        path = os.path.join(d, name)
        if lower in _KNOWN_BUNDLED:
            display, bold, italic, cjk = _KNOWN_BUNDLED[lower]
        else:
            # Unknown file — derive display from filename
            display = os.path.splitext(name)[0]
            bold = "bold" in lower or "bd" in lower
            italic = "italic" in lower or "it" in lower or "oblique" in lower
            cjk = any(k in lower for k in (
                "cjk", "yh", "song", "hei", "kai", "fang", "noto", "han",
                "stxi", "stsong", "stkai",
            ))
        out.append(FontDef(
            key="file:" + lower,
            display=display,
            file=path,
            bold=bold,
            italic=italic,
            cjk=cjk,
        ))
    return out


def list_fonts(refresh: bool = False) -> list[FontDef]:
    """Return every font the editor can use, in display order."""
    global _cache
    if _cache is not None and not refresh:
        return _cache
    fonts: list[FontDef] = []
    fonts.extend(_BASE14)
    seen: set[str] = set()
    fonts.extend(_scan_dir(_bundled_fonts_dir() or "", seen))
    user_dir = _user_fonts_dir()
    if user_dir and user_dir != _bundled_fonts_dir():
        fonts.extend(_scan_dir(user_dir, seen))
    _cache = fonts
    return fonts


def get_font(key: str) -> Optional[FontDef]:
    for f in list_fonts():
        if f.key == key:
            return f
    return None


def default_key() -> str:
    return "helv"


def pick_default_for_span(span_font_name: str, *, bold: bool, italic: bool) -> str:
    """Best-effort: map a detected span font name to a registry key."""
    lower = (span_font_name or "").lower()
    # Try bundled match by filename hints.
    for f in list_fonts():
        if not f.is_bundled or not f.file:
            continue
        base = os.path.basename(f.file).lower()
        stem = os.path.splitext(base)[0]
        # Common substrings (yahei, simsun, simhei, kaiti, fangsong, song, hei…)
        if any(tok in lower for tok in (stem, base.split(".")[0])):
            if f.bold == bold:
                return f.key
    # Otherwise base-14 mapping like the legacy text_edit.map_to_base14.
    mono = any(s in lower for s in ("mono", "courier", "consol", "code"))
    serif = (
        not mono and any(s in lower for s in (
            "serif", "times", "roman", "georgia", "garamond",
            "minion", "cambria", "palatino", "song",
        ))
    )
    if mono:
        prefix = "co"
    elif serif:
        prefix = "ti"
    else:
        prefix = "he"
    base = "lv" if prefix == "he" else ("ro" if prefix == "ti" else "ur")
    if bold and italic:
        suf = "bi"
    elif bold:
        suf = "bo"
    elif italic:
        suf = "it"
    else:
        suf = base
    key = prefix + suf
    if get_font(key) is not None:
        return key
    return "helv"
