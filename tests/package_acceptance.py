"""Exercise dpkg in a disposable root, using host dependency status read-only."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
PACKAGE = PROJECT / 'dist/copyfinder_0.1.0_all.deb'


def run(*arguments, **options):
    result = subprocess.run(arguments, check=True, capture_output=True, text=True, **options)
    if result.stdout:
        print(result.stdout, end='')
    if result.stderr:
        print(result.stderr, end='', file=sys.stderr)


def main():
    with tempfile.TemporaryDirectory(prefix='copyfinder-dpkg-test-') as directory:
        work = Path(directory)
        root = work / 'root'
        database = root / 'var/lib/dpkg'
        database.mkdir(parents=True)
        shutil.copyfile('/var/lib/dpkg/status', database / 'status')
        (database / 'info').mkdir()
        for listing in Path('/var/lib/dpkg/info').glob('*.list'):
            shutil.copyfile(listing, database / 'info' / listing.name)
        package_log = work / 'dpkg.log'
        prior = work / 'prior'
        (prior / 'DEBIAN').mkdir(parents=True)
        (prior / 'DEBIAN/control').write_text(
            'Package: copyfinder\nVersion: 0.0.0\nArchitecture: all\n'
            'Maintainer: Local test <nobody@localhost>\nDescription: Disposable upgrade fixture\n')
        stale = prior / 'usr/lib/copyfinder/obsolete-test-file'
        stale.parent.mkdir(parents=True)
        stale.write_text('This fixture must disappear on upgrade.')
        prior_deb = work / 'prior.deb'
        run('dpkg-deb', '--root-owner-group', '--build', str(prior), str(prior_deb))
        run('dpkg', f'--root={root}', f'--log={package_log}', '--install', str(prior_deb))
        run('dpkg', f'--root={root}', f'--log={package_log}', '--install', str(PACKAGE))
        if (root / 'usr/lib/copyfinder/obsolete-test-file').exists():
            raise AssertionError('Upgrade left obsolete package files.')
        library = root / 'usr/lib/copyfinder/copyfinder'
        checked = 0
        for source in (PROJECT / 'copyfinder').rglob('*'):
            if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
                installed = library / source.relative_to(PROJECT / 'copyfinder')
                if hashlib.sha256(source.read_bytes()).digest() != hashlib.sha256(installed.read_bytes()).digest():
                    raise AssertionError(f'Installed content mismatch: {source.name}')
                checked += 1
        environment = dict(os.environ, HOME=str(work / 'home'), XDG_CONFIG_HOME=str(work / 'config'),
                           XDG_STATE_HOME=str(work / 'state'), PYTHONDONTWRITEBYTECODE='1')
        # Desktop bus authentication requires the real user's credentials.
        preload = environment.get('LD_PRELOAD', '')
        preload = ' '.join(library for library in preload.replace(':', ' ').split() if 'fakeroot' not in library)
        if preload:
            environment['LD_PRELOAD'] = preload
        else:
            environment.pop('LD_PRELOAD', None)
        environment.pop('FAKEROOTKEY', None)
        run(str(root / 'usr/bin/copyfinder'), '--version', env=environment)
        run('desktop-file-validate', str(root / 'usr/share/applications/copyfinder.desktop'))
        environment['PYTHONPATH'] = str(root / 'usr/lib/copyfinder')
        gui_probe = '''
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from copyfinder.app import apply_style
from copyfinder.window import MainWindow
Gtk.init()
application = Gtk.Application(application_id='au.com.technification.CopyFinder.PackageTest')
application.register(None)
apply_style()
window = MainWindow(application)
window.present()
loop = GLib.MainLoop()
def finish():
    assert window.get_mapped(), 'Packaged window was not mapped'
    window.destroy()
    loop.quit()
    return GLib.SOURCE_REMOVE
GLib.timeout_add(300, finish)
loop.run()
print('PASS: packaged GTK window presented and closed on Mint')
'''
        run('/usr/bin/python3', '-c', gui_probe, env=environment, cwd=work)
        marker = root / 'home/example/.config/copyfinder/settings.json'
        marker.parent.mkdir(parents=True)
        marker.write_text('{"limit": 17}')
        run('dpkg', f'--root={root}', f'--log={package_log}', '--remove', 'copyfinder')
        if (root / 'usr/bin/copyfinder').exists() or not marker.exists():
            raise AssertionError('Removal did not preserve the expected package/user-file boundary.')
        if (root / 'usr/lib/copyfinder').exists():
            raise AssertionError('Removal left application files behind.')
        print(f'PASS: isolated dpkg install, fixture upgrade, {checked} file hashes, launcher, desktop entry and removal.')
        print('Host dependency status was copied read-only; runtime libraries came from this Mint host. Host installation was not changed.')


if __name__ == '__main__':
    main()
