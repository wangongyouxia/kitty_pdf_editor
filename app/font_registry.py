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


# Maps a *bundled file's basename* → tokens that, if present in the
# span font's PSName, identify the user as having intended that font.
# Order inside each list does not matter; the matcher looks for any
# substring hit (after normalising the span name).
_FONT_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "msyh.ttc":     (
        "microsoftyahei", "yahei", "msyh", "微软雅黑",
        "dengxian", "等线",                        # Win 10 default Chinese
        "microsoftjhenghei", "微软正黑",           # Trad. Chinese
    ),
    "msyhbd.ttc":   (
        "microsoftyaheibold", "yaheibold", "msyhbd",
        "dengxianbold", "microsoftjhengheibold",
        # Also accept regular-yahei aliases — pass 1 below requires
        # f.bold matching the span's bold-ness, so a regular YaHei span
        # still routes to msyh.ttc.  This entry lets a bold YaHei span
        # whose PSName lacks the literal word "bold" (because the
        # bold-ness comes from the span flags, not the font name) still
        # find the correct face.
        "microsoftyahei", "yahei", "msyh",
        "dengxian", "microsoftjhenghei",
    ),
    "msyhl.ttc":    ("microsoftyaheilight", "msyhl", "dengxianlight"),
    "simsun.ttc":   (
        "simsun", "songti", "宋体", "songtisc", "song",
        "adobesongstd", "stsongstd", "newsongti",
        "mingliu", "pmingliu", "细明体",            # Trad. equivalents
    ),
    "simsunb.ttf":  ("simsunb", "simsunbold"),
    "nsimsun.ttf":  ("nsimsun", "newsimsun"),
    "simhei.ttf":   (
        # NOTE: do NOT add a bare "hei" here — it would substring-match
        # "MicrosoftYaHei" and divert bold YaHei spans away from msyhbd.
        "simhei", "黑体", "heiti",
        "adobeheitistd", "stxihei", "xihei",
        "sourcehansans", "sourcehansansc",          # OK to alias — same style
    ),
    "simkai.ttf":   (
        "simkai", "kaiti", "楷体", "stkaiti", "kai",
        "adobekaitistd", "dfkai", "标楷体",
    ),
    "simfang.ttf":  (
        "simfang", "fangsong", "stfangsong", "仿宋", "fang",
        "adobefangsongstd", "fzfangsong",
    ),
    "simli.ttf":    ("simli", "lisu", "隶书"),
    "simyou.ttf":   ("simyou", "youyuan", "幼圆"),
    "stkaiti.ttf":  ("stkaiti", "kaiti"),
    "stsong.ttf":   ("stsong", "songti"),
    "stxihei.ttf":  ("stxihei", "xihei"),
}


def _maybe_decode_mojibake(name: str) -> str:
    """Some Chinese PDFs store a CJK PSName as raw UTF-8 bytes in a
    place where PyMuPDF / the PDF spec expect a PDFDocEncoding /
    Latin-1 string.  PyMuPDF then hands us back a string like
    'ä»¿å®\\x8b' — those are literally the UTF-8 bytes of '仿宋'
    re-decoded one-byte-per-char.  Detect that and recover the real
    name so our alias table can actually find it.
    """
    if not name:
        return name
    # If the string is already plain ASCII, nothing to fix.
    if not any(ord(c) > 0x7F for c in name):
        return name
    # If it already contains real CJK codepoints, nothing to fix.
    if any(ord(c) > 0xFF for c in name):
        return name
    # All chars are 0x80-0xFF — could be mojibake.  Try the round-trip.
    try:
        as_bytes = name.encode("latin-1")
        decoded = as_bytes.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name
    # Accept the fix only if the decoded result actually contains
    # CJK / fullwidth codepoints (so we don't mangle, say, a German
    # PSName with umlauts).
    for c in decoded:
        cp = ord(c)
        if 0x3000 <= cp <= 0x9FFF or 0xFF00 <= cp <= 0xFFEF:
            return decoded
    return name


def _normalise_font_name(name: str) -> str:
    """Drop the 'ABCDEF+' subset prefix PDF embedders prepend, recover
    UTF-8-as-Latin-1 mojibake'd CJK names, and collapse whitespace /
    dashes so 'Microsoft YaHei-Bold' becomes 'microsoftyaheibold'.
    """
    n = _maybe_decode_mojibake(name or "")
    if "+" in n:
        # PDF subset prefix: six uppercase letters + '+'.
        n = n.split("+", 1)[1]
    n = n.lower()
    for ch in (" ", "-", "_", ","):
        n = n.replace(ch, "")
    return n


# Tokens that strongly suggest a Chinese / Japanese / Korean font even
# when the exact PSName isn't in our alias table.  Used as a last-ditch
# fallback so the inspector doesn't default to Helvetica for spans that
# clearly want a CJK face.
_CJK_NAME_HINTS: tuple[str, ...] = (
    # Microsoft / Windows
    "yahei", "simsun", "simhei", "simkai", "simfang", "simli", "simyou",
    "simsunb", "nsimsun",
    "songti", "heiti", "kaiti", "fangsong", "youyuan", "lisu",
    "stxihei", "stsong", "stkaiti", "stzhongs", "stfangso", "stcaiyun",
    "stxinwei", "stxingkai", "sthupo",
    "mingliu", "pmingliu", "msjh", "msmincho", "msgothic",
    "dengxian", "deng",
    # macOS / iOS
    "pingfang", "hiraginosans", "hiraginomincho", "hiraginokaku",
    "applesdgothic", "applegothic",
    # Cross-platform / open source
    "noto", "sourcehansans", "sourcehanserif", "sourcehan", "shsans",
    "wenquanyi", "wqy", "droidsansfallback", "droidsans",
    # FangZheng / Founder (very common in Chinese publishing)
    "fz", "founder", "fangzheng", "方正",
    # Adobe stdfonts often seen in PDFs
    "adobesong", "adobeheiti", "adobekaiti", "adobefangsong",
    # Generic
    "han", "ming", "gothic", "mincho",
    "gb2312", "gb18030", "big5",
    "cjk",
)


