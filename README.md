# CopyFinder for macOS

CopyFinder is a duplicate-file review application with a native macOS build.
It scans one chosen folder, groups only nonempty files with equal sizes and full
SHA-256 hashes, lets you choose which copy to keep, exports the review, and moves
approved duplicates to Trash after checking both files again.

The first Mac target is a 64-bit Intel Mac running macOS Catalina 10.15.8.
The downloadable app is being built and must pass its macOS build checks before
it is described as Catalina-compatible. Apple Silicon packaging is planned after
the Intel edition is accepted. The Linux Mint edition remains in the separate
[CopyFinder-LinuxMint repository](https://github.com/DJW1080/CopyFinder-LinuxMint).

## Contributors

- **Dean John Weiniger (DJW1080)** — project creator and maintainer; requirements,
  direction, Mac testing, and release approvals.
- **OpenAI Codex** — AI development co-contributor for the independently written
  Linux foundation and native macOS integration, tests, packaging, and documentation,
  working under Dean's direction.

## Workflow

Choose a folder, adjust Scan Settings if needed, and select Scan. One file per
exact-duplicate group is kept; the other files are selected initially. Keep changes
the protected file. Open reveals a file in Finder. Review the selections before
choosing Delete Duplicates; a confirmation is always required.

The six keep choices are Original, Shortest name, Oldest file, Newest file, Folder,
and Highest Resolution. Original is a filename preference, not proof of provenance.
Oldest and Newest use modification time. Highest Resolution operates only within
files already proven byte-for-byte equal; CopyFinder does not compare visual similarity.

The default limit is 500 duplicate files, excluding the kept files. Reaching it
means the scan stopped for review and later files may not have been evaluated.
Inventory is temporary and disk-backed; only same-size candidates are hashed, with
a bounded worker queue.

## File safety

- Symlinks and special files are never hashed. A scan root with a symlink ancestor
  is rejected; choose its real path.
- Hard-link aliases count as one physical file. A candidate with another hard link
  is refused because removing one name would not reclaim its contents.
- Before Trash, the duplicate and keeper are checked against their scanned identity,
  size, timestamps, and full hash. The keeper is checked again after the operation.
- Finder and Foundation provide native reveal, volume classification, and Trash.
  There is no permanent-delete fallback, permission repair, ownership change, or
  elevated application helper.
- A failed or uncertain operation leaves the review row in place. Check Trash and
  rescan before trying again.

Skip hidden files covers dotfiles and dot-directories. Skip system files excludes
protected macOS locations while retaining user folders. Readable mounted folders can
be scanned; CopyFinder warns about network storage before deletion when macOS can
classify the volume.

## Configuration and logs

Settings are stored at
`~/Library/Application Support/CopyFinder/settings.json`. Logs are stored at
`~/Library/Logs/CopyFinder/copyfinder.log` and may contain filenames. Invalid settings
are left untouched and reported. Settings and exported reports use atomic replacement.

## Development and packaging

Shared tests can be run on Linux with:

```sh
make test
```

The real app must be built on an Intel Mac environment prepared for a 10.15 deployment
target:

```sh
make package
```

The build creates a standalone `.app`, `.dmg`, `.zip`, SHA-256 checksums, a native
acceptance report, and an audit of every bundled Mach-O binary. See
[the Mac build guide](docs/macos-build.md) for the exact gates and the Catalina test
checklist.

Initial builds use an ad hoc signature and are not notarized. A checksum identifies
the downloaded bytes but is not a publisher signature. Developer ID signing and Apple
notarization require credentials controlled by the project owner.

The interface retains the CopyFinder layout and artwork. Window decorations, fonts,
and file dialogs follow macOS. See [NOTICE.md](NOTICE.md) for source and artwork
provenance.
