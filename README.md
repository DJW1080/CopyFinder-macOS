# CopyFinder for macOS

CopyFinder is a native macOS duplicate-file scanner written from scratch in Swift. It follows the established CopyFinder workflow while using Apple system frameworks for its interface, file access, SHA-256 comparison, Finder integration, and Trash.

This repository is the macOS application. The Linux Mint version remains in its own repository.

## Beta 1 target

- Intel Macs (`x86_64`)
- macOS Catalina 10.15 or later
- no Python, GTK, MacPorts, Homebrew, or third-party runtime
- ad-hoc signed; no Apple Developer ID or notarization yet

## What it does

- scans a chosen folder and its subfolders
- considers files duplicates only when size and SHA-256 content match
- offers Original, Shortest name, Oldest file, Newest file, Folder, and Highest Resolution keep rules
- lets you review groups, change the kept file, reveal files in Finder, and select duplicates
- rechecks both files immediately before moving a selected duplicate to the macOS Trash
- exports CSV or JSON reports
- remembers scan settings locally

## Install the beta

Download the DMG from the GitHub release, open it, and drag `CopyFinder.app` to Applications. Because Beta 1 has no Developer ID signature, Catalina may require Control-clicking the app, choosing **Open**, and confirming once.

## Build

On a Mac with Xcode command-line tools:

```sh
make build
```

The build creates a DMG, ZIP, checksums, build details, and the result of one smoke test under `dist/macos/`. The build has a 110-second limit.

## Status

Beta 1 is intentionally an early real-hardware build. The automated check starts the compiled executable in smoke mode and confirms that it detects one duplicate pair. Catalina behavior is confirmed only after testing the published package on a Catalina Mac.
