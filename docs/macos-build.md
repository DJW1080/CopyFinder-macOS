# Building the Intel macOS distribution

The first target is the user's Intel 2013 Mac running Catalina (reported as
10.15.8). The app bundles Python, GTK4 Quartz, Pillow, PyObjC and its libraries;
users do not install Python or a package manager. The shared application version
remains 0.1.0. This repository is `DJW1080/CopyFinder-macOS` and does not publish
to or replace CopyFinder-LinuxMint releases.

## Build environment and limits

Run **Build Intel macOS app** in GitHub Actions. The workflow selects
`macos-15-intel`, an Intel image listed in the
[official runner table](https://github.com/actions/runner-images#available-images).
`packaging/macos/provision.sh` builds MacPorts 2.12.6 from its
[official release](https://github.com/macports/macports-base/releases/tag/v2.12.6).
The source archive SHA-256 is pinned to the release API asset digest:
`d4d77de931a0442d0d144e1b3033b6285d51091b9d9e6f73c4e02e3627be29a6`.

The script requires a fresh Intel Mac; it refuses to alter an existing MacPorts
installation. It configures `build_arch x86_64`,
`macosx_deployment_target 10.15`, `buildfromsource always`, and Quartz variants.
MacPorts source builds supply GTK4, Python 3.13, PyGObject, Pillow, PyObjC and
PyInstaller. The GTK port's [Quartz variant and compatibility patches](https://github.com/macports/macports-ports/blob/master/gnome/gtk4/Portfile)
provide a plausible legacy macOS build route. It does not use Homebrew bottles.
The [MacPorts configuration reference](https://github.com/macports/macports-base/blob/master/doc/macports.conf.5.txt)
documents its build settings. MacPorts ports are resolved at build time; the
workflow records installed versions and configuration, but the entire dependency
graph is not yet locked. Source compilation may take several hours.

**This route has not yet been executed on a Mac.** A port may require a newer
minimum OS or need build adjustments. Such a result must fail the build; do not
lower existing Mach-O deployment metadata to conceal incompatibility. A modern
SDK and a declared 10.15 target cannot prove that all runtime API usage works on
Catalina. The old Mac's manual acceptance remains required even after CI passes.

On a prepared Intel Mac with a logged-in desktop session:

```sh
/opt/local/bin/python3.13 scripts/run_tests.py
/opt/local/bin/python3.13 scripts/build_macos.py
```

Use a fresh output directory. The builder intentionally refuses to overwrite an
existing `dist/macos/CopyFinder.app`. Compilation and provisioning are never
performed on the Linux development host.

## Distribution gates and outputs

PyInstaller creates a real `CopyFinder.app` containing its interpreter and native
libraries. Its [macOS packaging support](https://pyinstaller.org/en/stable/feature-notes.html#macos-multi-arch-support)
provides explicit Intel architecture selection and ad hoc signing. The builder
inspects every bundled Mach-O file, including extensions, frameworks and helper
binaries. It rejects missing Intel slices, missing minimum-version commands,
minimum macOS versions newer than 10.15, non-macOS platforms, absolute external
library references and non-system absolute library search paths. Apple system
libraries remain provided by macOS. Relative install names are resolved against loader/executable locations and
LC_RPATH entries; non-system targets must exist inside the app. Broken or
escaping bundle symlinks are rejected. The bundled smoke test also exercises
runtime loading; static checks do not cover every optional runtime path.

The bundled app runs with a minimal environment and isolated config/state paths,
opens its GTK window, scans generated duplicates, uses the actual safe-deletion
validator and Foundation Trash operation, checks the keeper and exact resulting
Trash file, then restores only its generated fixture. It never scans user folders
or empties Trash. On a failed check, the build stops; a generated fixture may
remain for inspection. The test requires a usable native desktop session.

Successful runs produce these files in `dist/macos`:

- `CopyFinder-0.1.0-macOS-x86_64.dmg` and `.zip`.
- `SHA256SUMS`, calculated over those completed archives.
- `binary-audit.json`, `acceptance.json`, and `distribution.json`.

The workflow uploads the archives and evidence as an Actions artifact; it does
not publish a GitHub Release. A checksum detects differing bytes; it is not a
cryptographic publisher signature. The app uses an **ad hoc signature**, has no
Developer ID signature, and is **not notarized**. Developer ID distribution and
notarization require the owner's Apple credentials and a separate signing step.

## Catalina manual acceptance

Download the successful Actions artifact, extract it, and verify its checksums:

```sh
shasum -a 256 -c SHA256SUMS
```

Mount the disk image, drag CopyFinder into Applications, and launch it using
Finder. Record the exact macOS version from About This Mac. macOS may block this
unsigned distribution pending the user's explicit security approval; do not
remove quarantine automatically or disable system protections globally.

Check the actual window layout, folder chooser, scan progress and cancellation,
all duplicate keep rules, image previews, Finder reveal, and readable error
messages. Using only a disposable folder containing two equal files and one
unequal file, confirm that Trash removes the selected duplicate, preserves the
keeper and unrelated file, and allows restoration through Finder. Verify folder
permission denial reports an error without deletion. Run without development
Python, GTK, or MacPorts installed to establish standalone runtime behavior.

Record screenshots and the actual outcomes. A CI pass on macOS 15 should be
reported as build-host acceptance, never as a successful Catalina runtime test.
