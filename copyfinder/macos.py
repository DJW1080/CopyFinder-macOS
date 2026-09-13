"""Lazy PyObjC integration for native macOS desktop services."""

from __future__ import annotations

import os
from pathlib import Path
import platform


class DesktopIntegrationError(RuntimeError):
    """A requested desktop action could not be completed."""


def _native_frameworks():
    import AppKit
    import Foundation
    import objc

    return AppKit, Foundation, objc


def _error_description(error) -> str:
    if error is None:
        return "macOS did not provide an error description"
    description = getattr(error, "localizedDescription", None)
    return str(description() if callable(description) else error)


def _file_url(path: str, foundation):
    return foundation.NSURL.fileURLWithPath_(os.path.abspath(path))


def reveal_file(path: str) -> None:
    """Select a path in Finder."""
    try:
        appkit, foundation, objc = _native_frameworks()
        with objc.autorelease_pool():
            url = _file_url(path, foundation)
            appkit.NSWorkspace.sharedWorkspace().activateFileViewerSelectingURLs_([url])
    except Exception as error:
        raise DesktopIntegrationError(f"Finder could not reveal the file: {error}") from error


def _url_path(url) -> Path:
    value = getattr(url, "path", None)
    path = value() if callable(value) else value
    if not path:
        raise DesktopIntegrationError("macOS Trash did not return a destination path")
    return Path(str(path))


def trash_with_result(path: str) -> Path:
    """Move a path to Trash and return the exact native destination."""
    try:
        _appkit, foundation, objc = _native_frameworks()
        with objc.autorelease_pool():
            source_url = _file_url(path, foundation)
            completed, destination_url, error = (
                foundation.NSFileManager.defaultManager()
                .trashItemAtURL_resultingItemURL_error_(source_url, None, None)
            )
            if not completed:
                raise DesktopIntegrationError(
                    f"macOS could not move the file to Trash: {_error_description(error)}"
                )
            if destination_url is None:
                raise DesktopIntegrationError("macOS Trash did not return a destination URL")
            return _url_path(destination_url)
    except DesktopIntegrationError:
        raise
    except Exception as error:
        raise DesktopIntegrationError(f"macOS could not move the file to Trash: {error}") from error


def trash_file(path: str) -> None:
    """Move a path to Trash while preserving the desktop module's public API."""
    trash_with_result(path)


def is_network_path(path: str) -> bool:
    """Classify the containing macOS volume using its native local-volume key."""
    try:
        _appkit, foundation, objc = _native_frameworks()
        with objc.autorelease_pool():
            url = _file_url(path, foundation)
            completed, is_local, error = url.getResourceValue_forKey_error_(
                None, foundation.NSURLVolumeIsLocalKey, None
            )
            if not completed or is_local is None:
                raise DesktopIntegrationError(
                    f"macOS could not classify the file's volume: {_error_description(error)}"
                )
            return not bool(is_local)
    except DesktopIntegrationError:
        raise
    except Exception as error:
        raise DesktopIntegrationError(f"macOS could not classify the file's volume: {error}") from error


def compatibility_report() -> str:
    """Describe native macOS services and application locations."""
    try:
        _appkit, foundation, objc = _native_frameworks()
        from .storage import settings_path, state_directory

        with objc.autorelease_pool():
            operating_system = foundation.NSProcessInfo.processInfo().operatingSystemVersionString()
        return "\n".join((
            "CopyFinder macOS compatibility report",
            f"Operating system: {operating_system}; {platform.machine()}",
            f"Python: {platform.python_version()}; PyObjC: {getattr(objc, '__version__', 'version unavailable')}",
            f"Configuration: {settings_path().parent}",
            f"Logs: {state_directory()}",
            "Finder reveal: native NSWorkspace.",
            "Trash: native NSFileManager only; support and permissions are checked for each operation.",
            "Volume classification: native NSURL local-volume resource value.",
            "No permanent deletion, ownership changes, permission changes, or privilege elevation.",
            "These checks are read-only; they do not establish that every filesystem supports Trash.",
        ))
    except DesktopIntegrationError:
        raise
    except Exception as error:
        raise DesktopIntegrationError(f"macOS compatibility checks could not run: {error}") from error
