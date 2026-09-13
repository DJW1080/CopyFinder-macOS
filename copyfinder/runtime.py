"""Operating-system constants shared by the scanner and user interface."""

from __future__ import annotations

import os
import sys


LINUX_SYSTEM_DIRECTORIES = ("/dev", "/proc", "/sys", "/run")
MACOS_SYSTEM_DIRECTORIES = (
    "/dev",
    "/System",
    "/Library",
    "/bin",
    "/sbin",
    "/usr",
    "/private/etc",
    "/private/var/db",
    "/private/var/log",
    "/private/var/root",
    "/private/var/run",
)
REQUIRED_OPEN_FLAG_NAMES = ("O_DIRECTORY", "O_NOFOLLOW", "O_CLOEXEC")


def platform_label(platform_name: str | None = None) -> str:
    """Return the edition label shown to users."""
    selected_platform = platform_name or sys.platform
    if selected_platform == "darwin":
        return "macOS"
    if selected_platform.startswith("linux"):
        return "Linux Mint"
    return selected_platform


def system_directories(platform_name: str | None = None) -> tuple[str, ...]:
    """Return system locations skipped when the user enables that option."""
    return (MACOS_SYSTEM_DIRECTORIES
            if (platform_name or sys.platform) == "darwin"
            else LINUX_SYSTEM_DIRECTORIES)


def path_is_under(path: str, directory: str,
                  platform_name: str | None = None) -> bool:
    """Compare path boundaries conservatively on case-insensitive macOS volumes."""
    selected_platform = platform_name or sys.platform
    directory = directory.rstrip(os.sep)
    if selected_platform == "darwin":
        path = path.casefold()
        directory = directory.casefold()
    return path == directory or path.startswith(directory + os.sep)


def _required_open_flags() -> int:
    missing = tuple(name for name in REQUIRED_OPEN_FLAG_NAMES if not hasattr(os, name))
    if missing:
        raise RuntimeError(f"CopyFinder requires safe file-open flags: {', '.join(missing)}")
    return os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _path_open_flag() -> int | None:
    return getattr(os, "O_PATH", None)


def directory_open_flags(prefer_path_handle: bool = False) -> int:
    """Build safe directory flags, using O_RDONLY where macOS has no O_PATH."""
    path_flag = _path_open_flag() if prefer_path_handle else None
    access_mode = path_flag if path_flag is not None else os.O_RDONLY
    return access_mode | _required_open_flags()


def file_open_flags() -> int:
    """Build flags that open a regular file without following a final symlink."""
    return os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
