"""Independent scanner fixtures; all filesystem mutations are disposable."""

from dataclasses import FrozenInstanceError
import hashlib
import io
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

IMPLEMENTED = (Path(__file__).parents[1] / "copyfinder/core.py").is_file()
if IMPLEMENTED:
    from copyfinder.core import FileRecord, ScanCancelled, ScanOptions, scan
    from copyfinder.keep import order_files
    from copyfinder.traversal import FileSnapshot, virtual_mounts
    from copyfinder.hashing import hash_snapshot


class ImplementationTests(unittest.TestCase):
    def test_scanner_implementation_exists(self):
        self.assertTrue(IMPLEMENTED, "scanner implementation pending")


@unittest.skipUnless(IMPLEMENTED, "scanner implementation pending")
class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, name, contents=b"abc"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        return path

    def run_scan(self, options=None, progress=None, cancel=None):
        return scan(str(self.root), options or ScanOptions(),
                    cancel or threading.Event(), progress or (lambda message: None))

    def test_exact_hash_groups_exclude_empty_and_same_size_different_data(self):
        original = self.write("report.txt")
        duplicate = self.write("report copy.txt")
        self.write("different.txt", b"xyz")
        self.write("empty-a", b"")
        self.write("empty-b", b"")
        result = self.run_scan()
        self.assertEqual(len(result.groups), 1)
        self.assertEqual([item.path for item in result.groups[0].files],
                         [str(original), str(duplicate)])
        self.assertEqual(result.groups[0].files[0].digest,
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertFalse(result.limit_reached)
        self.assertEqual(result.scanned_files, 3)
        self.assertEqual(result.skipped_files, 2)

    def test_limit_counts_duplicate_rows_not_kept_rows(self):
        for number in range(7):
            self.write(f"sample-{number}.txt")
        result = self.run_scan(ScanOptions(limit=2))
        self.assertEqual(sum(len(group.files) - 1 for group in result.groups), 2)
        self.assertTrue(result.limit_reached)

    def test_limit_across_separate_groups(self):
        for number in range(5):
            self.write(f"{number}-a", bytes([number + 1]))
            self.write(f"{number}-b", bytes([number + 1]))
        result = self.run_scan(ScanOptions(limit=3))
        self.assertEqual(len(result.groups), 3)
        self.assertEqual(sum(len(group.files) - 1 for group in result.groups), 3)

    def test_hidden_directories_extensions_and_minimum(self):
        self.write("included-a.bin", b"hello")
        self.write("included-b.bin", b"hello")
        self.write(".hidden", b"hello")
        self.write(".folder/hidden.bin", b"hello")
        self.write("excluded.TXT", b"hello")
        self.write("short", b"a")
        result = self.run_scan(ScanOptions(minimum_bytes=2, excluded_extensions=(" TXT ",)))
        self.assertEqual(len(result.groups[0].files), 2)
        self.assertEqual(result.scanned_files, 2)
        self.assertEqual(result.skipped_files, 4)

    def test_hidden_can_be_included(self):
        self.write(".nested/a")
        self.write(".b")
        result = self.run_scan(ScanOptions(skip_hidden=False))
        self.assertEqual(len(result.groups[0].files), 2)

    def test_case_distinct_names_are_independent(self):
        self.write("File.txt")
        self.write("file.txt")
        self.assertEqual(len(self.run_scan().groups[0].files), 2)

    def test_unicode_newline_and_undecodable_filename(self):
        self.write("café\nreport.txt")
        filename = os.fsdecode(b"raw-\xff.txt")
        self.write(filename)
        self.assertEqual(len(self.run_scan().groups[0].files), 2)

    def test_hard_links_do_not_count_as_reclaimable_duplicates(self):
        original = self.write("original")
        os.link(original, self.root / "alias")
        self.assertEqual(self.run_scan().groups, ())
        self.write("independent")
        result = self.run_scan()
        self.assertEqual(len(result.groups[0].files), 2)
        self.assertEqual(len({(item.device, item.inode) for item in result.groups[0].files}), 2)
        self.assertEqual(result.skipped_files, 1)

    def test_symlinks_loops_and_special_files_are_excluded(self):
        original = self.write("original")
        self.write("duplicate")
        (self.root / "file-link").symlink_to(original)
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)
        os.mkfifo(self.root / "pipe")
        result = self.run_scan(ScanOptions(skip_system=False))
        self.assertEqual(len(result.groups[0].files), 2)
        self.assertEqual(result.skipped_files, 3)

    def test_cancellation_before_inventory(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ScanCancelled):
            self.run_scan(cancel=cancel)

    def test_cancellation_after_inventory(self):
        self.write("a")
        self.write("b")
        cancel = threading.Event()
        def progress(message):
            if message.startswith("Hashing"):
                cancel.set()
        with self.assertRaises(ScanCancelled):
            self.run_scan(cancel=cancel, progress=progress)

    def test_changed_file_is_skipped_before_hashing(self):
        changed = self.write("a")
        self.write("b")
        changed_once = False
        def progress(message):
            nonlocal changed_once
            if message.startswith("Hashing") and not changed_once:
                changed.write_bytes(b"xyz")
                changed_once = True
        result = self.run_scan(progress=progress)
        self.assertEqual(result.groups, ())
        self.assertEqual(result.skipped_files, 1)

    def test_file_replaced_by_symlink_is_skipped(self):
        changed = self.write("a")
        other = self.write("b")
        changed_once = False
        def progress(message):
            nonlocal changed_once
            if message.startswith("Hashing") and not changed_once:
                changed.unlink()
                changed.symlink_to(other)
                changed_once = True
        self.assertEqual(self.run_scan(progress=progress).groups, ())

    def test_unreadable_file_is_counted_as_skipped(self):
        from copyfinder import hashing
        original = self.write("a")
        self.write("b")
        actual_open = hashing.open_regular_file
        def denied(path):
            if path == str(original):
                raise PermissionError("deliberate inaccessible fixture")
            return actual_open(path)
        with patch("copyfinder.hashing.open_regular_file", side_effect=denied):
            result = self.run_scan()
        self.assertEqual(result.groups, ())
        self.assertEqual(result.skipped_files, 1)

    def test_png_dimensions_are_metadata_only(self):
        from PIL import Image
        first = self.root / "image.png"
        Image.new("RGB", (31, 17), "red").save(first)
        self.write("image copy.png", first.read_bytes())
        result = self.run_scan()
        self.assertEqual({(item.width, item.height) for item in result.groups[0].files}, {(31, 17)})

    def test_all_supported_image_formats(self):
        from PIL import Image
        for extension in ("jpg", "png", "bmp", "gif", "tiff", "webp"):
            with self.subTest(extension=extension):
                first = self.root / ("picture." + extension)
                Image.new("RGB", (12, 9), "blue").save(first)
                self.write("picture copy." + extension, first.read_bytes())
        result = self.run_scan()
        self.assertEqual(len(result.groups), 6)
        self.assertTrue(all((item.width, item.height) == (12, 9)
                            for group in result.groups for item in group.files))

    def test_webp_decoder_never_makes_unrestricted_underlying_reads(self):
        from PIL import Image
        from copyfinder.hashing import image_dimensions
        output = io.BytesIO()
        Image.new("RGB", (12, 9), "blue").save(output, format="WEBP")
        class TrackedStream(io.BytesIO):
            def __init__(self, contents):
                super().__init__(contents)
                self.requests = []
            def read(self, amount=-1):
                self.requests.append(amount)
                return super().read(amount)
        stream = TrackedStream(output.getvalue())
        self.assertEqual(image_dimensions(stream), (12, 9))
        self.assertTrue(stream.requests)
        self.assertTrue(all(amount >= 0 for amount in stream.requests),
                        f"unrestricted metadata read: {stream.requests}")

    def test_metadata_heavy_valid_webp_stops_at_read_budget(self):
        from PIL import Image
        from copyfinder.hashing import image_dimensions
        metadata_budget = 256
        output = io.BytesIO()
        Image.new("RGB", (12, 9), "blue").save(
            output, format="WEBP", exif=b"Exif\x00\x00" + b"a" * (metadata_budget * 16))
        contents = output.getvalue()
        with Image.open(io.BytesIO(contents)) as valid_fixture:
            self.assertEqual(valid_fixture.size, (12, 9))
        class TrackedStream(io.BytesIO):
            def __init__(self, contents):
                super().__init__(contents)
                self.bytes_read = 0
            def read(self, amount=-1):
                result = super().read(amount)
                self.bytes_read += len(result)
                return result
        stream = TrackedStream(contents)
        with patch("copyfinder.hashing.IMAGE_METADATA_READ_BUDGET", metadata_budget, create=True):
            dimensions = image_dimensions(stream)
        self.assertLessEqual(stream.bytes_read, metadata_budget)
        self.assertEqual(dimensions, (None, None))

    def test_scan_results_do_not_depend_on_worker_count(self):
        for number in range(3):
            self.write(f"group-{number}/original", bytes([number + 1]) * 500)
            self.write(f"group-{number}/original copy", bytes([number + 1]) * 500)
        self.assertEqual(self.run_scan(ScanOptions(workers=1)).groups,
                         self.run_scan(ScanOptions(workers=4)).groups)

    def test_limit_stops_remaining_workers_without_cancelling_user_event(self):
        from copyfinder import core
        for number in range(8):
            self.write(f"sample-{number}")
        worker_cancellations = []
        actual_hash = core.hash_snapshot
        def tracked_hash(snapshot, cancel):
            worker_cancellations.append(cancel)
            return actual_hash(snapshot, cancel)
        user_cancel = threading.Event()
        with patch("copyfinder.core.hash_snapshot", side_effect=tracked_hash):
            result = self.run_scan(ScanOptions(limit=1), cancel=user_cancel)
        self.assertTrue(result.limit_reached)
        self.assertTrue(worker_cancellations)
        self.assertTrue(all(cancel.is_set() for cancel in worker_cancellations))
        self.assertFalse(user_cancel.is_set())

    def test_cancel_during_streaming_hash(self):
        from copyfinder.hashing import hash_stream
        import io
        cancel = threading.Event()
        class CancellingStream(io.BytesIO):
            def read(self, amount):
                chunk = super().read(amount)
                cancel.set()
                return chunk
        with self.assertRaises(ScanCancelled):
            hash_stream(CancellingStream(b"abc"), cancel)

    def test_file_changed_during_hash_is_skipped(self):
        from copyfinder import hashing
        changed = self.write("a")
        self.write("b")
        actual_hash_stream = hashing.hash_stream
        def changing_hash(stream, cancel):
            digest = actual_hash_stream(stream, cancel)
            if os.fstat(stream.fileno()).st_ino == changed.stat().st_ino:
                changed.write_bytes(b"xyz")
            return digest
        with patch("copyfinder.hashing.hash_stream", side_effect=changing_hash):
            result = self.run_scan()
        self.assertEqual(result.groups, ())
        self.assertEqual(result.skipped_files, 1)

    def test_directory_replaced_by_symlink_is_not_followed(self):
        self.write("original/a")
        self.write("original/b")
        changed_once = False
        def progress(message):
            nonlocal changed_once
            if message.startswith("Hashing") and not changed_once:
                (self.root / "original").rename(self.root / "moved")
                (self.root / "original").symlink_to(self.root / "moved", target_is_directory=True)
                changed_once = True
        result = self.run_scan(progress=progress)
        self.assertEqual(result.groups, ())
        self.assertEqual(result.skipped_files, 2)

    def test_missing_file_snapshot_cannot_be_hashed(self):
        path = self.write("missing")
        information = path.stat()
        snapshot = FileSnapshot(str(path), information.st_size, information.st_mtime_ns,
                                information.st_ctime_ns, information.st_dev, information.st_ino)
        path.unlink()
        self.assertIsNone(hash_snapshot(snapshot, threading.Event()))

    def test_hash_streams_files_larger_than_read_chunk(self):
        contents = b"abcdefgh" * 200000
        self.write("large-a", contents)
        self.write("large-b", contents)
        digest = self.run_scan().groups[0].files[0].digest
        self.assertEqual(digest, hashlib.sha256(contents).hexdigest())

    def test_virtual_mounts_are_always_excluded(self):
        self.write("virtual/a")
        self.write("virtual/b")
        with patch("copyfinder.traversal.virtual_mounts", return_value=(str(self.root / "virtual"),)):
            result = self.run_scan(ScanOptions(skip_system=False))
        self.assertEqual(result.groups, ())
        self.assertEqual(result.skipped_files, 1)

    def test_temporary_inventory_is_not_included_when_inside_scan_root(self):
        self.write("a")
        self.write("b")
        actual_temporary_directory = tempfile.TemporaryDirectory
        def nested_temporary(**options):
            return actual_temporary_directory(dir=self.root, **options)
        with patch("copyfinder.core.tempfile.TemporaryDirectory", side_effect=nested_temporary):
            result = self.run_scan()
        self.assertEqual(result.scanned_files, 2)
        self.assertEqual(len(result.groups[0].files), 2)

    def test_invalid_root_is_rejected(self):
        path = self.write("regular")
        with self.assertRaises(ValueError):
            scan(str(path), ScanOptions(), threading.Event(), lambda message: None)


