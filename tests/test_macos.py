import os
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from copyfinder import desktop, macos, storage


class FakeError:
    def localizedDescription(self):
        return "native operation failed"


class FakeURL:
    def __init__(self, path):
        self._path = path

    def path(self):
        return self._path


class FakeNSURL:
    @staticmethod
    def fileURLWithPath_(path):
        return FakeURL(path)


class FakeObjC:
    @staticmethod
    def autorelease_pool():
        return nullcontext()


class MacOSDesktopServiceTests(unittest.TestCase):
    def native_frameworks(self, workspace=None, file_manager=None):
        class FakeWorkspaceClass:
            @staticmethod
            def sharedWorkspace():
                return workspace

        class FakeFileManagerClass:
            @staticmethod
            def defaultManager():
                return file_manager

        appkit = type("AppKit", (), {"NSWorkspace": FakeWorkspaceClass})
        foundation = type("Foundation", (), {
            "NSFileManager": FakeFileManagerClass,
            "NSProcessInfo": object,
            "NSURL": FakeNSURL,
            "NSURLVolumeIsLocalKey": "NSURLVolumeIsLocalKey",
        })
        return appkit, foundation, FakeObjC

    def assert_framework_loader_failure_is_wrapped(self, operation):
        with patch.object(macos, "_native_frameworks", side_effect=ImportError("PyObjC unavailable")):
            with self.assertRaisesRegex(macos.DesktopIntegrationError, "PyObjC unavailable"):
                operation()

    def test_reveal_wraps_framework_loader_failure(self):
        self.assert_framework_loader_failure_is_wrapped(lambda: macos.reveal_file("candidate.txt"))

    def test_trash_wraps_framework_loader_failure(self):
        self.assert_framework_loader_failure_is_wrapped(lambda: macos.trash_with_result("candidate.txt"))

    def test_volume_classification_wraps_framework_loader_failure(self):
        self.assert_framework_loader_failure_is_wrapped(lambda: macos.is_network_path("candidate.txt"))

    def test_compatibility_report_wraps_framework_loader_failure(self):
        self.assert_framework_loader_failure_is_wrapped(macos.compatibility_report)

    def test_reveal_selects_the_absolute_file_url_in_finder(self):
        class Workspace:
            selected_urls = None

            def activateFileViewerSelectingURLs_(self, urls):
                self.selected_urls = urls

        workspace = Workspace()
        with patch.object(macos, "_native_frameworks", return_value=self.native_frameworks(workspace=workspace)):
            macos.reveal_file("relative.txt")
        self.assertEqual(workspace.selected_urls[0].path(), os.path.abspath("relative.txt"))

    def test_trash_requires_success_and_returns_the_native_destination(self):
        destination = FakeURL("/Users/test/.Trash/candidate.txt")

        class FileManager:
            def trashItemAtURL_resultingItemURL_error_(self, url, resulting_url, error):
                return True, destination, None

        with patch.object(macos, "_native_frameworks", return_value=self.native_frameworks(file_manager=FileManager())):
            result = macos.trash_with_result("candidate.txt")
        self.assertEqual(result, Path("/Users/test/.Trash/candidate.txt"))

    def test_trash_failure_reports_the_native_error(self):
        class FileManager:
            def trashItemAtURL_resultingItemURL_error_(self, url, resulting_url, error):
                return False, None, FakeError()

        with patch.object(macos, "_native_frameworks", return_value=self.native_frameworks(file_manager=FileManager())):
            with self.assertRaisesRegex(macos.DesktopIntegrationError, "native operation failed"):
                macos.trash_file("candidate.txt")

    def test_trash_rejects_success_without_a_destination_url(self):
        class FileManager:
            def trashItemAtURL_resultingItemURL_error_(self, url, resulting_url, error):
                return True, None, None

        with patch.object(macos, "_native_frameworks", return_value=self.native_frameworks(file_manager=FileManager())):
            with self.assertRaisesRegex(macos.DesktopIntegrationError, "destination"):
                macos.trash_file("candidate.txt")

    def test_volume_classification_uses_the_native_local_volume_value(self):
        class URL(FakeURL):
            def getResourceValue_forKey_error_(self, value, key, error):
                return True, False, None

        class NSURL:
            fileURLWithPath_ = staticmethod(URL)

        frameworks = self.native_frameworks()
        frameworks[1].NSURL = NSURL
        with patch.object(macos, "_native_frameworks", return_value=frameworks):
            self.assertTrue(macos.is_network_path("/Volumes/share/file.txt"))

    def test_local_volume_is_not_network_classified(self):
        class URL(FakeURL):
            def getResourceValue_forKey_error_(self, value, key, error):
                return True, True, None

        class NSURL:
            fileURLWithPath_ = staticmethod(URL)

        frameworks = self.native_frameworks()
        frameworks[1].NSURL = NSURL
        with patch.object(macos, "_native_frameworks", return_value=frameworks):
            self.assertFalse(macos.is_network_path("/Users/test/file.txt"))

    def test_volume_classification_reports_resource_lookup_failure(self):
        class URL(FakeURL):
            def getResourceValue_forKey_error_(self, value, key, error):
                return False, None, FakeError()

        class NSURL:
            fileURLWithPath_ = staticmethod(URL)

        frameworks = self.native_frameworks()
        frameworks[1].NSURL = NSURL
        with patch.object(macos, "_native_frameworks", return_value=frameworks):
            with self.assertRaisesRegex(macos.DesktopIntegrationError, "native operation failed"):
                macos.is_network_path("/Volumes/share/file.txt")

    def test_native_compatibility_report_names_services_and_paths(self):
        class ProcessInfo:
            @staticmethod
            def processInfo():
                return ProcessInfo()

            def operatingSystemVersionString(self):
                return "Version 10.15.8"

        frameworks = self.native_frameworks()
        frameworks[1].NSProcessInfo = ProcessInfo
        environment = {
            "COPYFINDER_CONFIG_HOME": "/isolated/config",
            "COPYFINDER_STATE_HOME": "/isolated/logs",
        }
        with patch.object(macos, "_native_frameworks", return_value=frameworks), \
                patch.object(storage.sys, "platform", "darwin"), patch.dict(os.environ, environment, clear=True):
            report = macos.compatibility_report()
        self.assertIn("macOS compatibility report", report)
        self.assertIn("Version 10.15.8", report)
        self.assertIn("/isolated/config", report)
        self.assertIn("/isolated/logs", report)
        self.assertIn("NSWorkspace", report)
        self.assertIn("NSFileManager", report)


