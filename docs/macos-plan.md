# macOS Beta 1 delivery report

## Objective

Create a separate, native macOS CopyFinder with the same core user workflow, written independently for Apple platforms, and provide a downloadable build for a 2013 Intel Mac running macOS Catalina 10.15.8.

## Chosen approach

The application is implemented directly in Swift with AppKit, SwiftUI, Foundation, CryptoKit, and Finder/Trash services. This removes the earlier dependency compilation path and makes the package suitable for rapid real-hardware feedback.

## Beta scope

Beta 1 includes folder selection, recursive scanning, size plus SHA-256 matching, six keeper rules, group review, Finder reveal, guarded Trash removal, report export, and saved settings. The build performs one smoke check and must finish its own work inside 110 seconds.

## Evidence boundary

The automated smoke check proves that the compiled Intel executable can detect a basic duplicate pair on its build host. It does not prove compatibility with Catalina hardware. The downloaded DMG on the target 2013 Mac is the decisive Beta 1 acceptance test.
