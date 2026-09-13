"""Exercise the frozen app in an isolated fixture and record native evidence."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from threading import Event
import uuid

ACCEPTANCE_TIMEOUT_SECONDS = 90
FIXTURE_CONTENT = b'CopyFinder native bundle acceptance fixture\n'
EVENT_ITERATION_LIMIT = 100


def run_native_acceptance(report_path):
    if sys.platform != 'darwin' or not getattr(sys, 'frozen', False):
        raise RuntimeError('Native acceptance must execute inside the frozen macOS app')
    from copyfinder.core import ScanOptions, scan
    from copyfinder.deletion import validate_and_trash
    from copyfinder.macos import trash_with_result
    from copyfinder.app import CopyFinderApplication
    from gi.repository import GLib
    tempfile.tempdir = str(Path(tempfile.gettempdir()).resolve())
    application = CopyFinderApplication()
    if not application.register(None):
        raise RuntimeError('GTK application registration failed')
    application.activate()
    context = GLib.MainContext.default()
    for _ in range(EVENT_ITERATION_LIMIT):
        if not context.pending():
            break
        context.iteration(False)
    if application.window is None or not application.window.get_visible():
        raise RuntimeError('Bundled GTK window did not become visible')
    application.window.close()
    application.quit()
    # Only this generated UUID file is moved; the native Trash location is returned.
    with tempfile.TemporaryDirectory(prefix='copyfinder-native-') as directory:
        root = Path(directory)
        kept_path = root / 'keeper.txt'
        duplicate_path = root / f'copyfinder-acceptance-{uuid.uuid4()}.txt'
        kept_path.write_bytes(FIXTURE_CONTENT)
        duplicate_path.write_bytes(FIXTURE_CONTENT)
        result = scan(str(root), ScanOptions(), Event(), lambda message: None)
        if len(result.groups) != 1 or len(result.groups[0].files) != 2:
            raise RuntimeError(f'Unexpected duplicate scan result: {result}')
        records = {record.path: record for record in result.groups[0].files}
        trashed = []
        def native_trash(path):
            trashed.append(Path(trash_with_result(path)))
        validate_and_trash(records[str(duplicate_path)], records[str(kept_path)], native_trash)
        if len(trashed) != 1 or trashed[0].read_bytes() != FIXTURE_CONTENT:
            raise RuntimeError('Native Trash did not preserve fixture contents')
        if kept_path.read_bytes() != FIXTURE_CONTENT or duplicate_path.exists():
            raise RuntimeError('Native Trash survivor verification failed')
        # Hard-link creation refuses to overwrite any unexpected replacement path.
        os.link(trashed[0], duplicate_path)
        trashed[0].unlink()
        if duplicate_path.read_bytes() != FIXTURE_CONTENT:
            raise RuntimeError('Fixture restoration failed')
    report_path.write_text(json.dumps({'passed': True, 'frozen': True,
        'macos': platform.mac_ver()[0], 'architecture': platform.machine(),
        'checks': ['GTK window visible', 'exact duplicate scan', 'validated native Trash',
                   'Trash contents intact', 'keeper preserved', 'fixture restored'],
        'manual_catalina_acceptance': 'required'}, indent=2) + '\n')


def main():
    bundle, report = (Path(argument).resolve() for argument in sys.argv[1:])
    with tempfile.TemporaryDirectory(prefix='copyfinder-bundle-test-') as directory:
        root = Path(directory).resolve()
        environment = {'HOME': str(Path.home()), 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin',
                       'TMPDIR': str(root), 'COPYFINDER_CONFIG_HOME': str(root / 'config'),
                       'COPYFINDER_STATE_HOME': str(root / 'state'), 'GDK_BACKEND': 'macos'}
        subprocess.run([str(bundle / 'Contents/MacOS/CopyFinder'), '--macos-acceptance', str(report)],
                       env=environment, cwd=root, timeout=ACCEPTANCE_TIMEOUT_SECONDS, check=True)
    evidence = json.loads(report.read_text())
    if evidence.get('passed') is not True or evidence.get('frozen') is not True:
        raise RuntimeError('Missing successful frozen app acceptance evidence')


if __name__ == '__main__':
    main()
