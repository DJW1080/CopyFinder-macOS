# CopyFinder Linux validation record

Target observed on 11 September 2026: Linux Mint 22.3 Cinnamon, X11, Python 3.12.3, GTK 4.14.5, PyGObject 3.48.2, Pillow 10.2.0. This is the local implementation matching the approved Windows 2.1.8 behavioural reference at commit `d90fa7b502326bfcac2df55fa1c87de2ed0e1543`.

## Verified components

- Core scanner: 45 tests passed after correcting bounded metadata reads and keep ordering. Fixtures include all six supported image formats, same-size different bytes, empty files, cancellation, filters, replacement during reading, symlink and hard-link handling, undecodable names and review limits.
- Deletion and desktop services: 26 tests passed. Real GIO Trash and restore run with temporary HOME and XDG_DATA_HOME in a subprocess. The actual user's Trash was not used. Changed/missing/replaced/aliased files, no-op or failed Trash, and survivor validation are covered.
- Review/export/settings: 5 tests passed, covering kept-row protection, selection changes, compatible exports with quotes/newlines/Unicode, and atomic settings writes.
- GTK: 7 tests passed, covering native selection/settings, a real asynchronous limited scan, PNG thumbnails surviving row rebinding, queued preview closure and 16 malformed persisted-settings cases. Invalid settings remain unchanged while the interface uses defaults.
- Native GTK rendering completed at 830 × 800 for collapsed and expanded settings. The actual widget renderings are saved in `screenshots/review.png` and `screenshots/settings.png` and have been visually inspected.

Commands:

```sh
/usr/bin/python3 -m unittest discover -s tests -p 'test_core.py' -v
/usr/bin/python3 -m unittest discover -s tests -p 'test_deletion.py' -v
/usr/bin/python3 -m unittest discover -s tests -p 'test_ui.py' -v
/usr/bin/python3 tests/render_ui.py
```

## Scale measurements

The benchmark creates disposable regular files, with one exact pair in every 50 files, then scans using default settings. It measures synthetic directory behaviour, not arbitrary document collections or slow network storage.

| Files inventoried | Duplicate groups returned | Limit reached | Scan time |
|---|---:|---|---:|
| 20,000 | 400 | No | 3.136 s |
| 80,000 | 500 | Yes | 6.756 s |

The 20,000-file run's `/proc/self/status` measured 24,764 KiB resident initially and 33,756 KiB resident/high-water after scanning. The 80,000-file run measured 24,772 KiB initially and 40,416 KiB after scanning (about 39.5 MiB). Initial `getrusage` readings included a much larger process-lifetime peak not reflected in this executable's `/proc` high-water figures; they are excluded from the scanner memory claim. The benchmark now records executable-local `/proc` measurements explicitly.

## Package acceptance procedure

`scripts/build_deb.py` builds the local Debian artifact. `tests/package_acceptance.py`, run under fakeroot, uses an isolated dpkg root and a read-only copy of the host dependency status. It checks installation, upgrade from a deliberately minimal 0.0.0 fixture, source-to-installed file hashes, launcher version, desktop-entry syntax, obsolete-file removal, and removal while retaining a synthetic user settings file.

This procedure does not install anything into the running host. Runtime libraries are supplied by the existing Mint installation, so it does not establish dependency installation in a clean VM. The graphical probe runs with the ordinary user's identity; fakeroot applies to package management only.

The fixture routes dpkg logs into its temporary root and includes the copied host file lists. The launcher disables bytecode writes so package removal leaves no generated application cache behind. Graphical probes remove fakeroot's preload to preserve normal desktop-bus authentication.

## Final verification

After baseline cleanup, `PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m unittest discover -s tests -v` passed **83 tests in 2.001 seconds**, with no failures or skips. The retained application code is unchanged from the tested implementation; the unused source `.ico` was removed, leaving the native PNG icon.

The `.deb` build and isolated package acceptance both exited 0 from a temporary copy of the cleaned baseline. The dpkg run verified 30 packaged application-file hashes against current source, upgrade removal of an obsolete fixture file, the launcher version, desktop-entry syntax and a mapped GTK window. Removal preserved the synthetic user settings and removed application files. The copied host package database already contained CopyFinder 0.1.0, so installing the deliberately older 0.0.0 test fixture produced a downgrade warning inside the isolated root before the tested upgrade.

The validated package contained 124,634 bytes. SHA-256: `78f70ac800c5b36ad878c1cf7e0d6933b18178e7866a3facee39d43d5b27a6a1`. This identifies that validation artifact; package builds include build-time metadata and are not claimed to reproduce this checksum. Generated packages, caches, and completed planning documents are excluded from the source baseline. The pre-cleanup snapshot and validation artifact were retained outside the project.

## Boundaries

The Windows executable was not run side by side. Appearance was assessed from its published screenshot and inspected source. Native window decorations, fonts and dialogs differ. Other Mint releases, MATE/Xfce, Wayland, actual removable/network/read-only mount behaviour and opening an actual file-manager window remain unverified. Unsupported Trash is covered through an injected failure, in addition to successful real local Trash/recovery.

The validation used synthetic files and isolated Trash fixtures. It made no ownership changes, permission repairs, permanent deletion of user data, or elevated application execution. The host application installation was unchanged by cleanup and validation. Source-reference artwork was reused; application code and tests were newly authored.
