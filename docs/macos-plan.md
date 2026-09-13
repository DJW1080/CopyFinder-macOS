# macOS implementation plan

Goal: Deliver CopyFinder's existing workflow in a self-contained macOS app.
Specification: docs/macos.md. Architecture: shared Python/GTK application with
native platform services and separate Linux/macOS packaging.

First target: Intel x86_64, macOS Catalina 10.15.8 (user's remote 2013 Mac).
Publication target: a separate repository, `DJW1080/CopyFinder-macOS` (not yet
created). All Mac CI, code, tags and release assets belong there. Do not push Mac
work to `DJW1080/CopyFinder-LinuxMint` or alter the Linux checkout's origin.
Global constraints: preserve Linux behavior and existing release assets; retain
all duplicate deletion safeguards; do not claim unperformed Mac checks; pause on
any tool or test error under the user's AGENTS instructions.

- [ ] Task 1: Implement native macOS desktop services and settings paths, with
  tests for success, failure, remote-volume handling, and Linux dispatch.
  Own desktop.py, storage.py, macos.py and tests/test_macos.py.
- [ ] Task 2: Make shared descriptor handling and runtime messages portable.
  Add meaningful cross-platform regression checks; retain Linux safeguards.
- [ ] Task 3: Add architecture-specific macOS app/disk-image packaging and CI,
  Catalina-compatible dependency installation, bundled-app acceptance, checksums
  and instructions. Inspect every bundled Mach-O minimum macOS version.
  Own packaging/macos, scripts/build_macos.py, scripts/macos_acceptance.py,
  scripts/run_tests.py, .github/workflows/macos.yml and docs/macos-build.md.
- [ ] Task 4: Review integrated changes, run Linux regression tests, commit the
  Mac work to its separate repository, and use that repository's macOS CI for
  native build and acceptance evidence. Verify the destination before any push.
- [ ] Task 5: Record results and provide the resulting artifacts and manual
  acceptance instructions. Do not mark native validation passed without evidence.

Interface decisions: desktop.py keeps its public API and Linux mock points.
Native integration raises DesktopIntegrationError. VERSION remains shared and
the initial Mac addition does not rewrite the existing v0.1.0 Linux release.
Mac test runner resolves the temporary directory's system alias before creating
fixtures so tests retain the application's deliberate symlink refusal.
