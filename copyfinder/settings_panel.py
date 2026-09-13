"""The reference scan controls expressed as native GTK widgets."""

import re

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from .core import ScanOptions

KEEP_RULES = ('Original', 'Shortest name', 'Oldest file', 'Newest file', 'Folder', 'Highest Resolution')
BYTES_PER_KILOBYTE = 1024
MAXIMUM_LIMIT = 10_000
MAXIMUM_WORKERS = 16


def labelled_control(label, control):
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
    box.append(Gtk.Label(label=label, xalign=0))
    box.append(control)
    return box


def number_control(value, minimum, maximum, width):
    control = Gtk.SpinButton.new_with_range(minimum, maximum, 1)
    control.set_value(value)
    control.set_width_chars(width)
    control.set_numeric(True)
    return control


class SettingsPanel(Gtk.Box):
    def __init__(self, options, changed):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.add_css_class('settings-panel')
        self._changed = changed
        self.keep_rule = Gtk.DropDown.new_from_strings(KEEP_RULES)
        self.keep_rule.set_selected(KEEP_RULES.index(options.keep_rule))
        self.preferred = Gtk.Entry(placeholder_text='Used only by Prefer folder', width_chars=25)
        self.preferred.set_text(options.preferred_folder)
        self.preferred.set_sensitive(options.keep_rule == 'Folder')
        self.workers = number_control(options.workers, 1, MAXIMUM_WORKERS, 2)
        self.limit = number_control(options.limit, 1, MAXIMUM_LIMIT, 5)
        self.minimum = number_control(options.minimum_bytes / BYTES_PER_KILOBYTE, 0, 1_000_000_000, 5)
        self.exclude = Gtk.Entry(placeholder_text='tmp, bak, log', width_chars=15)
        self.exclude.set_text(', '.join(options.excluded_extensions))
        self.hidden = Gtk.CheckButton(label='Skip hidden files', active=options.skip_hidden)
        self.hidden.set_tooltip_text('Skip dotfiles and hidden directories.')
        self.system = Gtk.CheckButton(label='Skip system files', active=options.skip_system)
        self.system.set_tooltip_text('Skip /dev, /proc, /sys and /run. Links and special files are always excluded.')
        for controls in (
            [('Keep', self.keep_rule), ('Folder', self.preferred), ('Workers', self.workers)],
            [('Limit', self.limit), ('Min KB', self.minimum), ('Exclude', self.exclude)],
        ):
            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=4,
                               min_children_per_line=1, max_children_per_line=3, homogeneous=False)
            for label, control in controls:
                flow.append(labelled_control(label, control))
            self.append(flow)
        toggles = Gtk.Box(spacing=16)
        toggles.append(self.hidden)
        toggles.append(self.system)
        self.append(toggles)
        self.keep_rule.connect('notify::selected', self._rule_changed)
        for control in (self.preferred, self.exclude):
            control.connect('changed', lambda *_: self._changed())
        for control in (self.workers, self.limit, self.minimum):
            control.connect('value-changed', lambda *_: self._changed())
        for control in (self.hidden, self.system):
            control.connect('toggled', lambda *_: self._changed())

    def _rule_changed(self, *_):
        self.preferred.set_sensitive(KEEP_RULES[self.keep_rule.get_selected()] == 'Folder')
        self._changed()

    def options(self):
        extensions = tuple(filter(None, re.split(r'[,;\s]+', self.exclude.get_text())))
        return ScanOptions(limit=self.limit.get_value_as_int(), workers=self.workers.get_value_as_int(),
                           keep_rule=KEEP_RULES[self.keep_rule.get_selected()],
                           preferred_folder=self.preferred.get_text(),
                           minimum_bytes=int(self.minimum.get_value() * BYTES_PER_KILOBYTE),
                           skip_hidden=self.hidden.get_active(), skip_system=self.system.get_active(),
                           excluded_extensions=extensions)
