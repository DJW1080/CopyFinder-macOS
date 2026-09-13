"""Selection state kept separate from immutable filesystem snapshots."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import FileRecord


class ReviewRow:
    def __init__(self, record: 'FileRecord', kept: bool):
        self.record = record
        self._kept = kept
        self._selected = not kept

    @property
    def is_kept(self):
        return self._kept

    @property
    def selected(self):
        return self._selected and not self._kept

    @selected.setter
    def selected(self, value):
        self._selected = bool(value) and not self._kept

    def assign_role(self, kept):
        self._kept = kept
        self._selected = not kept


class ReviewGroup:
    def __init__(self, group_id: int, records):
        if len(records) < 2:
            raise ValueError('A duplicate group needs at least two files.')
        self.group_id = group_id
        self.rows = [ReviewRow(record, index == 0) for index, record in enumerate(records)]
        self.expanded = True

    @property
    def kept(self):
        return next(row.record for row in self.rows if row.is_kept)

    @property
    def has_duplicates(self):
        return len(self.rows) > 1

    def keep(self, path):
        if not any(row.record.path == path for row in self.rows):
            raise ValueError('The kept file must belong to this group.')
        for row in self.rows:
            row.assign_role(row.record.path == path)

    def set_selected(self, selected):
        for row in self.rows:
            row.selected = selected

    def selected_records(self):
        return [row.record for row in self.rows if row.selected]

    def remove(self, path):
        if self.kept.path == path:
            raise ValueError('The kept file cannot be removed.')
        self.rows = [row for row in self.rows if row.record.path != path]
