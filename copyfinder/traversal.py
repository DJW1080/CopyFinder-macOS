"""Descriptor-based Linux traversal without following directory or file links."""

from dataclasses import dataclass
import errno
import os
import stat
from threading import Event
from typing import Callable, Iterator

SYSTEM_DIRECTORIES = ("/dev", "/proc", "/sys", "/run")
ALWAYS_EXCLUDED_DIRECTORIES = ("/dev", "/proc", "/sys")
VIRTUAL_FILESYSTEMS = frozenset({
    "proc", "sysfs", "devtmpfs", "devpts", "cgroup", "cgroup2", "securityfs", "debugfs",
    "tracefs", "pstore", "configfs", "mqueue", "hugetlbfs", "fusectl", "bpf", "rpc_pipefs",
    "binfmt_misc", "nsfs", "efivarfs",
})
DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
FILE_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
MOUNT_ESCAPE_SEQUENCES = {"\\040": " ", "\\011": "\t", "\\012": "\n", "\\134": "\\"}
MOUNTINFO_PATH_INDEX = 4


class ScanCancelled(Exception):
    """Raised cooperatively when a scan is cancelled."""


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    path: str
    size: int
    modified_ns: int
    changed_ns: int
    device: int
    inode: int


@dataclass
class _DirectoryFrame:
    path: str
    descriptor: int
    iterator: Iterator[os.DirEntry]
    identity: tuple[int, int]

    def close(self):
        self.iterator.close()
        os.close(self.descriptor)


def check_cancelled(cancel: Event):
    if cancel.is_set():
        raise ScanCancelled("Scan cancelled")


def same_snapshot(snapshot: FileSnapshot, information: os.stat_result) -> bool:
    return (stat.S_ISREG(information.st_mode)
            and snapshot.size == information.st_size
            and snapshot.modified_ns == information.st_mtime_ns
            and snapshot.changed_ns == information.st_ctime_ns
            and snapshot.device == information.st_dev
            and snapshot.inode == information.st_ino)


def open_directory(path: str) -> int:
    """Reject symlinks in every component, including ancestors of the scan root."""
    absolute_path = os.path.abspath(path)
    descriptor = os.open(os.sep, DIRECTORY_OPEN_FLAGS)
    try:
        for component in absolute_path.split(os.sep):
            if component:
                next_descriptor = os.open(component, DIRECTORY_OPEN_FLAGS, dir_fd=descriptor)
                os.close(descriptor)
                descriptor = next_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def open_regular_file(path: str):
    parent_descriptor = open_directory(os.path.dirname(path))
    try:
        descriptor = os.open(os.path.basename(path), FILE_OPEN_FLAGS, dir_fd=parent_descriptor)
    finally:
        os.close(parent_descriptor)
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        os.close(descriptor)
        raise OSError(errno.EINVAL, "Not a regular file", path)
    return os.fdopen(descriptor, "rb")


def _decode_mount_path(path: str) -> str:
    for encoded, decoded in MOUNT_ESCAPE_SEQUENCES.items():
        path = path.replace(encoded, decoded)
    return path


def virtual_mounts() -> tuple[str, ...]:
    mounts = set(ALWAYS_EXCLUDED_DIRECTORIES)
    try:
        with open("/proc/self/mountinfo", encoding="utf-8", errors="surrogateescape") as stream:
            for line in stream:
                before, separator, after = line.partition(" - ")
                fields = before.split()
                filesystem_fields = after.split()
                if separator and len(fields) > MOUNTINFO_PATH_INDEX and filesystem_fields:
                    if filesystem_fields[0] in VIRTUAL_FILESYSTEMS:
                        mounts.add(_decode_mount_path(fields[MOUNTINFO_PATH_INDEX]))
    except OSError:
        # The explicit proc/sys/dev fallback still applies without mounted procfs.
        pass
    return tuple(sorted(mounts))


def _inside_any(path: str, excluded: tuple[str, ...]) -> bool:
    return any(path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)
               for folder in excluded)


def _open_frame(path: str, descriptor: int) -> _DirectoryFrame:
    try:
        information = os.fstat(descriptor)
        return _DirectoryFrame(path, descriptor, os.scandir(descriptor),
                               (information.st_dev, information.st_ino))
    except BaseException:
        os.close(descriptor)
        raise


def _child_frame(parent: _DirectoryFrame, name: str, path: str,
                 expected: os.stat_result) -> _DirectoryFrame:
    descriptor = os.open(name, DIRECTORY_OPEN_FLAGS, dir_fd=parent.descriptor)
    frame = _open_frame(path, descriptor)
    if frame.identity != (expected.st_dev, expected.st_ino):
        frame.close()
        raise OSError(errno.ESTALE, "Directory changed during traversal", path)
    return frame


def iter_files(root: str, options, cancel: Event,
               skipped: Callable[[str], None],
               excluded_paths: tuple[str, ...] = ()) -> Iterator[FileSnapshot]:
    """Retain one iterator per directory depth, not one entry per discovered file.

    A skipped directory is counted once; its descendants are never enumerated.
    Files filtered by name/type/size and inaccessible entries are counted once.
    """
    excluded = virtual_mounts() + (SYSTEM_DIRECTORIES if options.skip_system else ()) + excluded_paths
    if _inside_any(root, excluded):
        skipped(root)
        return
    stack = [_open_frame(root, open_directory(root))]
    ancestor_identities = {stack[0].identity}
    try:
        while stack:
            check_cancelled(cancel)
            parent = stack[-1]
            try:
                entry = next(parent.iterator)
            except StopIteration:
                ancestor_identities.remove(parent.identity)
                stack.pop().close()
                continue
            except OSError:
                skipped(parent.path)
                ancestor_identities.remove(parent.identity)
                stack.pop().close()
                continue
            path = os.path.join(parent.path, entry.name)
            if (options.skip_hidden and entry.name.startswith(".")) or _inside_any(path, excluded):
                skipped(path)
                continue
            try:
                information = entry.stat(follow_symlinks=False)
                if stat.S_ISDIR(information.st_mode):
                    frame = _child_frame(parent, entry.name, path, information)
                    if frame.identity in ancestor_identities:
                        frame.close()
                        skipped(path)
                    else:
                        ancestor_identities.add(frame.identity)
                        stack.append(frame)
                elif (not stat.S_ISREG(information.st_mode) or information.st_size == 0
                      or information.st_size < options.minimum_bytes
                      or os.path.splitext(entry.name)[1].casefold() in options.excluded_extensions):
                    skipped(path)
                else:
                    yield FileSnapshot(path, information.st_size, information.st_mtime_ns,
                                       information.st_ctime_ns, information.st_dev, information.st_ino)
            except OSError:
                skipped(path)
    finally:
        for frame in reversed(stack):
            frame.close()
