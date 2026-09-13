"""Build a real Intel app, rejecting incompatible or externally linked Mach-O files."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
TARGET_VERSION = (10, 15)
TARGET_ARCH = 'x86_64'
MACHO_MAGICS = {bytes.fromhex(value) for value in
                ('feedface', 'cefaedfe', 'feedfacf', 'cffaedfe',
                 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
SYSTEM_LIBRARY_PREFIXES = ('/System/Library/', '/usr/lib/')
RELATIVE_LIBRARY_PREFIXES = ('@rpath/', '@loader_path/', '@executable_path/')


def run(*arguments, **options):
    return subprocess.run(arguments, check=True, text=True, capture_output=True, **options).stdout


def minimum_versions(output):
    versions = []
    command = None
    for line in output.splitlines():
        fields = line.split()
        if fields[:1] == ['cmd']:
            command = fields[1]
        if len(fields) >= 2 and ((command == 'LC_BUILD_VERSION' and fields[0] == 'minos') or
                               (command == 'LC_VERSION_MIN_MACOSX' and fields[0] == 'version')):
            versions.append(tuple(int(part) for part in fields[1].split('.')))
    return versions


def validate_load_commands(output):
    versions = minimum_versions(output)
    if not versions or any(version[:2] > TARGET_VERSION for version in versions):
        raise ValueError(f'Missing or incompatible macOS deployment target: {versions}')
    for platform_id in re.findall(r'^\s*platform\s+(\S+)', output, re.MULTILINE):
        if platform_id not in ('1', 'macos', 'MACOS'):
            raise ValueError(f'Non-macOS binary platform: {platform_id}')
    return versions


def is_system_library(path):
    return os.path.normpath(str(path)).startswith(SYSTEM_LIBRARY_PREFIXES)


def contained_path(path, bundle, require_exists=True):
    try:
        resolved = path.resolve(strict=require_exists)
    except (OSError, RuntimeError) as error:
        raise ValueError(f'Broken bundle path: {path}') from error
    if not resolved.is_relative_to(bundle.resolve()):
        raise ValueError(f'Path escapes app bundle: {path}')
    return resolved


def validate_bundle_links(bundle):
    for entry in bundle.rglob('*'):
        if entry.is_symlink():
            contained_path(entry, bundle)


def expand_loader_path(value, binary, executable):
    for prefix, directory in (('@loader_path', binary.parent),
                              ('@executable_path', executable.parent)):
        if value == prefix or value.startswith(prefix + '/'):
            return directory / value[len(prefix):].lstrip('/')
    raise ValueError(f'Unsupported relative load path: {value}')


def resolve_search_paths(search_paths, bundle, binary, executable):
    resolved = []
    for value in search_paths:
        if is_system_library(value):
            resolved.append(Path(os.path.normpath(value)))
        else:
            candidate = expand_loader_path(value, binary, executable)
            resolved.append(contained_path(candidate, bundle, require_exists=False))
    return resolved


def validate_dependencies(output, bundle=None, binary=None, executable=None,
                          search_paths=(), inherited_paths=()):
    resolved_paths = []
    if bundle is not None:
        resolved_paths = resolve_search_paths(search_paths, bundle, binary, executable)
    for line in output.splitlines()[1:]:
        dependency = line.strip().split(' (', 1)[0]
        if not dependency or is_system_library(dependency):
            continue
        if not dependency.startswith(RELATIVE_LIBRARY_PREFIXES) or bundle is None:
            raise ValueError(f'External or unsupported library dependency: {dependency}')
        if dependency.startswith('@rpath/'):
            suffix = dependency.removeprefix('@rpath/')
            candidates = [directory / suffix for directory in [*resolved_paths, *inherited_paths]]
        else:
            candidates = [expand_loader_path(dependency, binary, executable)]
        found = False
        for candidate in candidates:
            if is_system_library(candidate):
                found = True
                break
            resolved = contained_path(candidate, bundle, require_exists=False)
            if resolved.is_file():
                found = True
                break
        if not found:
            raise ValueError(f'Unresolved bundled dependency: {binary}: {dependency}')


def load_search_paths(commands):
    return re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.+) \(offset \d+\)', commands)


def inspect_bundle(bundle):
    bundle = bundle.resolve()
    validate_bundle_links(bundle)
    records = []
    executable = bundle / 'Contents/MacOS/CopyFinder'
    executable_commands = run('/usr/bin/otool', '-arch', TARGET_ARCH, '-l', str(executable))
    inherited_paths = resolve_search_paths(load_search_paths(executable_commands),
                                          bundle, executable, executable)
    for binary in sorted(bundle.rglob('*')):
        if not binary.is_file() or binary.is_symlink():
            continue
        with binary.open('rb') as stream:
            magic = stream.read(4)
        if magic not in MACHO_MAGICS:
            continue
        architectures = run('/usr/bin/lipo', '-archs', str(binary)).split()
        if TARGET_ARCH not in architectures:
            raise ValueError(f'Missing Intel slice: {binary}: {architectures}')
        commands = run('/usr/bin/otool', '-arch', TARGET_ARCH, '-l', str(binary))
        versions = validate_load_commands(commands)
        validate_dependencies(run('/usr/bin/otool', '-arch', TARGET_ARCH, '-L', str(binary)),
                              bundle, binary, executable, load_search_paths(commands), inherited_paths)
        records.append({'path': str(binary.relative_to(bundle)), 'architectures': architectures,
                        'minimum_versions': versions})
    if not records:
        raise ValueError('No Mach-O binaries in app; refusing a source-only distribution')
    return records


def main():
    if sys.platform != 'darwin' or platform.machine() != TARGET_ARCH:
        raise SystemExit('Build requires an Intel macOS machine with prepared MacPorts dependencies.')
    sys.path.insert(0, str(PROJECT))
    from copyfinder import VERSION
    destination = PROJECT / 'dist/macos'
    destination.mkdir(parents=True, exist_ok=True)
    if (destination / 'CopyFinder.app').exists():
        raise SystemExit('Use a fresh build directory; existing app will not be overwritten.')
    environment = dict(os.environ, MACOSX_DEPLOYMENT_TARGET='10.15', PYTHONPATH=str(PROJECT))
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--distpath', str(destination),
                    '--workpath', str(PROJECT / 'build/macos'),
                    str(PROJECT / 'packaging/macos/CopyFinder.spec')], check=True, env=environment)
    bundle = destination / 'CopyFinder.app'
    records = inspect_bundle(bundle)
    (destination / 'binary-audit.json').write_text(json.dumps(records, indent=2) + '\n')
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(bundle))
    subprocess.run([sys.executable, str(PROJECT / 'scripts/macos_acceptance.py'), str(bundle),
                    str(destination / 'acceptance.json')], check=True)
    stem = f'CopyFinder-{VERSION}-macOS-x86_64'
    with tempfile.TemporaryDirectory(prefix='copyfinder-dmg-') as temporary:
        staging = Path(temporary)
        run('/usr/bin/ditto', str(bundle), str(staging / bundle.name))
        (staging / 'Applications').symlink_to('/Applications')
        run('/usr/bin/hdiutil', 'create', '-volname', 'CopyFinder', '-srcfolder', str(staging),
            '-ov', '-format', 'UDZO', str(destination / f'{stem}.dmg'))
    run('/usr/bin/hdiutil', 'verify', str(destination / f'{stem}.dmg'))
    run('/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', str(bundle),
        str(destination / f'{stem}.zip'))
    checksums = []
    for artifact in (destination / f'{stem}.dmg', destination / f'{stem}.zip'):
        checksums.append(f'{hashlib.file_digest(artifact.open("rb"), "sha256").hexdigest()}  {artifact.name}')
    (destination / 'SHA256SUMS').write_text('\n'.join(checksums) + '\n')
    (destination / 'distribution.json').write_text(json.dumps({
        'version': VERSION, 'architecture': TARGET_ARCH, 'deployment_target': '10.15',
        'build_host': platform.mac_ver()[0], 'signing': 'ad hoc; no Developer ID or notarization',
        'catalina_runtime_verified': False,
        'note': 'Deployment metadata and build-host acceptance do not establish Catalina runtime compatibility.'
    }, indent=2) + '\n')


if __name__ == '__main__':
    main()