class DesktopDispatchTests(unittest.TestCase):
    def test_macos_dispatch_does_not_use_linux_gio(self):
        with patch.object(desktop.sys, "platform", "darwin"), \
                patch.object(macos, "trash_file", return_value=FakeURL("trash")) as native_trash, \
                patch.object(desktop.Gio.File, "new_for_path", side_effect=AssertionError("Linux GIO used")):
            self.assertIsNone(desktop.trash_file("candidate.txt"))
        native_trash.assert_called_once_with("candidate.txt")

    def test_linux_dispatch_preserves_gio_trash(self):
        gio_file = type("GioFile", (), {"trash": lambda self, cancellable: True})()
        with patch.object(desktop.sys, "platform", "linux"), \
                patch.object(desktop.Gio.File, "new_for_path", return_value=gio_file):
            self.assertIsNone(desktop.trash_file("candidate.txt"))


class MacOSStoragePathTests(unittest.TestCase):
    def test_macos_defaults_use_library_application_support_and_logs(self):
        with patch.object(storage.sys, "platform", "darwin"), patch.object(storage.Path, "home", return_value=Path("/Users/test")), \
                patch.dict(os.environ, {}, clear=True):
            self.assertEqual(storage.settings_path(), Path("/Users/test/Library/Application Support/CopyFinder/settings.json"))
            self.assertEqual(storage.state_directory(), Path("/Users/test/Library/Logs/CopyFinder"))

    def test_absolute_app_overrides_are_complete_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "config"
            state = Path(temporary) / "logs"
            environment = {"COPYFINDER_CONFIG_HOME": str(config), "COPYFINDER_STATE_HOME": str(state)}
            with patch.object(storage.sys, "platform", "darwin"), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(storage.settings_path(), config / "settings.json")
                self.assertEqual(storage.state_directory(), state)

    def test_relative_app_overrides_do_not_escape_native_defaults(self):
        environment = {"COPYFINDER_CONFIG_HOME": "relative", "COPYFINDER_STATE_HOME": "relative"}
        with patch.object(storage.sys, "platform", "darwin"), patch.object(storage.Path, "home", return_value=Path("/Users/test")), \
                patch.dict(os.environ, environment, clear=True):
            self.assertEqual(storage.settings_path(), Path("/Users/test/Library/Application Support/CopyFinder/settings.json"))
            self.assertEqual(storage.state_directory(), Path("/Users/test/Library/Logs/CopyFinder"))


if __name__ == "__main__":
    unittest.main()
