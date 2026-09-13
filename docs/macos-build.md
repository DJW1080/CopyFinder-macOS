# Fast macOS beta build

The build uses the Swift compiler and Apple frameworks already supplied by Xcode. It has no dependency installation stage.

Run `make build` on an Intel-capable Mac with Xcode command-line tools. The script compiles for Intel and macOS 10.15, assembles `CopyFinder.app`, applies an ad-hoc signature, runs one duplicate-detection smoke check, and creates DMG and ZIP downloads with SHA-256 checksums.

The same script runs in GitHub Actions with a two-minute job timeout. Its own work limit is 110 seconds so it can fail clearly before the job is killed.
