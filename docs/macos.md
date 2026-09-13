# CopyFinder for macOS

## Implementation report

The macOS edition retains the existing GTK 4 interface and independently written
Python duplicate scanner. It adds native macOS services through PyObjC rather
than emulating Linux desktop services. Linux packaging remains available.

Publication must use a separate GitHub repository, planned as
`DJW1080/CopyFinder-macOS`, with its own build workflows and downloadable releases.
Do not publish Mac changes, workflows, tags, or assets to
`DJW1080/CopyFinder-LinuxMint`. The existing Linux checkout and release remain
the Linux baseline. The Mac repository has not yet been created.

The application will use Finder to reveal files, Foundation to move selected
duplicates to Trash, `~/Library/Application Support/CopyFinder` for settings, and
`~/Library/Logs/CopyFinder` for logs. It must never fall back to permanent deletion.
The existing snapshot, digest, hard-link, and symlink safeguards remain mandatory.

Mac builds require macOS. The first target is the user's 2013 Intel Mac running
macOS Catalina 10.15.8. Its `.app` and disk image must contain only dependencies
built for macOS 10.15 or earlier. A newer macOS runner alone does not establish
Catalina compatibility. Apple Silicon packaging is a later target. The bundles include
Python, GTK, and the application dependencies; users do not need Homebrew or
Python to use a completed bundle.

The existing Linux machine can verify shared code and mocked platform contracts.
Only a successful macOS build and native integration checks can establish Mac
compatibility. A final interactive check on a Mac must cover window appearance,
folder permissions, previews, Finder reveal, and restoration from Trash.

Developer ID signing and Apple notarization require the project owner's Apple
credentials. Builds without those credentials must identify themselves as
unsigned distribution builds, even if the build tool applies an ad hoc signature.

## Acceptance criteria

- All existing Linux regression tests pass.
- The same duplicate review workflow works on macOS, including safe Trash.
- macOS imports do not require Linux-only constants or `/proc` interfaces.
- The Intel build passes native tests; every bundled Mach-O dependency declares
  a deployment target of macOS 10.15 or earlier.
- Each packaged app starts and performs an isolated scan and safe Trash check.
- Downloadable artifacts have architecture labels and SHA-256 checksums.
- Validation records distinguish actual results from remaining manual checks.
