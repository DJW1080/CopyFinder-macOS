"""Deterministic filename, timestamp, folder and image keep policies."""

from pathlib import Path
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import FileRecord

KEEP_RULES = (
    "Original", "Shortest name", "Oldest file", "Newest file", "Folder", "Highest Resolution",
)
DEFAULT_KEEP_RULE = KEEP_RULES[0]
COPY_SUFFIX = re.compile(r"(?: - copy| copy|_copy)$", re.IGNORECASE)
NUMBERED_SUFFIX = re.compile(r"\(\d+\)$")
NO_SUFFIX_SCORE = 0
COPY_SUFFIX_SCORE = 10
NUMBERED_SUFFIX_SCORE = 20


def _path_key(record: "FileRecord") -> str:
    return record.path


def _suffix_score(stem: str) -> int:
    if COPY_SUFFIX.search(stem):
        return COPY_SUFFIX_SCORE
    if NUMBERED_SUFFIX.search(stem):
        return NUMBERED_SUFFIX_SCORE
    return NO_SUFFIX_SCORE


def _original_key(record: "FileRecord") -> tuple:
    stem = Path(record.path).stem
    return _suffix_score(stem), len(stem), record.modified_ns, record.path


def _within_folder(path: str, preferred_folder: str) -> bool:
    if not preferred_folder:
        return False
    folder = os.path.abspath(os.path.expanduser(preferred_folder))
    return path.startswith(folder.rstrip(os.sep) + os.sep)


def _policy_key(record: "FileRecord", rule: str, preferred_folder: str) -> tuple:
    original_key = _original_key(record)
    if rule == "Shortest name":
        return len(Path(record.path).stem), *original_key
    if rule == "Oldest file":
        return record.modified_ns, *original_key
    if rule == "Newest file":
        return -record.modified_ns, *original_key
    if rule == "Folder":
        return not _within_folder(record.path, preferred_folder), *original_key
    if rule == "Highest Resolution":
        area = (record.width or 0) * (record.height or 0)
        return -area, *original_key
    return original_key


def order_files(files: tuple["FileRecord", ...], rule: str,
                preferred_folder: str = "") -> tuple["FileRecord", ...]:
    """Place the preferred survivor first; remaining rows use stable path order."""
    if not files:
        return ()
    kept = min(files, key=lambda record: _policy_key(record, rule, preferred_folder))
    return (kept, *sorted((record for record in files if record is not kept), key=_path_key))
