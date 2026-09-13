"""Main-window workflow; filesystem operations execute outside the GTK loop."""

import logging
import os
import threading
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk, Pango

from . import VERSION
from .core import ScanCancelled, ScanOptions, scan
from .deletion import validate_and_trash
from .desktop import DesktopIntegrationError, compatibility_report, is_network_path, reveal_file, trash_file
from .reports import build_csv, build_json
from .results_view import ResultsView, display_text
from .review import ReviewGroup
from .settings_panel import SettingsPanel
from .storage import atomic_write, load_settings, save_settings

WINDOW_WIDTH = 830
WINDOW_HEIGHT = 800
PROGRESS_INTERVAL_MS = 100
SETTINGS_DELAY_MS = 350
FIRST_FAILURES_LIMIT = 10
LOGGER = logging.getLogger('copyfinder')
SETTING_TYPE_NAMES = {str: 'text', bool: 'a boolean', int: 'an integer', list: 'a list', dict: 'an object'}


def validate_setting_type(name, value, expected_type):
    # Exact types prevent JSON booleans from silently becoming integer controls.
    if type(value) is not expected_type:
        raise ValueError(f'Setting {name} must contain {SETTING_TYPE_NAMES[expected_type]}.')


def persisted_scan_options(settings):
    validate_setting_type('last_folder', settings.get('last_folder', ''), str)
    values = settings.get('scan', {})
    validate_setting_type('scan', values, dict)
    options = {}
    for option in fields(ScanOptions):
        if option.name not in values:
            continue
        value = values[option.name]
        setting_name = f'scan.{option.name}'
        if option.name == 'excluded_extensions':
            validate_setting_type(setting_name, value, list)
            for extension in value:
                validate_setting_type(f'{setting_name} entry', extension, str)
        else:
            validate_setting_type(setting_name, value, type(option.default))
        options[option.name] = value
    return ScanOptions(**options)


