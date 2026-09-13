# macOS implementation

CopyFinder uses SwiftUI hosted in a normal AppKit window. Folder selection, Finder reveal, Trash, settings, image inspection, and file metadata all use Apple APIs. SHA-256 comparisons use CryptoKit.

The app targets Intel macOS 10.15. It keeps file removal recoverable through Trash and validates the selected duplicate, kept copy, content hash, metadata snapshot, and physical file identity immediately before removal.

Beta 1 is ad-hoc signed. Until a project Apple Developer identity is available, it cannot be Developer ID signed or notarized.
