"""Virtualised group headers and file rows for the duplicate review grid."""

from datetime import datetime
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GObject, Gtk, Pango

from .previews import PREVIEW_SIZE, PreviewCache, icon_path

COLUMN_WIDTHS = (30, 58, 124, 200, 68, 110, 180)
SIZE_UNITS = ('B', 'KB', 'MB', 'GB', 'TB')
BYTES_PER_UNIT = 1024
NANOSECONDS_PER_SECOND = 1_000_000_000


def display_text(value):
    return str(value).encode('utf-8', 'replace').decode('utf-8')


def format_size(size):
    value = float(size)
    for unit in SIZE_UNITS:
        if value < BYTES_PER_UNIT or unit == SIZE_UNITS[-1]:
            return f'{value:g} {unit}' if value.is_integer() else f'{value:.2f} {unit}'
        value /= BYTES_PER_UNIT


def text_cell(text, column, tooltip=None):
    label = Gtk.Label(label=display_text(text), xalign=0, ellipsize=Pango.EllipsizeMode.END)
    label.set_size_request(COLUMN_WIDTHS[column], -1)
    label.set_hexpand(column == len(COLUMN_WIDTHS) - 1)
    if tooltip:
        label.set_tooltip_text(display_text(tooltip))
    return label


class ListEntry(GObject.Object):
    def __init__(self, group, row=None):
        super().__init__()
        self.group = group
        self.row = row


class ResultsView(Gtk.Box):
    def __init__(self, selection_changed, keep_file, open_file):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.add_css_class('results')
        self.groups = []
        self.selection_changed = selection_changed
        self.keep_file = keep_file
        self.open_file = open_file
        self.previews = PreviewCache()
        self.store = Gio.ListStore.new(ListEntry)
        self.factory = Gtk.SignalListItemFactory()
        self.factory.connect('bind', self._bind)
        self.factory.connect('unbind', self._unbind)
        self.list = Gtk.ListView(model=Gtk.NoSelection.new(self.store), factory=self.factory)
        self.list.set_single_click_activate(False)
        self.list.set_vexpand(True)
        self.list.set_show_separators(False)
        header = Gtk.Box(spacing=4)
        header.add_css_class('table-header')
        for index, title in enumerate(('', '', 'Actions', 'File Name', 'Size', 'Modified', 'Path')):
            header.append(text_cell(title, index))
        table = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        table.append(header)
        vertical = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        vertical.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vertical.set_child(self.list)
        table.append(vertical)
        horizontal = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        horizontal.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        horizontal.set_child(table)
        self.append(horizontal)

    def set_groups(self, groups):
        self.groups = groups
        self.refresh()

    def refresh(self):
        entries = []
        for group in self.groups:
            entries.append(ListEntry(group))
            if group.expanded:
                entries.extend(ListEntry(group, row) for row in group.rows)
        self.store.splice(0, self.store.get_n_items(), entries)

    def _bind(self, factory, item):
        entry = item.get_item()
        item.set_child(self._group_header(entry.group) if entry.row is None else self._file_row(entry, item))

    def _unbind(self, factory, item):
        item.set_child(None)

    def _group_header(self, group):
        box = Gtk.Box(spacing=6)
        box.add_css_class('group-header')
        toggle = Gtk.Button(label=f'{"▾" if group.expanded else "▸"} Group {group.group_id}')
        toggle.set_size_request(108, -1)
        toggle.connect('clicked', lambda *_: self._toggle_group(group))
        box.append(toggle)
        for label, selected in (('Select', True), ('Deselect', False)):
            button = Gtk.Button(label=label)
            button.connect('clicked', lambda *_, selected=selected: self._select_group(group, selected))
            box.append(button)
        box.append(Gtk.Label(label=f'Same size and SHA-256 hash {group.kept.digest[:12].upper()}', xalign=0,
                             ellipsize=Pango.EllipsizeMode.END, hexpand=True))
        return box

    def _file_row(self, entry, item):
        row, group = entry.row, entry.group
        record = row.record
        box = Gtk.Box(spacing=4)
        box.add_css_class('file-row')
        box.add_css_class('selected-row' if row.selected else 'kept-row')
        checkbox = Gtk.CheckButton(active=row.selected, sensitive=not row.is_kept)
        checkbox.set_size_request(COLUMN_WIDTHS[0], -1)
        checkbox.set_tooltip_text('Kept file' if row.is_kept else 'Select duplicate for deletion')
        checkbox.connect('toggled', lambda widget: self._toggle_row(row, widget.get_active(), box))
        box.append(checkbox)
        picture = Gtk.Image.new_from_file(icon_path(record.path))
        picture.set_pixel_size(PREVIEW_SIZE)
        picture.set_size_request(COLUMN_WIDTHS[1], PREVIEW_SIZE)
        box.append(picture)

        def apply_preview(texture):
            if texture is not None and item.get_item() is entry and item.get_child() is box:
                picture.set_from_paintable(texture)

        self.previews.load(record, apply_preview)
        actions = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
        actions.set_size_request(COLUMN_WIDTHS[2], -1)
        keep = Gtk.Button(label='Keep', sensitive=not row.is_kept)
        keep.connect('clicked', lambda *_: self.keep_file(group, record.path))
        open_button = Gtk.Button(label='Open')
        open_button.set_tooltip_text('Open file location')
        open_button.connect('clicked', lambda *_: self.open_file(record.path))
        actions.append(keep)
        actions.append(open_button)
        box.append(actions)
        box.append(text_cell(Path(record.path).name, 3, record.path))
        box.append(text_cell(format_size(record.size), 4))
        modified = datetime.fromtimestamp(record.modified_ns / NANOSECONDS_PER_SECOND).strftime('%d/%m/%y %H:%M')
        box.append(text_cell(modified, 5))
        box.append(text_cell(record.path, 6, record.path))
        return box

    def _toggle_row(self, row, selected, box):
        row.selected = selected
        box.remove_css_class('selected-row')
        box.remove_css_class('kept-row')
        box.add_css_class('selected-row' if row.selected else 'kept-row')
        self.selection_changed()

    def _toggle_group(self, group):
        group.expanded = not group.expanded
        self.refresh()

    def _select_group(self, group, selected):
        group.set_selected(selected)
        self.refresh()
        self.selection_changed()

    def close(self):
        self.previews.close()
