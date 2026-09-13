"""Application entry point for the Linux desktop."""

import sys
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk

from . import VERSION
from .storage import configure_logging
from .window import MainWindow

APPLICATION_ID = 'au.com.technification.CopyFinder'


def apply_style():
    settings = Gtk.Settings.get_default()
    settings.set_property('gtk-application-prefer-dark-theme', True)
    provider = Gtk.CssProvider()
    provider.load_from_path(str(Path(__file__).with_name('style.css')))
    Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class CopyFinderApplication(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APPLICATION_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.window = None

    def do_activate(self):
        if self.window is None:
            apply_style()
            self.window = MainWindow(self)
            self.window.present()
            self.window.show_compatibility_once()
        else:
            self.window.present()


def main():
    if '--version' in sys.argv:
        print(f'CopyFinder {VERSION} (Linux Mint)')
        return 0
    GLib.set_application_name('CopyFinder')
    GLib.set_prgname('copyfinder')
    configure_logging()
    return CopyFinderApplication().run(sys.argv)
