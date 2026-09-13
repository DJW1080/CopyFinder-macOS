"""Fail-closed validation around the desktop's pathname-based Trash operation."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import PurePosixPath
import stat
from typing import Callable, Iterator, TYPE_CHECKING

if TYPE_CHECKING:
    from .core import FileRecord


HASH_CHUNK_BYTES = 1024 * 1024
DIRECTORY_OPEN_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
SINGLE_LINK_COUNT = 1


class UnsafeDeletionError(RuntimeError):
    """The requested removal was unsafe, failed, or could not be confirmed."""


def _check_pair(record: FileRecord, kept: FileRecord) -> None:
    if record.path == kept.path or (record.device, record.inode) == (kept.device, kept.inode):
        raise UnsafeDeletionError("The duplicate and kept file refer to the same physical file.")
    if record.size <= 0 or record.size != kept.size or record.digest != kept.digest:
        raise UnsafeDeletionError("The duplicate and kept scan records do not identify matching nonempty files.")


@contextmanager
def _open_without_links(path: str) -> Iterator[int]:
    parts = PurePosixPath(path).parts
    if not path.startswith("/") or ".." in parts or len(parts) < 2:
        raise UnsafeDeletionError(f"A normal absolute file path is required: {path}")
    directory_descriptor = os.open("/", DIRECTORY_OPEN_FLAGS)
    file_descriptor = None
    try:
        for component in parts[1:-1]:
            next_directory = os.open(component, DIRECTORY_OPEN_FLAGS, dir_fd=directory_descriptor)
            os.close(directory_descriptor)
            directory_descriptor = next_directory
        file_descriptor = os.open(parts[-1], FILE_OPEN_FLAGS, dir_fd=directory_descriptor)
        yield file_descriptor
    finally:
        if file_descriptor is not None:
            os.close(file_descriptor)
        os.close(directory_descriptor)


def _check_snapshot(descriptor: int, record: FileRecord, role: str) -> None:
    current = os.fstat(descriptor)
    if not stat.S_ISREG(current.st_mode):
        raise UnsafeDeletionError(f"The {role} is not a regular file: {record.path}")
    expected = (record.device, record.inode, record.size, record.modified_ns, record.changed_ns)
    observed = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)
    if observed != expected:
        raise UnsafeDeletionError(f"The {role} changed or was replaced since scanning: {record.path}")
    if role == "duplicate" and current.st_nlink != SINGLE_LINK_COUNT:
        raise UnsafeDeletionError(f"The duplicate has hard-link aliases and cannot be removed: {record.path}")


def _check_digest(descriptor: int, record: FileRecord, role: str) -> None:
    _check_snapshot(descriptor, record, role)
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    while chunk := os.read(descriptor, HASH_CHUNK_BYTES):
        digest.update(chunk)
    _check_snapshot(descriptor, record, role)
    if digest.hexdigest() != record.digest:
        raise UnsafeDeletionError(f"The {role} content no longer matches its scanned SHA-256: {record.path}")


def _check_current_path(record: FileRecord, role: str) -> None:
    with _open_without_links(record.path) as descriptor:
        _check_snapshot(descriptor, record, role)


def _perform_trash(path: str, trash_function: Callable[[str], None]) -> None:
    try:
        trash_function(path)
    except Exception as error:
        raise UnsafeDeletionError(f"Trash failed for {path}: {error}") from error
    try:
        os.lstat(path)
    except FileNotFoundError:
        return
    raise UnsafeDeletionError(f"Trash did not remove the original path, so success cannot be confirmed: {path}")


def validate_and_trash(record: FileRecord, kept: FileRecord,
                       trash_function: Callable[[str], None]) -> None:
    """Validate both scan snapshots and confirm Trash and survivor before returning.

    File descriptors remain open across streamed validation and the Trash call.
    All path components reject symlinks. Identity and change metadata are checked
    again immediately before action; the survivor is rehashed afterwards.
    GIO operates on a pathname, so arbitrary concurrent renames/edits cannot be
    locked out atomically. A post-action failure may mean the duplicate is already
    in Trash; callers must report that uncertainty and retain the review row.
    """
    _check_pair(record, kept)
    try:
        with _open_without_links(kept.path) as kept_descriptor:
            with _open_without_links(record.path) as candidate_descriptor:
                _check_digest(kept_descriptor, kept, "kept file")
                _check_digest(candidate_descriptor, record, "duplicate")
                _check_current_path(kept, "kept file")
                _check_current_path(record, "duplicate")
                _check_snapshot(kept_descriptor, kept, "kept file")
                _check_snapshot(candidate_descriptor, record, "duplicate")
                _perform_trash(record.path, trash_function)
                try:
                    _check_digest(kept_descriptor, kept, "kept file")
                    _check_current_path(kept, "kept file")
                except (OSError, UnsafeDeletionError) as error:
                    raise UnsafeDeletionError(
                        f"The duplicate left its original path, but the kept survivor could not be "
                        f"confirmed. Check Trash and rescan before continuing: {error}"
                    ) from error
    except OSError as error:
        raise UnsafeDeletionError(f"Cannot safely access the duplicate or kept file: {error}") from error
