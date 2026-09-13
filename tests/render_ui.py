"""Export the application's GTK widget rendering for visual acceptance."""

import ctypes
import ctypes.util
import os
from pathlib import Path
import sys
import tempfile
import threading

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gsk', '4.0')
from gi.repository import GLib, Gsk, Gtk
from PIL import Image

from copyfinder.app import apply_style
from copyfinder.core import ScanOptions, scan
from copyfinder.window import MainWindow

RENDER_DELAY_MS = 600
RENDER_WIDTH = 830
RENDER_HEIGHT = 800


def export_widget(window, destination):
    width, height = window.get_width(), window.get_height()
    snapshot = Gtk.Snapshot()
    paintable = Gtk.WidgetPaintable.new(window)
    paintable.snapshot(snapshot, width, height)
    renderer = Gsk.Renderer.new_for_surface(window.get_surface())
    library = ctypes.CDLL(ctypes.util.find_library('gtk-4'))
    library.gtk_snapshot_to_node.argtypes = [ctypes.c_void_p]
    library.gtk_snapshot_to_node.restype = ctypes.c_void_p
    library.gsk_renderer_render_texture.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    library.gsk_renderer_render_texture.restype = ctypes.c_void_p
    library.gdk_texture_save_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    library.gdk_texture_save_to_png.restype = ctypes.c_int
    library.gsk_render_node_unref.argtypes = [ctypes.c_void_p]
    library.g_object_unref.argtypes = [ctypes.c_void_p]
    node = library.gtk_snapshot_to_node(hash(snapshot))
    if not node:
        raise RuntimeError('GTK produced no rendered widget node.')
    texture = library.gsk_renderer_render_texture(hash(renderer), node, None)
    try:
        if not texture or not library.gdk_texture_save_to_png(texture, os.fsencode(destination)):
            raise RuntimeError('GTK could not export the rendered texture.')
    finally:
        if texture:
            library.g_object_unref(texture)
        library.gsk_render_node_unref(node)
        renderer.unrealize()
    print(f'Rendered native GTK widgets: {destination} ({width} x {height})')


def render():
    output = PROJECT / 'docs/screenshots'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='copyfinder-visual-') as directory:
        os.environ['XDG_CONFIG_HOME'] = str(Path(directory) / 'config')
        fixtures = Path(directory) / 'sample-files'
        fixtures.mkdir()
        for filename, content in (('Meeting notes.txt', b'Team meeting notes.'),
                                  ('Meeting notes copy.txt', b'Team meeting notes.'),
                                  ('Budget.csv', b'Department,Amount\nResearch,1200\n'),
                                  ('Budget (1).csv', b'Department,Amount\nResearch,1200\n')):
            (fixtures / filename).write_bytes(content)
        for name in ('Blue square.png', 'Blue square copy.png'):
            Image.new('RGB', (120, 80), '#0094ff').save(fixtures / name)
        result = scan(str(fixtures), ScanOptions(), threading.Event(), lambda _: None)
        Gtk.init()
        app = Gtk.Application(application_id='au.com.technification.CopyFinder.Render')
        app.register(None)
        apply_style()
        window = MainWindow(app)
        window.set_default_size(RENDER_WIDTH, RENDER_HEIGHT)
        window.folder.set_text(str(fixtures))
        window.set_groups(result.groups)
        window.status.set_text('Scan complete.')
        window.present()
        loop = GLib.MainLoop()

        def first_frame():
            export_widget(window, output / 'review.png')
            window.settings_expander.set_expanded(True)
            GLib.timeout_add(RENDER_DELAY_MS, second_frame)
            return GLib.SOURCE_REMOVE

        def second_frame():
            export_widget(window, output / 'settings.png')
            window.destroy()
            loop.quit()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add(RENDER_DELAY_MS, first_frame)
        loop.run()


if __name__ == '__main__':
    render()
