import csv
import importlib.util
import io
import json
import unittest
from dataclasses import dataclass


@dataclass(frozen=True)
class Record:
    path: str
    size: int = 3
    modified_ns: int = 1_700_000_000_000_000_000
    digest: str = 'abc123'
    width: int | None = None
    height: int | None = None


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('copyfinder.review'), 'Review implementation is pending')
        from copyfinder.review import ReviewGroup
        self.group = ReviewGroup(7, (Record('/tmp/original.txt'), Record('/tmp/copy.txt')))

    def test_kept_file_cannot_be_selected_for_deletion(self):
        self.group.rows[0].selected = True
        self.assertFalse(self.group.rows[0].selected)
        self.assertEqual(len(self.group.selected_records()), 1)

    def test_switching_keep_selects_previous_keep_and_protects_new_keep(self):
        self.group.set_selected(False)
        self.group.keep('/tmp/copy.txt')
        self.assertEqual(self.group.kept.path, '/tmp/copy.txt')
        self.assertEqual([record.path for record in self.group.selected_records()], ['/tmp/original.txt'])

    def test_removing_last_duplicate_removes_duplicate_status(self):
        self.group.remove('/tmp/copy.txt')
        self.assertFalse(self.group.has_duplicates)
        self.assertEqual(self.group.kept.path, '/tmp/original.txt')

    def test_csv_round_trip_preserves_commas_quotes_and_newlines(self):
        from copyfinder.review import ReviewGroup
        from copyfinder.reports import build_csv, build_json
        odd_path = '/tmp/a,"b\nλ.txt'
        group = ReviewGroup(1, (Record(odd_path), Record('/tmp/dup.txt')))
        table = list(csv.DictReader(io.StringIO(build_csv([group], lambda path: False))))
        self.assertEqual(table[0]['Path'], odd_path)
        self.assertEqual(table[0]['DeleteStatus'], 'Kept')
        self.assertEqual(table[1]['Selected'], 'True')
        payload = json.loads(build_json([group], lambda path: False))
        self.assertEqual(payload[1]['DeleteStatus'], 'Selected')
        self.assertEqual(payload[0]['Path'], odd_path)
        self.assertIn('LastWriteTime', payload[0])
        self.assertNotIn('Modified', payload[0])


if __name__ == '__main__':
    unittest.main()
