"""Run the shared suite with canonical temporary paths on macOS."""
from pathlib import Path
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


def main():
    sys.path.insert(0, str(PROJECT))
    # macOS /var aliases /private/var; fixtures must not accidentally test symlinks.
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    suite = unittest.defaultTestLoader.discover(str(PROJECT / 'tests'))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
