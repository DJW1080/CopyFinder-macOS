"""The distribution gate rejects binaries that cannot run on Catalina."""
import ast
from pathlib import Path
import tempfile
import unittest
from scripts.build_macos import minimum_versions, validate_load_commands, validate_dependencies, validate_bundle_links


class MacPackagingTests(unittest.TestCase):
    def test_reads_modern_and_legacy_deployment_commands(self):
        self.assertEqual(minimum_versions('cmd LC_BUILD_VERSION\n platform 1\n minos 10.15\n'), [(10, 15)])
        self.assertEqual(minimum_versions('cmd LC_VERSION_MIN_MACOSX\n version 10.13\n sdk 15.0\n'), [(10, 13)])

    def test_rejects_newer_and_missing_minimum_versions(self):
        for output in ('cmd LC_BUILD_VERSION\n minos 11.0\n', 'cmd LC_UUID\n'):
            with self.assertRaises(ValueError):
                validate_load_commands(output)

    def test_accepts_catalina_and_older(self):
        validate_load_commands('cmd LC_VERSION_MIN_MACOSX\n version 10.15\n')

    def test_rejects_dependency_on_build_machine(self):
        with self.assertRaises(ValueError):
            validate_dependencies('app:\n /opt/local/lib/libgtk-4.dylib (compatibility version 1.0.0)')

    def test_accepts_system_dependencies(self):
        validate_dependencies('app:\n /System/Library/Frameworks/AppKit.framework/Versions/C/AppKit (compatibility version 1.0.0)\n /usr/lib/libSystem.B.dylib (compatibility version 1.0.0)')

    def test_spec_explicitly_selects_gtk4(self):
        spec = Path(__file__).resolve().parents[1] / 'packaging/macos/CopyFinder.spec'
        tree = ast.parse(spec.read_text())
        analysis = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name) and node.func.id == 'Analysis')
        hooks = ast.literal_eval(next(item.value for item in analysis.keywords
                                     if item.arg == 'hooksconfig'))
        self.assertEqual(hooks['gi']['module-versions'], {'Gtk': '4.0', 'Gdk': '4.0'})
        bundle = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Name) and node.func.id == 'BUNDLE')
        icon = next(item.value for item in bundle.keywords if item.arg == 'icon')
        self.assertIn('copyfinder.png', ast.unparse(icon))

    def test_resolves_bundle_install_names(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory).resolve()
            executable = bundle / 'Contents/MacOS/CopyFinder'
            executable.parent.mkdir(parents=True)
            library = bundle / 'Contents/Frameworks/Test.framework/Versions/A/Test'
            library.parent.mkdir(parents=True)
            library.touch()
            for name in ('@rpath/Test.framework/Versions/A/Test',
                         '@loader_path/../Frameworks/Test.framework/Versions/A/Test',
                         '@executable_path/../Frameworks/Test.framework/Versions/A/Test'):
                validate_dependencies('app:\n ' + name + ' (compatibility version 1.0)',
                    bundle, executable, executable, ['@loader_path/../Frameworks'])

    def test_rejects_missing_escaping_and_linked_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle = root / 'App.app'
            bundle.mkdir()
            executable = bundle / 'CopyFinder'
            outside = root / 'outside.dylib'
            outside.touch()
            (bundle / 'escape.dylib').symlink_to(outside)
            for name in ('@loader_path/missing.dylib', '@loader_path/../outside.dylib',
                         '@loader_path/escape.dylib', '@rpath/missing.dylib'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    validate_dependencies('app:\n ' + name, bundle, executable, executable, [])

    def test_rejects_broken_and_escaping_bundle_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            bundle = root / 'App.app'
            bundle.mkdir()
            outside = root / 'outside'
            outside.touch()
            link = bundle / 'link'
            for target in (outside, bundle / 'missing'):
                link.symlink_to(target)
                with self.assertRaises(ValueError):
                    validate_bundle_links(bundle)
                link.unlink()
            inside = bundle / 'inside'
            inside.touch()
            link.symlink_to(inside)
            validate_bundle_links(bundle)
