"""Memory-bounded, exact-content duplicate scanning for Linux filesystems."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import os
import sqlite3
import stat
import tempfile
from threading import Event
from typing import Callable

from .hashing import HashResult, hash_snapshot
from .keep import DEFAULT_KEEP_RULE, KEEP_RULES, order_files
from .traversal import FileSnapshot, ScanCancelled, check_cancelled, iter_files

DEFAULT_DUPLICATE_LIMIT = 500
MINIMUM_DUPLICATE_LIMIT = 1
MAXIMUM_DUPLICATE_LIMIT = 10000
DEFAULT_WORKERS = 2
MINIMUM_WORKERS = 1
MAXIMUM_WORKERS = 16
PENDING_WORK_PER_WORKER = 2
INVENTORY_PROGRESS_INTERVAL = 256
HASH_PROGRESS_INTERVAL = 32
SQLITE_CACHE_KIB = 2048
SNAPSHOT_COLUMNS = "path, size, modified_ns, changed_ns, device, inode"
SNAPSHOT_FIELD_COUNT = 6


@dataclass(frozen=True, slots=True)
class FileRecord:
    path: str
    size: int
    modified_ns: int
    changed_ns: int
    device: int
    inode: int
    digest: str
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    group_id: int
    files: tuple[FileRecord, ...]


@dataclass(frozen=True, slots=True)
class ScanOptions:
    limit: int = DEFAULT_DUPLICATE_LIMIT
    workers: int = DEFAULT_WORKERS
    keep_rule: str = DEFAULT_KEEP_RULE
    preferred_folder: str = ""
    minimum_bytes: int = 0
    skip_hidden: bool = True
    skip_system: bool = True
    excluded_extensions: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "limit", max(MINIMUM_DUPLICATE_LIMIT,
                           min(MAXIMUM_DUPLICATE_LIMIT, int(self.limit))))
        object.__setattr__(self, "workers", max(MINIMUM_WORKERS, min(MAXIMUM_WORKERS, int(self.workers))))
        object.__setattr__(self, "minimum_bytes", max(0, int(self.minimum_bytes)))
        if self.keep_rule not in KEEP_RULES:
            object.__setattr__(self, "keep_rule", DEFAULT_KEEP_RULE)
        extensions = {"." + extension.strip().casefold().lstrip(".")
                      for extension in self.excluded_extensions if extension.strip().lstrip(".")}
        object.__setattr__(self, "excluded_extensions", tuple(sorted(extensions)))


@dataclass(frozen=True, slots=True)
class ScanResult:
    groups: tuple[DuplicateGroup, ...]
    limit_reached: bool
    scanned_files: int
    skipped_files: int


@dataclass
class _ScanCounts:
    scanned: int = 0
    skipped: int = 0
    hashed: int = 0

    def skip(self, path: str):
        self.skipped += 1


@dataclass
class _WorkerCancellation:
    user_cancel: Event
    workers_finished: Event

    def is_set(self) -> bool:
        return self.user_cancel.is_set() or self.workers_finished.is_set()


def _create_inventory(database_path: str) -> sqlite3.Connection:
    database = sqlite3.connect(database_path)
    database.execute(f"PRAGMA cache_size = -{SQLITE_CACHE_KIB}")
    database.execute("PRAGMA temp_store = FILE")
    database.execute("""CREATE TABLE files (
        path BLOB NOT NULL, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
        changed_ns INTEGER NOT NULL, device TEXT NOT NULL, inode TEXT NOT NULL,
        PRIMARY KEY (device, inode))""")
    database.execute("CREATE INDEX files_by_size ON files(size, path)")
    database.execute("""CREATE TABLE hashed (
        path BLOB NOT NULL, size INTEGER NOT NULL, modified_ns INTEGER NOT NULL,
        changed_ns INTEGER NOT NULL, device TEXT NOT NULL, inode TEXT NOT NULL,
        digest TEXT NOT NULL, width INTEGER, height INTEGER)""")
    database.execute("CREATE INDEX hashed_by_content ON hashed(size, digest)")
    return database


def _snapshot_values(snapshot: FileSnapshot) -> tuple:
    # BLOB paths preserve undecodable POSIX filenames; inode values may be unsigned.
    return (os.fsencode(snapshot.path), snapshot.size, snapshot.modified_ns, snapshot.changed_ns,
            str(snapshot.device), str(snapshot.inode))


def _snapshot_from_row(row: tuple) -> FileSnapshot:
    path, size, modified_ns, changed_ns, device, inode = row[:SNAPSHOT_FIELD_COUNT]
    return FileSnapshot(os.fsdecode(path), size, modified_ns, changed_ns, int(device), int(inode))


def _record(snapshot: FileSnapshot, result: HashResult) -> FileRecord:
    return FileRecord(snapshot.path, snapshot.size, snapshot.modified_ns, snapshot.changed_ns,
                      snapshot.device, snapshot.inode, result.digest, result.width, result.height)


def _inventory(database: sqlite3.Connection, root: str, options: ScanOptions,
               cancel: Event, progress: Callable[[str], None], counts: _ScanCounts,
               internal_directory: str):
    progress("Inventory: reading folders")
    for snapshot in iter_files(root, options, cancel, counts.skip, (internal_directory,)):
        inserted = database.execute("INSERT OR IGNORE INTO files VALUES (?, ?, ?, ?, ?, ?)",
                                    _snapshot_values(snapshot)).rowcount
        if inserted:
            counts.scanned += 1
            if counts.scanned % INVENTORY_PROGRESS_INTERVAL == 0:
                database.commit()
                progress(f"Inventory: {counts.scanned:,} files; {counts.skipped:,} skipped")
        else:
            counts.skip(snapshot.path)
            # Keep a deterministic representative even when readdir order differs.
            database.execute("""UPDATE files SET path=?, size=?, modified_ns=?, changed_ns=?
                WHERE device=? AND inode=? AND path > ?""",
                (*_snapshot_values(snapshot), os.fsencode(snapshot.path)))
    database.commit()
    check_cancelled(cancel)


def _hash_candidates(database: sqlite3.Connection, options: ScanOptions, cancel: Event):
    cursor = database.execute(f"""SELECT {SNAPSHOT_COLUMNS} FROM files
        WHERE size IN (SELECT size FROM files GROUP BY size HAVING COUNT(*) > 1)
        ORDER BY size, path""")
    pending = deque()
    workers_finished = Event()
    worker_cancel = _WorkerCancellation(cancel, workers_finished)
    executor = ThreadPoolExecutor(max_workers=options.workers, thread_name_prefix="copyfinder-hash")
    try:
        for row in cursor:
            check_cancelled(cancel)
            snapshot = _snapshot_from_row(row)
            pending.append((snapshot, executor.submit(hash_snapshot, snapshot, worker_cancel)))
            if len(pending) >= options.workers * PENDING_WORK_PER_WORKER:
                previous, future = pending.popleft()
                yield previous, future.result()
        while pending:
            check_cancelled(cancel)
            snapshot, future = pending.popleft()
            yield snapshot, future.result()
    finally:
        workers_finished.set()
        for snapshot, future in pending:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        cursor.close()


def _collect_groups(database: sqlite3.Connection, options: ScanOptions, cancel: Event,
                    progress: Callable[[str], None], counts: _ScanCounts) -> tuple:
    grouped_records = {}
    duplicate_count = 0
    limit_reached = False
    progress(f"Hashing: evaluating same-size files from {counts.scanned:,} physical files")
    check_cancelled(cancel)
    candidates = _hash_candidates(database, options, cancel)
    try:
        for snapshot, result in candidates:
            check_cancelled(cancel)
            counts.hashed += 1
            if result is None:
                counts.skip(snapshot.path)
                continue
            content_key = snapshot.size, result.digest
            previous = database.execute(f"""SELECT {SNAPSHOT_COLUMNS}, digest, width, height
                FROM hashed WHERE size=? AND digest=? LIMIT 1""", content_key).fetchone()
            if previous is not None:
                if content_key not in grouped_records:
                    first = _record(_snapshot_from_row(previous), HashResult(*previous[SNAPSHOT_FIELD_COUNT:]))
                    grouped_records[content_key] = [first]
                grouped_records[content_key].append(_record(snapshot, result))
                duplicate_count += 1
                if duplicate_count >= options.limit:
                    limit_reached = True
                    break
            else:
                database.execute("INSERT INTO hashed VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (*_snapshot_values(snapshot), result.digest, result.width, result.height))
            if counts.hashed % HASH_PROGRESS_INTERVAL == 0:
                progress(f"Hashing: {counts.hashed:,} files checked; {duplicate_count:,} duplicates")
        check_cancelled(cancel)
    finally:
        candidates.close()
    groups = tuple(DuplicateGroup(number, order_files(tuple(files), options.keep_rule, options.preferred_folder))
                   for number, files in enumerate(grouped_records.values(), start=1))
    return groups, limit_reached


def scan(root: str, options: ScanOptions, cancel: Event,
         progress: Callable[[str], None]) -> ScanResult:
    """Scan one root; counts describe eligible physical files and skipped entries.

    The temporary inventory is disk-backed. At most twice the worker count is
    queued for hashing, and review memory cannot exceed the duplicate limit plus
    one kept row per group. Reaching the limit conservatively marks an incomplete
    review, because other candidates may remain unevaluated.
    """
    check_cancelled(cancel)
    root = os.path.abspath(os.path.expanduser(root))
    if not stat.S_ISDIR(os.stat(root, follow_symlinks=False).st_mode):
        raise ValueError("Choose a real directory; symlink roots are not scanned")
    counts = _ScanCounts()
    with tempfile.TemporaryDirectory(prefix="copyfinder-scan-") as temporary:
        database = _create_inventory(os.path.join(temporary, "inventory.sqlite3"))
        try:
            _inventory(database, root, options, cancel, progress, counts, temporary)
            groups, limit_reached = _collect_groups(database, options, cancel, progress, counts)
        finally:
            database.close()
    return ScanResult(groups, limit_reached, counts.scanned, counts.skipped)
