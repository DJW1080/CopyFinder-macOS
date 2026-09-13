"""Measure a real scan of disposable files; retain only JSON measurements."""

import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from copyfinder.core import ScanOptions, scan

FILES_PER_DIRECTORY = 1_000
DUPLICATE_INTERVAL = 50
DEFAULT_FILE_COUNT = 20_000


def memory_status():
    values = {}
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith(('VmRSS:', 'VmHWM:')):
            name, amount, unit = line.split()
            values[name.rstrip(':')] = int(amount)
    return values


def main():
    count = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_FILE_COUNT
    initial_memory = memory_status()
    with tempfile.TemporaryDirectory(prefix='copyfinder-benchmark-') as temporary:
        root = Path(temporary)
        for number in range(count):
            directory = root / f'{number // FILES_PER_DIRECTORY:04d}'
            directory.mkdir(exist_ok=True)
            identity = number - 1 if number % DUPLICATE_INTERVAL == 1 else number
            (directory / f'{number:08d}.bin').write_bytes(identity.to_bytes(16, 'big'))
        started = time.monotonic()
        result = scan(str(root), ScanOptions(), threading.Event(), lambda _: None)
        print(json.dumps({'fixture_files': count, 'scanned_physical_files': result.scanned_files,
                          'duplicate_groups': len(result.groups),
                          'duplicates': sum(len(group.files) - 1 for group in result.groups),
                          'limit_reached': result.limit_reached,
                          'scan_seconds': round(time.monotonic() - started, 3),
                          'initial_memory_kib': initial_memory,
                          'final_memory_kib': memory_status()}))


if __name__ == '__main__':
    main()
