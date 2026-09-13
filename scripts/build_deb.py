#!/usr/bin/python3
"""Build a local Debian package without installing or invoking network tools."""

import ast
from pathlib import Path
import shutil
import subprocess
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT / 'dist'
PACKAGE = 'copyfinder'
DEPENDENCIES = 'python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0 (>= 4.10), python3-pil'


def version():
    module = ast.parse((PROJECT / PACKAGE / '__init__.py').read_text())
    for statement in module.body:
        if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == 'VERSION' for target in statement.targets):
            return ast.literal_eval(statement.value)
    raise ValueError('No application VERSION constant was found.')


def copy_file(source, root, relative_destination, mode=0o644):
    destination = root / relative_destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def build():
    OUTPUT.mkdir(exist_ok=True)
    package_version = version()
    artifact = OUTPUT / f'{PACKAGE}_{package_version}_all.deb'
    with tempfile.TemporaryDirectory(prefix='copyfinder-package-') as directory:
        root = Path(directory)
        library = root / 'usr/lib/copyfinder/copyfinder'
        shutil.copytree(PROJECT / PACKAGE, library,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        for file in library.rglob('*'):
            file.chmod(0o755 if file.is_dir() else 0o644)
        copy_file(PROJECT / 'scripts/copyfinder', root, 'usr/bin/copyfinder', 0o755)
        copy_file(PROJECT / 'packaging/copyfinder.desktop', root, 'usr/share/applications/copyfinder.desktop')
        copy_file(PROJECT / 'copyfinder/assets/copyfinder.png', root,
                  'usr/share/icons/hicolor/256x256/apps/copyfinder.png')
        for filename in ('README.md', 'LICENSE', 'NOTICE.md'):
            copy_file(PROJECT / filename, root, f'usr/share/doc/copyfinder/{filename}')
        size_kib = sum(path.stat().st_size for path in root.rglob('*') if path.is_file()) // 1024 + 1
        control = root / 'DEBIAN/control'
        control.parent.mkdir()
        control.write_text(
            f'Package: {PACKAGE}\nVersion: {package_version}\nArchitecture: all\n'
            'Section: utils\nPriority: optional\n'
            'Maintainer: CopyFinder local package <nobody@localhost>\n'
            f'Depends: {DEPENDENCIES}\nInstalled-Size: {size_kib}\n'
            'Description: Native Linux duplicate file finder\n'
            ' Independently implemented GTK desktop application for exact size/SHA-256\n'
            ' duplicate review, compatible reports, and validated native Trash operations.\n')
        subprocess.run(['dpkg-deb', '--root-owner-group', '--build', str(root), str(artifact)], check=True)
    print(artifact)


if __name__ == '__main__':
    build()