def _looks_cjk(name: str, norm: str) -> bool:
    """Heuristic: does the original PSName clearly want a CJK font?"""
    if any(h in norm for h in _CJK_NAME_HINTS):
        return True
    # Any actual CJK codepoint in either the raw name OR the
    # mojibake-recovered name (covers PDFs whose PSName is real CJK
    # AND those whose PSName is mojibake'd UTF-8 of CJK).
    for source in ((name or ""), _maybe_decode_mojibake(name or "")):
        for c in source:
            cp = ord(c)
            if 0x3000 <= cp <= 0x9FFF or 0xFF00 <= cp <= 0xFFEF:
                return True
    return False


def _first_bundled_cjk(*, bold: bool) -> Optional[str]:
    """Return the key of the first bundled CJK font matching bold-ness,
    falling back to any bundled CJK face.
    """
    candidates = [f for f in list_fonts() if f.is_bundled and f.cjk and f.file]
    if not candidates:
        return None
    for f in candidates:
        if f.bold == bold:
            return f.key
    return candidates[0].key


def pick_default_for_span_aware(
    span_font_name: str, span_text: str = "",
    *, bold: bool, italic: bool,
) -> str:
    """Like `pick_default_for_span` but also looks at the actual text.

    When the original PSName doesn't match anything we know AND the
    text contains CJK characters, we escalate to a bundled CJK face
    rather than dropping to Helvetica.  Used by the Inspector so
    Chinese spans never show "Helvetica" as their default.
    """
    key = pick_default_for_span(span_font_name, bold=bold, italic=italic)
    fdef = get_font(key)
    # If the registry match landed on a base-14 face but the span's
    # actual text is CJK, switch to a bundled CJK font.
    if fdef and not fdef.is_bundled and span_text:
        if any(ord(c) > 0xFF for c in span_text):
            cjk_key = _first_bundled_cjk(bold=bold)
            if cjk_key:
                return cjk_key
    return key


def pick_default_for_span(span_font_name: str, *, bold: bool, italic: bool) -> str:
    """Map a detected span font name to a registry key.

    Priority order (style preservation beats family preservation —
    the user notices "my bold disappeared" much more than "my SimSun
    became YaHei"):

      Pass 1: same family AND matching bold-ness.  Perfect match.
      Pass 2: bold span + CJK heuristic AND no bold same-family file
              exists — escalate to any bundled bold CJK face so we
              keep the bold style.  (E.g. bold SimSun → msyhbd.ttc
              when we don't bundle simsunb.)
      Pass 3: same family, ignore bold-ness.  Family preserved but
              bold may be lost (only triggers for non-CJK or when
              no bundled bold CJK exists).
      Pass 4: CJK heuristic with the desired weight.
      Pass 5: base-14 family mapping with bold/italic suffixes.
    """
    norm = _normalise_font_name(span_font_name)

    bundled = [f for f in list_fonts() if f.is_bundled and f.file]

    def family_match(f: FontDef) -> bool:
        base = os.path.basename(f.file).lower()
        aliases = _FONT_NAME_ALIASES.get(base) or (os.path.splitext(base)[0],)
        return any(_normalise_font_name(a) in norm for a in aliases)

    # Pass 1: exact style + family.
    for f in bundled:
        if family_match(f) and f.bold == bold and f.italic == italic:
            return f.key

    # Pass 2: bold CJK escalation — preserve weight even if we have
    # to swap family.  Triggered when the user's span is bold + CJK
    # and the family-matching candidate above was regular-only.
    looks_cjk_span = _looks_cjk(span_font_name or "", norm)
    if bold and looks_cjk_span:
        cjk_bold = _first_bundled_cjk(bold=True)
        if cjk_bold:
            cjk_def = get_font(cjk_bold)
            if cjk_def and cjk_def.bold:
                return cjk_bold

    # Pass 3: same family, any style.
    for f in bundled:
        if family_match(f):
            return f.key

    # Pass 4: CJK heuristic with desired weight.
    if looks_cjk_span:
        cjk_key = _first_bundled_cjk(bold=bold)
        if cjk_key is not None:
            return cjk_key

    # Pass 5: base-14 fallback.
    mono = any(s in norm for s in ("mono", "courier", "consol", "code"))
    serif = (
        not mono and any(s in norm for s in (
            "serif", "times", "roman", "georgia", "garamond",
            "minion", "cambria", "palatino",
        ))
    )
    if mono:
        prefix, base_suf = "co", "ur"
    elif serif:
        prefix, base_suf = "ti", "ro"
    else:
        prefix, base_suf = "he", "lv"
    if bold and italic:
        suf = "bi"
    elif bold:
        suf = "bo"
    elif italic:
        suf = "it"
    else:
        suf = base_suf
    key = prefix + suf
    if get_font(key) is not None:
        return key
    return "helv"
