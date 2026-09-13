"""Cross-platform contracts that can be verified without a macOS runtime."""

import os
import unittest
from unittest.mock import patch

from copyfinder import runtime
from copyfinder.runtime import (
    directory_open_flags,
    file_open_flags,
    platform_label,
    path_is_under,
    system_directories,
)


class RuntimeTests(unittest.TestCase):
    def test_macos_label_and_system_directories_are_native(self):
        self.assertEqual(platform_label("darwin"), "macOS")
        directories = system_directories("darwin")
        self.assertIn("/System", directories)
        self.assertIn("/Library", directories)
        self.assertNotIn("/Users", directories)

    def test_linux_system_directories_remain_unchanged(self):
        self.assertEqual(system_directories("linux"), ("/dev", "/proc", "/sys", "/run"))
        self.assertEqual(platform_label("linux"), "Linux Mint")

    def test_open_flags_retain_no_follow_and_directory_safety(self):
        directory_flags = directory_open_flags()
        file_flags = file_open_flags()
        self.assertEqual(directory_flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
        self.assertEqual(directory_flags & os.O_DIRECTORY, os.O_DIRECTORY)
        self.assertEqual(file_flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
        self.assertEqual(file_flags & os.O_ACCMODE, os.O_RDONLY)

    def test_deletion_directory_flags_fall_back_when_o_path_is_unavailable(self):
        with patch.object(runtime, "_path_open_flag", return_value=None):
            flags = directory_open_flags(prefer_path_handle=True)
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
        self.assertEqual(flags & os.O_NOFOLLOW, os.O_NOFOLLOW)
        self.assertEqual(flags & os.O_DIRECTORY, os.O_DIRECTORY)
        self.assertEqual(flags & os.O_CLOEXEC, os.O_CLOEXEC)

    def test_macos_system_path_matching_is_case_insensitive(self):
        self.assertTrue(path_is_under("/library/cache", "/Library", "darwin"))
        self.assertTrue(path_is_under("/SYSTEM", "/System", "darwin"))
        self.assertFalse(path_is_under("/library-other", "/Library", "darwin"))
        self.assertFalse(path_is_under("/library/cache", "/Library", "linux"))


if __name__ == "__main__":
    unittest.main()
