"""Native widget integration using disposable settings and filesystem fixtures."""

import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

GTK_WAIT_SECONDS = 10
GTK_POLL_SECONDS = 0.005
TEST_IMAGE_SIZE = (8, 6)


def iterate_until(predicate):
    from gi.repository import GLib
    deadline = time.monotonic() + GTK_WAIT_SECONDS
    context = GLib.MainContext.default()
    while not predicate() and time.monotonic() < deadline:
        context.iteration(False)
        time.sleep(GTK_POLL_SECONDS)
    return predicate()


def image_record(path):
    from PIL import Image
    from copyfinder.core import FileRecord
    Image.new('RGB', TEST_IMAGE_SIZE, 'red').save(path)
    snapshot = path.stat()
    return FileRecord(str(path), snapshot.st_size, snapshot.st_mtime_ns, snapshot.st_ctime_ns,
                      snapshot.st_dev, snapshot.st_ino, 'same-image')


class InterfaceTests(unittest.TestCase):
    def test_cached_image_previews_survive_native_row_rebinding(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from copyfinder.core import DuplicateGroup
        from copyfinder.previews import decode_preview
        from copyfinder.window import MainWindow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            records = tuple(image_record(Path(directory) / name) for name in ('first.png', 'second.png'))
            Gtk.init()
            app = Gtk.Application(application_id='au.com.technification.CopyFinder.TestPreviews')
            app.register(None)
            window = MainWindow(app)
            pictures = {}
            bound_rows = []

            def remember_picture(factory, item):
                entry = item.get_item()
                if entry.row is not None:
                    picture = item.get_child().get_first_child().get_next_sibling()
                    pictures[entry.row.record.path] = picture
                    bound_rows.append(picture)

            def previews_are_current():
                return len(pictures) == len(records) and all(
                    (texture := window.results.previews.cache.get((record.path, record.modified_ns, record.inode)))
                    is not None and pictures[record.path].get_paintable() == texture for record in records)

            window.results.factory.connect('bind', remember_picture)
            try:
                with patch('copyfinder.previews.decode_preview', wraps=decode_preview) as decoder:
                    window.set_groups([DuplicateGroup(1, records)])
                    window.present()
                    self.assertTrue(iterate_until(previews_are_current), 'Initial image previews did not render')
                    self.assertEqual(decoder.call_count, len(records))
                    for picture in pictures.values():
                        texture = picture.get_paintable()
                        self.assertEqual((texture.get_width(), texture.get_height()), TEST_IMAGE_SIZE)
                    original_bind_count = len(bound_rows)
                    window.select_all(False)
                    self.assertTrue(iterate_until(lambda: len(bound_rows) > original_bind_count),
                                    'Selection refresh did not rebind native GTK rows')
                    self.assertTrue(iterate_until(previews_are_current),
                                    'Rebound file rows did not receive the cached image textures')
                    self.assertEqual(decoder.call_count, len(records), 'Cached images were decoded again')
            finally:
                window.results.close()
                window.destroy()

    def test_cached_preview_delivery_is_deferred_and_cancelled_on_close(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib, Gtk
        from copyfinder.previews import PreviewCache
        Gtk.init()
        with tempfile.TemporaryDirectory() as directory:
            record = image_record(Path(directory) / 'preview.png')
            cache = PreviewCache()
            delivered = []
            try:
                cache.load(record, delivered.append)
                self.assertTrue(iterate_until(lambda: bool(delivered)), 'Initial preview was not decoded')
                self.assertIsNotNone(delivered[0])
                cached_deliveries = []
                cache.load(record, cached_deliveries.append)
                self.assertEqual(cached_deliveries, [], 'A cache hit called back during row construction')
                cache.close()
                context = GLib.MainContext.default()
                while context.pending():
                    context.iteration(False)
                self.assertEqual(cached_deliveries, [], 'A closed cache delivered a queued preview')
            finally:
                cache.close()

    def test_malformed_widget_settings_recover_and_preserve_original_file(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from copyfinder.core import ScanOptions
        from copyfinder.window import MainWindow

        class SettingsLoadWindow(MainWindow):
            def _build(self, options):
                self.loaded_options = options

            def update_actions(self, refresh_summary=True):
                pass

            def _destroyed(self, *_):
                pass

        invalid_settings = (
            {'scan': {'preferred_folder': None}},
            {'scan': {'preferred_folder': 12}},
            {'scan': {'keep_rule': None}},
            {'scan': {'skip_hidden': 'false'}},
            {'scan': {'skip_system': 0}},
            {'scan': {'excluded_extensions': 'tmp'}},
            {'scan': {'excluded_extensions': ['tmp', 3]}},
            {'scan': {'excluded_extensions': None}},
            {'scan': {'limit': True}},
            {'scan': {'workers': False}},
            {'scan': {'minimum_bytes': True}},
            {'scan': {'limit': '19'}},
            {'scan': {'workers': 2.5}},
            {'scan': []},
            {'last_folder': None},
            {'last_folder': ['folder']},
        )
        Gtk.init()
        app = Gtk.Application(application_id='au.com.technification.CopyFinder.TestInvalidSettings')
        app.register(None)
        for settings in invalid_settings:
            with self.subTest(settings=settings), tempfile.TemporaryDirectory() as directory, \
                    patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                path = Path(directory) / 'copyfinder/settings.json'
                path.parent.mkdir()
                original = json.dumps(settings).encode('utf-8')
                path.write_bytes(original)
                # Recovery must happen before values reach PyGObject setters.
                candidate = SettingsLoadWindow(app)
                try:
                    self.assertIsNotNone(candidate._load_error, 'Malformed settings escaped startup validation')
                    self.assertEqual(candidate.loaded_options, ScanOptions())
                finally:
                    candidate.destroy()
                window = MainWindow(app)
                try:
                    self.assertFalse(window._settings_writable)
                    self.assertEqual(window.settings_panel.options(), ScanOptions())
                    self.assertEqual(window.folder.get_text(), '')
                    with patch.object(window, 'show_message') as show_message:
                        window.show_compatibility_once()
                    self.assertIn('left unchanged', show_message.call_args.args[0])
                    window._save()
                    self.assertEqual(path.read_bytes(), original)
                finally:
                    window.results.close()
                    window.destroy()

    def test_valid_persisted_widget_settings_load_without_recovery(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from copyfinder.core import ScanOptions
        from copyfinder.window import MainWindow
        settings = {'last_folder': '/scan-folder', 'scan': {
            'limit': 19, 'workers': 3, 'keep_rule': 'Folder', 'preferred_folder': '/keep-folder',
            'minimum_bytes': 2048, 'skip_hidden': False, 'skip_system': True,
            'excluded_extensions': ['TMP', '.bak'],
        }}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            path = Path(directory) / 'copyfinder/settings.json'
            path.parent.mkdir()
            path.write_text(json.dumps(settings))
            Gtk.init()
            app = Gtk.Application(application_id='au.com.technification.CopyFinder.TestValidSettings')
            app.register(None)
            window = MainWindow(app)
            try:
                self.assertIsNone(window._load_error)
                self.assertTrue(window._settings_writable)
                self.assertEqual(window.folder.get_text(), settings['last_folder'])
                self.assertEqual(window.settings_panel.options(), ScanOptions(**settings['scan']))
                self.assertTrue(window.settings_panel.preferred.get_sensitive())
            finally:
                window.results.close()
                window.destroy()

    def test_completed_limited_scan_retains_stopped_for_review_summary(self):
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import GLib, Gtk
        from copyfinder.window import MainWindow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            fixture = Path(directory) / 'files'
            fixture.mkdir()
            for name in ('a.txt', 'b.txt', 'c.txt'):
                (fixture / name).write_text('abc')
            Gtk.init()
            app = Gtk.Application(application_id='au.com.technification.CopyFinder.TestScan')
            app.register(None)
            window = MainWindow(app)
            try:
                window.folder.set_text(str(fixture))
                window.settings_panel.limit.set_value(1)
                window.start_scan()
                self.assertFalse(window.scan_button.get_sensitive())
                deadline = time.monotonic() + 10
                context = GLib.MainContext.default()
                while window.busy and time.monotonic() < deadline:
                    context.iteration(False)
                    time.sleep(0.005)
                self.assertFalse(window.busy, 'Scan did not finish within ten seconds')
                self.assertTrue(window.scan_button.get_sensitive())
                self.assertTrue(window.summary.get_text().startswith('Scan stopped for review.'))
                self.assertEqual(len(window.groups[0].selected_records()), 1)
            finally:
                window.destroy()

    def test_native_settings_round_trip_and_preferred_folder_sensitivity(self):
        self.assertIsNotNone(importlib.util.find_spec('copyfinder.settings_panel'), 'GTK settings implementation is pending')
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from copyfinder.core import ScanOptions
        from copyfinder.settings_panel import SettingsPanel
        Gtk.init()
        panel = SettingsPanel(ScanOptions(limit=19, workers=3, excluded_extensions=('tmp',)), lambda: None)
        self.assertEqual(panel.options().limit, 19)
        self.assertEqual(panel.options().workers, 3)
        self.assertFalse(panel.preferred.get_sensitive())
        panel.keep_rule.set_selected(4)
        self.assertTrue(panel.preferred.get_sensitive())
        self.assertEqual(panel.options().keep_rule, 'Folder')

    def test_main_window_selection_keep_and_result_summary(self):
        self.assertIsNotNone(importlib.util.find_spec('copyfinder.window'), 'GTK window implementation is pending')
        import gi
        gi.require_version('Gtk', '4.0')
        from gi.repository import Gtk
        from copyfinder.core import DuplicateGroup, FileRecord
        from copyfinder.window import MainWindow
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
            Gtk.init()
            app = Gtk.Application(application_id='au.com.technification.CopyFinder.Test')
            app.register(None)
            window = MainWindow(app)
            records = tuple(FileRecord(str(Path(directory) / name), 3, 1, 1, 1, index + 1, 'abc')
                            for index, name in enumerate(('keep.txt', 'duplicate.txt')))
            window.set_groups([DuplicateGroup(1, records)])
            self.assertIn('1 duplicate files', window.summary.get_text())
            self.assertTrue(window.delete_button.get_sensitive())
            window.select_all(False)
            self.assertFalse(window.delete_button.get_sensitive())
            window.keep_file(window.groups[0], records[1].path)
            self.assertEqual(window.groups[0].kept.path, records[1].path)
            self.assertTrue(window.delete_button.get_sensitive())
            window.destroy()


if __name__ == '__main__':
    unittest.main()
