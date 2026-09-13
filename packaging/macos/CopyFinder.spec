# PyInstaller hooks collect GTK typelibs, schemas and their native libraries.
from pathlib import Path
from copyfinder import VERSION

project = Path(SPECPATH).resolve().parents[1]
analysis = Analysis(
    [str(project / 'packaging/macos/launcher.py')],
    pathex=[str(project)],
    datas=[(str(project / 'copyfinder/assets'), 'copyfinder/assets'),
           (str(project / 'copyfinder/style.css'), 'copyfinder')],
    hiddenimports=['gi.repository.Gtk', 'gi.repository.Gdk', 'gi.repository.GdkPixbuf',
                   'gi.repository.Pango', 'gi.repository.Gio', 'gi.repository.GLib',
                   'Foundation', 'AppKit', 'objc', 'PIL.Image', 'PIL.ImageOps'],
    hooksconfig={'gi': {'module-versions': {'Gtk': '4.0', 'Gdk': '4.0'},
                       'icons': ['hicolor', 'Adwaita']}},
    excludes=['tkinter'],
)
archive = PYZ(analysis.pure)
executable = EXE(archive, analysis.scripts, [], exclude_binaries=True,
                 name='CopyFinder', console=False, target_arch='x86_64',
                 codesign_identity=None)
collection = COLLECT(executable, analysis.binaries, analysis.datas, name='CopyFinder')
app = BUNDLE(collection, name='CopyFinder.app',
             icon=str(project / 'copyfinder/assets/copyfinder.png'),
             bundle_identifier='au.com.technification.CopyFinder',
             version=VERSION,
             info_plist={'LSMinimumSystemVersion': '10.15',
                         'NSHighResolutionCapable': True,
                         'NSPrincipalClass': 'NSApplication',
                         'CFBundleShortVersionString': VERSION})
