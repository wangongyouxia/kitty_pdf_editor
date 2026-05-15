# PyInstaller spec — single-file Windows build.
#
# Build:   pyinstaller --noconfirm PDFEditor.spec
# Output:  dist/PDFEditor.exe   (one self-contained file, ~100 MB)
#
# To produce builds for macOS / Linux, run the same command on those
# platforms; the source is platform-agnostic, only the binary container
# differs.

import os

block_cipher = None
HERE = os.path.dirname(os.path.abspath(SPEC))


def _maybe(rel):
    """Bundle a resource if present; silently skip otherwise."""
    p = os.path.join(HERE, rel)
    return (p, os.path.dirname(rel)) if os.path.isfile(p) else None


datas = [d for d in (
    _maybe(os.path.join("app", "cat.png")),
    _maybe(os.path.join("app", "cat.ico")),
    _maybe(os.path.join("app", "donate.png")),
) if d is not None]


a = Analysis(
    ['main.py'],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'app.main_window',
        'app.viewer',
        'app.document',
        'app.panels',
        'app.dialogs',
        'app.operations',
        'app.tools',
        'app.text_edit',
        'app.edit_mode',
        'app.inspector',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'unittest',
        'pydoc',
        'doctest',
        'distutils',
        'setuptools',
        'pip',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---- Single-file mode: bundle binaries + datas inside the exe.
icon_path = os.path.join(HERE, 'app', 'cat.ico')
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDFEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path if os.path.isfile(icon_path) else None,
)
