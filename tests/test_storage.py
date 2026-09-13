import importlib.util
import tempfile
import unittest
from pathlib import Path


class StorageTests(unittest.TestCase):
    def test_atomic_output_and_settings_round_trip(self):
        self.assertIsNotNone(importlib.util.find_spec('copyfinder.storage'), 'Storage implementation is pending')
        from copyfinder.storage import atomic_write, load_settings, save_settings
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config' / 'settings.json'
            save_settings({'last_folder': '/tmp/λ', 'scan': {'limit': 27}}, path)
            self.assertEqual(load_settings(path)['scan']['limit'], 27)
            self.assertEqual(load_settings(path)['last_folder'], '/tmp/λ')
            atomic_write(path, 'replacement')
            self.assertEqual(path.read_text(), 'replacement')
            self.assertEqual([item.name for item in path.parent.iterdir()], ['settings.json'])


if __name__ == '__main__':
    unittest.main()
