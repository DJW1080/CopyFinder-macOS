"""Streaming hashes and bounded image-header inspection for immutable snapshots."""

from dataclasses import dataclass
import hashlib
import io
import os
from threading import Event
import warnings

from PIL import Image, UnidentifiedImageError

from .traversal import FileSnapshot, check_cancelled, open_regular_file, same_snapshot

HASH_CHUNK_BYTES = 1024 * 1024
IMAGE_METADATA_READ_BUDGET = 1024 * 1024
IMAGE_FORMATS = ("JPEG", "PNG", "BMP", "GIF", "TIFF", "WEBP")


@dataclass(frozen=True, slots=True)
class HashResult:
    digest: str
    width: int | None = None
    height: int | None = None


class _MetadataBudgetExceeded(Exception):
    """Stop a decoder before its requested reads exceed the metadata budget."""


class _MetadataReader(io.BufferedIOBase):
    def __init__(self, stream, byte_budget: int):
        self._stream = stream
        self._remaining_bytes = byte_budget

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._stream.tell()

    def seek(self, offset: int, whence: int = os.SEEK_SET) -> int:
        return self._stream.seek(offset, whence)

    def _bytes_to_end(self) -> int:
        position = self.tell()
        end = self.seek(0, os.SEEK_END)
        self.seek(position)
        return max(0, end - position)

    def read(self, amount: int = -1) -> bytes:
        if amount is None or amount < 0:
            amount = self._bytes_to_end()
        if amount > self._remaining_bytes:
            raise _MetadataBudgetExceeded
        contents = self._stream.read(amount)
        self._remaining_bytes -= len(contents)
        return contents

    def readinto(self, buffer) -> int:
        contents = self.read(len(buffer))
        buffer[:len(contents)] = contents
        return len(contents)


def image_dimensions(stream) -> tuple[int | None, int | None]:
    """Return unknown dimensions if header inspection needs over 1 MiB of reads.

    Some image plugins request the entire file even to obtain dimensions. The
    wrapper measures seekable length before such reads and limits cumulative
    bytes, including repeated reads after seeking; the content hash is unchanged
    when image metadata exceeds this budget.
    """
    try:
        stream.seek(0)
        with warnings.catch_warnings(), _MetadataReader(stream, IMAGE_METADATA_READ_BUDGET) as metadata:
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(metadata, formats=IMAGE_FORMATS) as picture:
                return picture.size
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError,
            Image.DecompressionBombError, Image.DecompressionBombWarning, _MetadataBudgetExceeded):
        return None, None


def hash_stream(stream, cancel: Event) -> str:
    digest = hashlib.sha256()
    while True:
        check_cancelled(cancel)
        chunk = stream.read(HASH_CHUNK_BYTES)
        if not chunk:
            return digest.hexdigest()
        digest.update(chunk)


def hash_snapshot(snapshot: FileSnapshot, cancel: Event) -> HashResult | None:
    """Return no hash when identity or metadata changes, or reading fails."""
    check_cancelled(cancel)
    try:
        with open_regular_file(snapshot.path) as stream:
            if not same_snapshot(snapshot, os.fstat(stream.fileno())):
                return None
            digest = hash_stream(stream, cancel)
            width, height = image_dimensions(stream)
            if not same_snapshot(snapshot, os.fstat(stream.fileno())):
                return None
            # Reopening catches a pathname replacement while the original inode was held open.
            with open_regular_file(snapshot.path) as current:
                if not same_snapshot(snapshot, os.fstat(current.fileno())):
                    return None
            check_cancelled(cancel)
            return HashResult(digest, width, height)
    except OSError:
        return None
