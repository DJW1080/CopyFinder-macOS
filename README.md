# CopyFinder for Linux Mint

A fresh native GTK implementation of CopyFinder's duplicate-file review workflow. The Windows 2.1.8 reference was inspected to specify behaviour and appearance. No Windows or existing Linux-edition application code was ported.

The current source baseline is version **0.1.0**. It replaces the previous implementation in this repository; earlier versions remain in Git history. Generated packages and Python caches are excluded from the source baseline.

## Contributors

- **Dean John Weiniger (DJW1080)** — project creator and maintainer; requirements, direction, and release approvals.
- **OpenAI Codex** — AI development co-contributor for the native Linux implementation, tests, packaging, and documentation, working under Dean's direction.

## Run

Target: Linux Mint 22.3 Cinnamon, Python 3.12 and GTK 4.14. Minimum API requirement: GTK 4.10 and Python 3.10. Other distributions, desktops and Wayland have not yet been accepted.

Install the desktop dependencies if absent:

```sh
sudo apt install python3 python3-gi gir1.2-gtk-4.0 python3-pil
```

From this project directory:

```sh
/usr/bin/python3 -m copyfinder
```

Use the system Python because PyGObject and GTK come from the distribution packages. The application runs as your ordinary user.

## Workflow

Choose one folder, adjust Scan Settings if needed, and select Scan. Files match only when nonzero sizes and full SHA-256 hashes match. One file per group is kept; other files are selected initially. Keep changes that choice. Open reveals a file in the desktop file manager. Review selections before Delete Duplicates. A confirmation is always required.

The six keep choices are Original, Shortest name, Oldest file, Newest file, Folder and Highest Resolution. Original is a filename preference, not proof of provenance. Oldest/Newest use modification time. Highest Resolution operates within exact-content groups; CopyFinder does not compare visual similarity.

The default review limit is 500 duplicate files, excluding kept files. Reaching it means the scan stopped for review. Later files, including a more-preferred kept copy, may not have been evaluated. Inventory is stored temporarily in SQLite; only same-size candidates are hashed, with a bounded worker queue.

Image metadata inspection has a 1 MiB cumulative source-read budget. If a decoder needs more, dimensions are reported as unknown; SHA-256 still covers the entire file. Previews use category icons for files larger than 32 MiB or images above 40 million pixels. Two background preview workers and a 128-item thumbnail cache bound normal review work. These are explicit resource limits of this Linux implementation.

## Linux file behaviour

- Skip hidden files includes dotfiles and hidden directories.
- Skip system files excludes `/dev`, `/proc`, `/sys`, and `/run`. Known virtual filesystems and `/dev`, `/proc`, `/sys` remain excluded regardless.
- Symlinks and special files are never hashed. Scan roots with symlink ancestors are rejected. Use the real directory path.
- Hard-link aliases count as one physical file. A candidate that has hard links is refused at deletion, since removing one name would not free the file's content.
- Ordinary mounted network/removable folders can be scanned when readable. Remote classification is best-effort, based on Linux mount information and GVfs paths.

Before Trash, both files are checked against the scan's identity, size, modification/change timestamps and hash. Changed, replaced, missing, aliased or inaccessible files are rejected. The kept survivor is checked again afterwards. GIO uses a pathname for Trash; arbitrary concurrent filesystem changes cannot be made atomic with that operation. If confirmation fails after moving a file, CopyFinder reports the uncertainty and retains its review row. Inspect Trash and rescan.

Trash is the only removal action. A mount without working Trash leaves the file in place. There is no permanent-deletion fallback, permission repair, ownership change or elevated helper. Recovery uses your file manager's Trash.

CSV and JSON export current review state with the Windows reference's field names. DeleteStatus means Kept/Selected/Not selected, not deletion history.

## Configuration and logs

Settings: `$XDG_CONFIG_HOME/copyfinder/settings.json` (default `~/.config/copyfinder/settings.json`). Logs: `$XDG_STATE_HOME/copyfinder/copyfinder.log` (default `~/.local/state/copyfinder/copyfinder.log`). Logs rotate and can contain filenames. Settings and export writes use atomic replacement. Invalid settings are left untouched and reported rather than silently overwritten.

The first launch of each version shows a Linux compatibility report. These diagnostics do not claim every mounted filesystem supports Trash.

## Test and package

```sh
make test
make package
sudo apt install ./dist/copyfinder_0.1.0_all.deb
```

GTK integration tests require a display. The package installs the CopyFinder menu launcher and application files; user settings remain on removal. The build creates a local `.deb` and makes no network changes. See `docs/validation.md` for the exact verification performed and remaining limitations.

The banner and category artwork come from the pinned original reference. Linux window decorations, font rendering and file dialogs follow the local desktop. See `NOTICE.md` for provenance.
