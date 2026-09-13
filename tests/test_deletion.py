"""Disposable-file safety and isolated native Trash acceptance tests."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CONTENT = b"identical disposable fixture\n"
SUBPROCESS_TIMEOUT_SECONDS = 30


class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("copyfinder.deletion"),
                             "Safe deletion implementation is not present yet")
        self.deletion = importlib.import_module("copyfinder.deletion")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.kept = self.root / "original.txt"
        self.candidate = self.root / "original copy.txt"
        self.kept.write_bytes(FIXTURE_CONTENT)
        self.candidate.write_bytes(FIXTURE_CONTENT)
        self.kept_record = self.record(self.kept)
        self.candidate_record = self.record(self.candidate)
        self.trash = self.root / "fixture-trash"
        self.trash.mkdir()

    @staticmethod
    def record(path):
        from copyfinder.core import FileRecord

        attributes = path.stat()
        return FileRecord(str(path), attributes.st_size, attributes.st_mtime_ns,
                          attributes.st_ctime_ns, attributes.st_dev,
                          attributes.st_ino, hashlib.sha256(path.read_bytes()).hexdigest())

    def move_to_fixture_trash(self, path):
        Path(path).rename(self.trash / Path(path).name)

    def validate(self, action=None):
        self.deletion.validate_and_trash(
            self.candidate_record, self.kept_record,
            action or self.move_to_fixture_trash)

    def assert_refused(self):
        with self.assertRaises(self.deletion.UnsafeDeletionError):
            self.validate()
        self.assertEqual(list(self.trash.iterdir()), [])

    def test_valid_duplicate_moves_and_surviving_kept_is_unchanged(self):
        self.validate()
        self.assertFalse(self.candidate.exists())
        self.assertEqual((self.trash / self.candidate.name).read_bytes(), FIXTURE_CONTENT)
        self.assertEqual(self.kept.read_bytes(), FIXTURE_CONTENT)

    def test_missing_kept_preserves_candidate(self):
        self.kept.unlink()
        self.assert_refused()
        self.assertEqual(self.candidate.read_bytes(), FIXTURE_CONTENT)

    def test_missing_candidate_does_not_invoke_trash(self):
        self.candidate.unlink()
        self.assert_refused()

    def test_modified_kept_preserves_candidate(self):
        self.kept.write_bytes(b"changed original")
        self.assert_refused()
        self.assertTrue(self.candidate.exists())

    def test_modified_candidate_is_preserved(self):
        self.candidate.write_bytes(b"changed copy")
        self.assert_refused()
        self.assertEqual(self.candidate.read_bytes(), b"changed copy")

    def test_replaced_kept_with_identical_content_is_refused(self):
        self.kept.rename(self.root / "previous-original.txt")
        self.kept.write_bytes(FIXTURE_CONTENT)
        self.assert_refused()

    def test_replaced_candidate_with_identical_content_is_refused(self):
        self.candidate.rename(self.root / "previous-copy.txt")
        self.candidate.write_bytes(FIXTURE_CONTENT)
        self.assert_refused()

    def test_timestamp_only_change_is_refused(self):
        attributes = self.candidate.stat()
        os.utime(self.candidate, ns=(attributes.st_atime_ns, attributes.st_mtime_ns + 1))
        self.assert_refused()

    def test_forged_scan_digest_is_refused(self):
        from dataclasses import replace

        self.candidate_record = replace(self.candidate_record, digest="0" * 64)
        self.kept_record = replace(self.kept_record, digest="0" * 64)
        self.assert_refused()

    def test_non_duplicate_records_are_refused(self):
        self.candidate.write_bytes(b"different current file")
        self.candidate_record = self.record(self.candidate)
        self.assert_refused()

    def test_same_record_cannot_be_its_own_survivor(self):
        self.kept_record = self.candidate_record
        self.assert_refused()

    def test_hardlink_alias_of_kept_is_refused(self):
        self.candidate.unlink()
        os.link(self.kept, self.candidate)
        self.candidate_record = self.record(self.candidate)
        self.kept_record = self.record(self.kept)
        self.assert_refused()

    def test_candidate_with_another_hardlink_is_refused(self):
        alias = self.root / "third-name.txt"
        os.link(self.candidate, alias)
        self.candidate_record = self.record(self.candidate)
        self.assert_refused()
        self.assertEqual(alias.read_bytes(), FIXTURE_CONTENT)

    def test_symlink_candidate_is_refused(self):
        self.candidate.unlink()
        self.candidate.symlink_to(self.kept)
        self.assert_refused()
        self.assertTrue(self.candidate.is_symlink())

    def test_symlink_kept_is_refused(self):
        previous = self.root / "previous-original.txt"
        self.kept.rename(previous)
        self.kept.symlink_to(previous)
        self.assert_refused()

    def test_symlink_parent_is_refused(self):
        from dataclasses import replace

        alias = self.root / "directory-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        self.candidate_record = replace(self.candidate_record, path=str(alias / self.candidate.name))
        self.assert_refused()

    def test_special_file_is_refused_without_blocking(self):
        self.candidate.unlink()
        os.mkfifo(self.candidate)
        self.assert_refused()

    def test_changed_file_during_hash_is_refused(self):
        original_read = os.read
        changed = False

        def read_then_change(descriptor, length):
            nonlocal changed
            chunk = original_read(descriptor, length)
            if chunk and not changed:
                changed = True
                self.candidate.write_bytes(b"changed during hashing")
            return chunk

        with patch("copyfinder.deletion.os.read", side_effect=read_then_change):
            self.assert_refused()

    def test_failed_trash_is_reported_and_file_remains(self):
        def unavailable(_path):
            raise OSError("Trash is unsupported on this fixture")

        with self.assertRaisesRegex(self.deletion.UnsafeDeletionError, "unsupported"):
            self.validate(unavailable)
        self.assertTrue(self.candidate.exists())
        self.assertTrue(self.kept.exists())

    def test_silent_trash_noop_is_not_reported_as_success(self):
        with self.assertRaises(self.deletion.UnsafeDeletionError):
            self.validate(lambda _path: None)
        self.assertTrue(self.candidate.exists())

    def test_survivor_changed_during_action_is_reported(self):
        def move_and_change(path):
            self.move_to_fixture_trash(path)
            self.kept.write_bytes(b"concurrent edit")

        with self.assertRaises(self.deletion.UnsafeDeletionError):
            self.validate(move_and_change)


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("copyfinder.desktop"),
                             "Native desktop implementation is not present yet")
        self.desktop = importlib.import_module("copyfinder.desktop")

    def test_network_mount_longest_prefix_wins(self):
        mount_table = (
            "20 1 0:1 / / rw - ext4 /dev/root rw\n"
            "21 20 0:2 / /media/network rw - nfs host:/share rw\n"
            "22 21 0:3 / /media/network/local rw - ext4 /dev/loop0 rw\n"
            "23 20 0:4 / /media/with\\040space rw - cifs //host/share rw\n"
        )
        with patch("copyfinder.desktop.Path.read_text", return_value=mount_table):
            self.assertTrue(self.desktop.is_network_path("/media/network/file.txt"))
            self.assertFalse(self.desktop.is_network_path("/media/network/local/file.txt"))
            self.assertFalse(self.desktop.is_network_path("/media/network-other/file.txt"))
            self.assertTrue(self.desktop.is_network_path("/media/with space/file.txt"))

    def test_gvfs_locations_are_network_classified(self):
        self.assertTrue(self.desktop.is_network_path(f"/run/user/{os.getuid()}/gvfs/smb-share/file"))
        self.assertTrue(self.desktop.is_network_path(str(Path.home() / ".gvfs" / "share" / "file")))

    def test_non_utf8_mount_path_preserves_network_classification(self):
        with tempfile.TemporaryDirectory() as temporary:
            mountinfo = Path(temporary) / "mountinfo"
            mountinfo.write_bytes(
                b"20 1 0:1 / / rw - ext4 /dev/root rw\n"
                b"21 20 0:2 / /media/network-\xff rw - nfs host:/share rw\n"
            )
            network_file = os.fsdecode(b"/media/network-\xff/file.txt")
            with patch("copyfinder.desktop.MOUNTINFO_PATH", mountinfo):
                try:
                    self.assertFalse(self.desktop.is_network_path("/unrelated/file.txt"))
                    self.assertTrue(self.desktop.is_network_path(network_file))
                except UnicodeDecodeError:
                    self.fail("Mount paths must preserve undecodable bytes without failing classification")

    def test_compatibility_report_is_informative(self):
        report = self.desktop.compatibility_report()
        self.assertIn("GTK", report)
        self.assertIn("Trash", report)
        self.assertIn("Linux", report)
        self.assertIsInstance(report, str)

    def test_real_gio_trash_and_restore_in_isolated_subprocess(self):
        script = r'''
import hashlib
import json
import os
from pathlib import Path
import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib
from copyfinder.core import FileRecord
from copyfinder.deletion import validate_and_trash
from copyfinder.desktop import trash_file
root = Path(os.environ["COPYFINDER_TRASH_FIXTURE"])
data = root / "data"
assert Path(GLib.get_user_data_dir()) == data
assert Path.home() == root / "home"
kept = root / "home" / "original.txt"
candidate = root / "home" / "original copy.txt"
payload = b"isolated real GIO Trash fixture\n"
kept.write_bytes(payload)
candidate.write_bytes(payload)
def record(path):
    attributes = path.stat()
    return FileRecord(str(path), attributes.st_size, attributes.st_mtime_ns,
                      attributes.st_ctime_ns, attributes.st_dev, attributes.st_ino,
                      hashlib.sha256(path.read_bytes()).hexdigest())
validate_and_trash(record(candidate), record(kept), trash_file)
assert not candidate.exists()
assert kept.read_bytes() == payload
trashed = list((data / "Trash" / "files").iterdir())
metadata = list((data / "Trash" / "info").iterdir())
assert len(trashed) == len(metadata) == 1
assert trashed[0].read_bytes() == payload
assert "Path=" in metadata[0].read_text()
trashed[0].rename(candidate)
metadata[0].unlink()
assert candidate.read_bytes() == kept.read_bytes() == payload
assert not list((data / "Trash" / "files").iterdir())
print(json.dumps({"trashed": 1, "restored": 1, "kept_unchanged": True}))
'''
        with tempfile.TemporaryDirectory(prefix="copyfinder-trash-acceptance-") as temporary:
            root = Path(temporary)
            (root / "home").mkdir()
            (root / "data").mkdir()
            environment = dict(os.environ, HOME=str(root / "home"),
                               XDG_DATA_HOME=str(root / "data"),
                               COPYFINDER_TRASH_FIXTURE=str(root), GIO_USE_VFS="local")
            completed = subprocess.run(["/usr/bin/python3", "-c", script],
                                       cwd=PROJECT_ROOT, env=environment,
                                       text=True, capture_output=True,
                                       timeout=SUBPROCESS_TIMEOUT_SECONDS, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout),
                             {"trashed": 1, "restored": 1, "kept_unchanged": True})


if __name__ == "__main__":
    unittest.main()