@unittest.skipUnless(IMPLEMENTED, "scanner implementation pending")
class KeepAndOptionsTests(unittest.TestCase):
    def record(self, path, modified=100, width=None, height=None):
        return FileRecord(path, 3, modified, 100, 1, 1, "hash", width, height)

    def kept(self, records, rule, folder=""):
        return order_files(tuple(records), rule, folder)[0].path

    def test_original_deprioritizes_copy_and_number_suffix(self):
        records = [self.record("/root/report copy.txt"), self.record("/root/report (1).txt"),
                   self.record("/root/report.txt")]
        self.assertEqual(self.kept(records, "Original"), "/root/report.txt")

    def test_copy_suffix_scores_below_parenthesized_number(self):
        for suffix in (" - copy", " copy", "_copy"):
            with self.subTest(suffix=suffix):
                copy_path = "/root/report" + suffix + ".txt"
                records = [self.record("/root/r (1).txt"), self.record(copy_path)]
                self.assertEqual(self.kept(records, "Original"), copy_path)

    def test_suffix_scoring_only_matches_specified_trailing_forms(self):
        records = [self.record("/root/a_copy.txt"), self.record("/root/b copy 2.txt")]
        self.assertEqual(self.kept(records, "Original"), "/root/b copy 2.txt")

    def test_equal_stem_lengths_choose_oldest_modification_before_path(self):
        records = [self.record("/root/a.txt", modified=200),
                   self.record("/root/z.txt", modified=100)]
        self.assertEqual(self.kept(records, "Original"), "/root/z.txt")

    def test_original_uses_stem_length_without_extension(self):
        records = [self.record("/root/a.longextension"), self.record("/root/bb.x")]
        self.assertEqual(self.kept(records, "Original"), "/root/a.longextension")

    def test_shortest_name_uses_stem_length_without_extension(self):
        records = [self.record("/root/a.longextension"), self.record("/root/bb.x")]
        self.assertEqual(self.kept(records, "Shortest name"), "/root/a.longextension")

    def test_all_rules_use_full_case_sensitive_path_as_final_tie_break(self):
        records = [self.record("/root/zz/A.txt"), self.record("/root/a/B.txt"),
                   self.record("/root/Z-long/C.txt")]
        for rule in ("Original", "Shortest name", "Oldest file", "Newest file", "Folder", "Highest Resolution"):
            with self.subTest(rule=rule):
                self.assertEqual(self.kept(records, rule), "/root/Z-long/C.txt")

    def test_primary_rule_precedes_suffix_and_common_ties(self):
        records = [self.record("/root/long-original.txt", modified=100, width=10, height=10),
                   self.record("/root/x (1).txt", modified=200, width=20, height=20)]
        self.assertEqual(self.kept(records, "Original"), "/root/long-original.txt")
        self.assertEqual(self.kept(records, "Shortest name"), "/root/x (1).txt")
        self.assertEqual(self.kept(records, "Newest file"), "/root/x (1).txt")
        self.assertEqual(self.kept(records, "Highest Resolution"), "/root/x (1).txt")

    def test_common_ties_apply_after_equal_primary_keys(self):
        records = [self.record("/root/z.txt", modified=100), self.record("/root/a.txt", modified=200)]
        for rule in ("Shortest name", "Folder", "Highest Resolution"):
            with self.subTest(rule=rule):
                self.assertEqual(self.kept(records, rule), "/root/z.txt")

    def test_shortest_filename_rule(self):
        records = [self.record("/root/a/long-name.txt"), self.record("/root/long-folder/b.txt")]
        self.assertEqual(self.kept(records, "Shortest name"), "/root/long-folder/b.txt")

    def test_modification_time_rules(self):
        records = [self.record("/root/new", 300), self.record("/root/old", 1)]
        self.assertEqual(self.kept(records, "Oldest file"), "/root/old")
        self.assertEqual(self.kept(records, "Newest file"), "/root/new")

    def test_folder_rule_respects_directory_boundary(self):
        records = [self.record("/root/preferred-other/a"), self.record("/root/preferred/sub/z")]
        self.assertEqual(self.kept(records, "Folder", "/root/preferred"), "/root/preferred/sub/z")

    def test_highest_resolution_uses_pixel_area(self):
        records = [self.record("/root/a", width=100, height=200),
                   self.record("/root/b", width=200, height=200), self.record("/root/c")]
        self.assertEqual(self.kept(records, "Highest Resolution"), "/root/b")

    def test_ties_are_deterministic_and_case_sensitive(self):
        records = [self.record("/root/a"), self.record("/root/A")]
        for rule in ("Original", "Shortest name", "Oldest file", "Newest file", "Folder", "Highest Resolution"):
            with self.subTest(rule=rule):
                self.assertEqual(self.kept(records, rule), self.kept(reversed(records), rule))

    def test_options_normalize_limits_extensions_and_unknown_rule(self):
        options = ScanOptions(limit=0, workers=100, minimum_bytes=-1, keep_rule="invalid",
                              excluded_extensions=("TXT", " .PDF ", ".txt", ""))
        self.assertEqual((options.limit, options.workers, options.minimum_bytes), (1, 16, 0))
        self.assertEqual(options.keep_rule, "Original")
        self.assertEqual(options.excluded_extensions, (".pdf", ".txt"))

    def test_records_and_options_are_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.record("/root/a").path = "/root/b"
        with self.assertRaises(FrozenInstanceError):
            ScanOptions().workers = 4


if __name__ == "__main__":
    unittest.main()
