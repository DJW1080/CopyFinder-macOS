"""Bounded asynchronous image previews; document types use bundled artwork."""

import io
import os
import stat
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gi
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, GLib
from PIL import Image, UnidentifiedImageError

ASSETS = Path(__file__).parent / 'assets'
PREVIEW_SIZE = 50
MAX_PREVIEW_PIXELS = 40_000_000
MAX_PREVIEW_FILE_BYTES = 32 * 1024 * 1024
MAX_CACHE_ITEMS = 128
MAX_PENDING_PREVIEWS = 32
PREVIEW_WORKERS = 2
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tif', '.tiff', '.webp'}
CATEGORIES = {
    'audio': 'mp3 flac wav m4a aac ogg wma aiff alac',
    'word': 'doc docx rtf odt', 'pdf': 'pdf', 'spreadsheet': 'xls xlsx csv ods',
    'presentation': 'ppt pptx odp', 'video': 'mp4 mkv mov avi wmv m4v webm',
    'archive': 'zip 7z rar tar gz bz2', 'text': 'txt md log nfo ini cfg',
    'code': 'cs js ts json xml html css ps1 py sql',
}


def icon_path(path):
    extension = Path(path).suffix.lower()
    category = 'image' if extension in IMAGE_EXTENSIONS else next(
        (name for name, extensions in CATEGORIES.items() if extension.lstrip('.') in extensions.split()), 'generic')
    return str(ASSETS / f'file-{category}.png')


def decode_preview(record):
    if record.size > MAX_PREVIEW_FILE_BYTES:
        return None
    descriptor = os.open(record.path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as source:
        current = os.fstat(source.fileno())
        if (not stat.S_ISREG(current.st_mode) or current.st_ino != record.inode
                or current.st_dev != record.device or current.st_mtime_ns != record.modified_ns
                or current.st_size > MAX_PREVIEW_FILE_BYTES):
            return None
        with Image.open(source) as picture:
            if picture.width * picture.height > MAX_PREVIEW_PIXELS:
                return None
            picture.thumbnail((PREVIEW_SIZE, PREVIEW_SIZE))
            output = io.BytesIO()
            picture.convert('RGBA').save(output, format='PNG')
            return output.getvalue()


class PreviewCache:
    def __init__(self):
        self.cache = OrderedDict()
        self.pending = {}
        self.executor = ThreadPoolExecutor(max_workers=PREVIEW_WORKERS, thread_name_prefix='preview')
        self.closed = False

    def load(self, record, callback):
        if self.closed or Path(record.path).suffix.lower() not in IMAGE_EXTENSIONS:
            return
        key = (record.path, record.modified_ns, record.inode)
        if key in self.cache:
            self.cache.move_to_end(key)
            # A cached result must wait until GTK has attached the new row child.
            GLib.idle_add(self._notify, callback, self.cache[key])
            return
        if key in self.pending:
            self.pending[key].append(callback)
            return
        if len(self.pending) >= MAX_PENDING_PREVIEWS:
            return
        self.pending[key] = [callback]
        future = self.executor.submit(decode_preview, record)
        future.add_done_callback(lambda result: GLib.idle_add(self._deliver, key, result))

    def _deliver(self, key, future):
        callbacks = self.pending.pop(key, [])
        if self.closed or future.cancelled():
            return GLib.SOURCE_REMOVE
        try:
            data = future.result()
            texture = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data)) if data else None
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, GLib.Error):
            texture = None
        self.cache[key] = texture
        while len(self.cache) > MAX_CACHE_ITEMS:
            self.cache.popitem(last=False)
        for callback in callbacks:
            self._notify(callback, texture)
        return GLib.SOURCE_REMOVE

    def _notify(self, callback, texture):
        if not self.closed:
            callback(texture)
        return GLib.SOURCE_REMOVE

    def close(self):
        self.closed = True
        self.pending.clear()
        self.executor.shutdown(wait=False, cancel_futures=True)