def action_button(label, callback, css_class=None):
    button = Gtk.Button(label=label)
    button.connect('clicked', lambda *_: callback())
    if css_class:
        button.add_css_class(css_class)
    return button


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, application):
        super().__init__(application=application, title=f'Technification CopyFinder {VERSION}',
                         default_width=WINDOW_WIDTH, default_height=WINDOW_HEIGHT)
        self.add_css_class('copyfinder')
        self.set_icon_name('copyfinder')
        self.groups = []
        self.busy = False
        self.cancel_event = threading.Event()
        self._settings_timer = None
        self._progress_timer = None
        self._progress = ''
        self._delete_progress = None
        self._pending_close = False
        self._delete_action = 0
        self._settings_writable = True
        self._load_error = None
        try:
            self.settings = load_settings()
            options = persisted_scan_options(self.settings)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            self.settings = {}
            options = ScanOptions()
            self._settings_writable = False
            self._load_error = str(error)
        self._build(options)
        self.connect('close-request', self._close_requested)
        self.connect('destroy', self._destroyed)
        self.update_actions()

    def _build(self, options):
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for name in ('top', 'bottom', 'start', 'end'):
            getattr(root, f'set_margin_{name}')(8)
        banner = Gtk.Picture.new_for_filename(str(Path(__file__).parent / 'assets/banner.png'))
        banner.set_content_fit(Gtk.ContentFit.CONTAIN)
        banner.set_can_shrink(True)
        banner.set_size_request(-1, 85)
        root.append(banner)
        self.folder = Gtk.Entry(placeholder_text='Choose or type a folder to scan', hexpand=True)
        self.folder.add_css_class('folder-entry')
        self.folder.set_text(str(self.settings.get('last_folder', '')))
        self.browse_button = action_button('Browse', self.browse)
        self.scan_button = action_button('Scan', self.start_scan, 'primary-action')
        self.cancel_button = action_button('Cancel', self.cancel_scan)
        browse_row = Gtk.Box(spacing=8)
        browse_row.add_css_class('panel')
        for control in (self.folder, self.browse_button, self.scan_button, self.cancel_button):
            browse_row.append(control)
        root.append(browse_row)
        self.settings_panel = SettingsPanel(options, self.schedule_save)
        self.settings_expander = Gtk.Expander(label='Scan Settings')
        self.settings_expander.add_css_class('settings-expander')
        self.settings_expander.set_child(self.settings_panel)
        root.append(self.settings_expander)
        summary_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        summary_panel.add_css_class('panel')
        self.progress_bar = Gtk.ProgressBar(show_text=False)
        self.summary = Gtk.Label(label='No scan run yet.', xalign=1, wrap=True)
        self.summary.add_css_class('accent')
        summary_panel.append(self.progress_bar)
        summary_panel.append(self.summary)
        root.append(summary_panel)
        self.results = ResultsView(self.update_actions, self.keep_file, self.open_file)
        root.append(self.results)
        self.status = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
        self.status.add_css_class('accent')
        self.export_button = action_button('Export report', self.export_report)
        self.select_button = action_button('Select duplicates', lambda: self.select_all(True))
        self.deselect_button = action_button('Deselect all', lambda: self.select_all(False))
        self.delete_button = action_button('Delete Duplicates', self.confirm_delete, 'danger-action')
        footer = Gtk.Box(spacing=6)
        footer.add_css_class('panel')
        for control in (self.status, self.export_button, self.select_button, self.deselect_button, self.delete_button):
            footer.append(control)
        root.append(footer)
        self.set_child(root)
        self.folder.connect('changed', lambda *_: self.schedule_save())

    def set_groups(self, groups):
        self.groups = [ReviewGroup(group.group_id, group.files) for group in groups]
        self.results.set_groups(self.groups)
        self.update_actions()

    def update_actions(self, refresh_summary=True):
        duplicates = sum(len(group.rows) - 1 for group in self.groups)
        selected = sum(len(group.selected_records()) for group in self.groups)
        if refresh_summary and self.groups and not self.busy:
            self.summary.set_text(f'{len(self.groups):,} duplicate groups, {duplicates:,} duplicate files, {selected:,} selected.')
        self.browse_button.set_sensitive(not self.busy)
        self.folder.set_sensitive(not self.busy)
        self.scan_button.set_sensitive(not self.busy)
        self.cancel_button.set_sensitive(self.busy and self._delete_progress is None)
        self.settings_panel.set_sensitive(not self.busy)
        self.results.set_sensitive(not self.busy)
        self.export_button.set_sensitive(bool(self.groups) and not self.busy)
        self.select_button.set_sensitive(duplicates > 0 and not self.busy)
        self.deselect_button.set_sensitive(selected > 0 and not self.busy)
        self.delete_button.set_sensitive(selected > 0 and not self.busy)

    def schedule_save(self):
        if self._settings_timer is not None:
            GLib.source_remove(self._settings_timer)
        self._settings_timer = GLib.timeout_add(SETTINGS_DELAY_MS, self._save)

    def _save(self):
        self._settings_timer = None
        if self._settings_writable:
            self.settings['last_folder'] = self.folder.get_text()
            self.settings['scan'] = asdict(self.settings_panel.options())
            try:
                save_settings(self.settings)
            except OSError as error:
                self.status.set_text(f'Settings were not saved: {error}')
                LOGGER.warning('Settings write failed: %s', error)
        return GLib.SOURCE_REMOVE

    def browse(self):
        dialog = Gtk.FileDialog(title='Choose a folder to scan')
        current = self.folder.get_text()
        if os.path.isdir(current):
            dialog.set_initial_folder(Gio.File.new_for_path(current))
        dialog.select_folder(self, None, self._folder_chosen)

    def _folder_chosen(self, dialog, result):
        try:
            folder = dialog.select_folder_finish(result)
            path = folder.get_path()
            if path is None:
                self.show_message('Choose a locally mounted folder. Mount network storage in the file manager first.')
                return
            self.folder.set_text(path)
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.show_message(f'Folder browser failed: {error.message}')

    def start_scan(self):
        folder = self.folder.get_text()
        options = self.settings_panel.options()
        if not os.path.isdir(folder):
            self.show_message('Choose an existing folder before scanning.')
            return
        if options.keep_rule == 'Folder' and not os.path.isdir(options.preferred_folder):
            self.show_message('Choose an existing preferred folder before scanning with the Folder keep rule.')
            return
        self._save()
        self.set_groups([])
        self._delete_action = 0
        self.summary.set_text('Scanning...')
        self.cancel_event = threading.Event()
        self._run_background(lambda: scan(folder, options, self.cancel_event, self._set_progress), self._scan_complete)

    def _set_progress(self, text):
        self._progress = text

    def _scan_complete(self, result):
        self.set_groups(result.groups)
        prefix = 'Scan stopped for review.' if result.limit_reached else 'Scan complete.'
        if self.groups:
            self.summary.set_text(f'{prefix} {self.summary.get_text()}')
        else:
            self.summary.set_text('No duplicate files found.')
        skipped = f' {result.skipped_files:,} skipped.' if result.skipped_files else ''
        self.status.set_text(f'{prefix} {result.scanned_files:,} files inspected.{skipped}')

    def cancel_scan(self):
        self.cancel_event.set()
        self.status.set_text('Canceling scan...')

    def _run_background(self, work, completed):
        self.busy = True
        self._progress = ''
        self.update_actions()
        self._progress_timer = GLib.timeout_add(PROGRESS_INTERVAL_MS, self._tick)

        def run():
            try:
                result = work()
            except Exception as error:
                GLib.idle_add(self._background_finished, completed, None, error)
            else:
                GLib.idle_add(self._background_finished, completed, result, None)

        threading.Thread(target=run, name='copyfinder-operation', daemon=True).start()

    def _tick(self):
        self.status.set_text(display_text(self._progress))
        if self._delete_progress is None:
            self.progress_bar.pulse()
        else:
            self._delete_label.set_text(display_text(self._progress))
            self._delete_bar.set_fraction(self._delete_progress[0] / max(1, self._delete_progress[1]))
        return GLib.SOURCE_CONTINUE

    def _background_finished(self, completed, result, error):
        if self._progress_timer is not None:
            GLib.source_remove(self._progress_timer)
            self._progress_timer = None
        self.busy = False
        self.progress_bar.set_fraction(0)
        self.update_actions()
        if error is None:
            completed(result)
        elif isinstance(error, ScanCancelled):
            self.summary.set_text('Scan canceled.')
            self.status.set_text('')
        else:
            LOGGER.error('Operation failed: %s', error)
            if self._delete_progress is not None:
                self._delete_dialog.destroy()
                self._delete_progress = None
            self.summary.set_text('Operation failed.')
            self.show_message(str(error))
        self.update_actions(refresh_summary=False)
        if self._pending_close:
            self.close()
        return GLib.SOURCE_REMOVE

    def select_all(self, selected):
        for group in self.groups:
            group.set_selected(selected)
        self.results.refresh()
        self.update_actions()

    def keep_file(self, group, path):
        group.keep(path)
        self.results.refresh()
        self.update_actions()
        self.status.set_text(f'Keep file changed: {display_text(path)}')

    def open_file(self, path):
        try:
            reveal_file(path)
        except (OSError, GLib.Error, DesktopIntegrationError) as error:
            self.show_message(f'Could not open file location: {error}')

    def confirm_delete(self):
        candidates = [(group, record, group.kept) for group in self.groups for record in group.selected_records()]
        if not candidates or self.busy:
            return
        network_count = sum(is_network_path(record.path) for _, record, _ in candidates)
        detail = (f'{len(candidates):,} selected duplicate file(s) will be validated against the kept file before moving to Trash. '
                  'One file in each group is kept. Files that cannot be moved to Trash will be left in place.')
        if network_count:
            detail += f'\n\n{network_count:,} selected file(s) are on network storage. Trash may be unavailable.'
        dialog = Gtk.AlertDialog(message='Delete selected duplicates?', detail=detail,
                                 buttons=['Delete Duplicates', 'Cancel'], default_button=1, cancel_button=1)
        dialog.choose(self, None, self._delete_confirmed, (candidates, network_count))

    def _delete_confirmed(self, dialog, result, context):
        try:
            choice = dialog.choose_finish(result)
        except GLib.Error:
            return
        if choice != 0:
            return
        candidates, network_count = context
        self._delete_action += 1
        self._delete_progress = (0, len(candidates))
        self._delete_dialog = Gtk.Window(title='Deleting duplicates', transient_for=self, modal=True,
                                         default_width=460, deletable=False)
        contents = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        for side in ('top', 'bottom', 'start', 'end'):
            getattr(contents, f'set_margin_{side}')(20)
        contents.append(Gtk.Label(label=f'{len(candidates):,} selected duplicate file(s)', xalign=0))
        self._delete_label = Gtk.Label(label='Preparing...', ellipsize=Pango.EllipsizeMode.MIDDLE)
        self._delete_bar = Gtk.ProgressBar()
        contents.append(self._delete_label)
        contents.append(self._delete_bar)
        self._delete_dialog.set_child(contents)
        self._delete_dialog.present()

        def remove_files():
            moved, failures = [], []
            for index, (group, record, kept) in enumerate(candidates):
                self._progress = Path(record.path).name
                LOGGER.info('Trash action %s validating %r against %r', self._delete_action, record.path, kept.path)
                try:
                    validate_and_trash(record, kept, trash_file)
                    moved.append((group, record.path))
                    LOGGER.info('Moved to Trash: %r', record.path)
                except Exception as error:
                    failures.append(f'{record.path}: {error}')
                    LOGGER.warning('Trash rejected: %r: %s', record.path, error)
                self._delete_progress = (index + 1, len(candidates))
            return moved, failures, network_count

        self._run_background(remove_files, self._delete_complete)

    def _delete_complete(self, result):
        self._delete_dialog.destroy()
        self._delete_progress = None
        moved, failures, network_count = result
        for group, path in moved:
            group.remove(path)
        self.groups = [group for group in self.groups if group.has_duplicates]
        self.results.set_groups(self.groups)
        self.summary.set_text(f'{len(moved):,} file(s) moved to Trash.')
        self.status.set_text(f'{len(failures):,} file(s) could not be moved.' if failures else 'Delete complete.')
        message = (f'Delete action: {self._delete_action}\nFiles moved: {len(moved):,}\nFailed files: {len(failures):,}'
                   f'\nNetwork-drive files: {network_count:,}\n\nMoved files can be restored using the file manager’s Trash.')
        if failures:
            message += '\n\nFirst failures:\n' + '\n'.join(failures[:FIRST_FAILURES_LIMIT])
        self.show_message(message)

    def export_report(self):
        dialog = Gtk.FileDialog(title='Export report', initial_name=f'CopyFinder-report-{datetime.now():%Y%m%d-%H%M%S}.csv')
        filters = Gio.ListStore.new(Gtk.FileFilter)
        for name, suffix in (('CSV report', 'csv'), ('JSON report', 'json')):
            file_filter = Gtk.FileFilter(name=name)
            file_filter.add_suffix(suffix)
            filters.append(file_filter)
        dialog.set_filters(filters)
        dialog.save(self, None, self._export_chosen)

    def _export_chosen(self, dialog, result):
        try:
            file = dialog.save_finish(result)
            path = file.get_path()
            if path is None:
                self.show_message('Choose a locally mounted destination for the report.')
                return
            builder = build_json if Path(path).suffix.lower() == '.json' else build_csv
            atomic_write(path, builder(self.groups, is_network_path))
            self.status.set_text(f'Report exported: {display_text(path)}')
        except GLib.Error as error:
            if not error.matches(Gtk.dialog_error_quark(), Gtk.DialogError.DISMISSED):
                self.show_message(f'Export failed: {error.message}')
        except (OSError, ValueError) as error:
            self.show_message(f'Export failed: {error}')

    def show_message(self, message):
        Gtk.AlertDialog(message='CopyFinder', detail=display_text(message)).show(self)

    def show_compatibility_once(self):
        if self._load_error:
            self.show_message(f'Settings could not be loaded and have been left unchanged.\n\n{self._load_error}')
        elif self.settings.get('compatibility_version') != VERSION:
            self.show_message(compatibility_report())
            self.settings['compatibility_version'] = VERSION
            self._save()

    def _close_requested(self, *_):
        if self.busy:
            self._pending_close = True
            self.cancel_event.set()
            return True
        self._save()
        return False

    def _destroyed(self, *_):
        if self._settings_timer is not None:
            GLib.source_remove(self._settings_timer)
        self.results.close()
