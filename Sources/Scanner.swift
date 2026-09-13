import AppKit
import CryptoKit
import Foundation

private let hashChunkBytes = 1_048_576
private let copySuffixes = [" - copy", " copy", "_copy"]
private let systemFolders = [
    "/dev", "/system", "/library", "/bin", "/sbin", "/usr", "/private/etc",
    "/private/var/db", "/private/var/log", "/private/var/root", "/private/var/run"
]

final class CancellationToken {
    private let lock = NSLock()
    private var cancelled = false

    func cancel() {
        lock.lock()
        cancelled = true
        lock.unlock()
    }

    func check() throws {
        lock.lock()
        let shouldCancel = cancelled
        lock.unlock()
        if shouldCancel {
            throw CopyFinderError.scanCancelled
        }
    }
}

final class DuplicateScanner {
    private let fileManager = FileManager.default
    private let resourceKeys: [URLResourceKey] = [
        .isDirectoryKey, .isRegularFileKey, .isSymbolicLinkKey, .isHiddenKey,
        .fileSizeKey, .contentModificationDateKey, .fileResourceIdentifierKey,
        .volumeIdentifierKey
    ]

    func scan(
        folder: URL,
        options: ScanOptions,
        cancellation: CancellationToken,
        progress: (String) -> Void
    ) throws -> ScanResult {
        var isDirectory: ObjCBool = false
        guard fileManager.fileExists(atPath: folder.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            throw CopyFinderError.invalidFolder
        }

        progress("Reading folders…")
        var skippedFiles = 0
        var scannedFiles = 0
        var seenPhysicalFiles = Set<String>()
        var filesBySize: [Int64: [UnhashedFile]] = [:]
        let enumerationOptions: FileManager.DirectoryEnumerationOptions = [.skipsPackageDescendants]
        guard let enumerator = fileManager.enumerator(
            at: folder,
            includingPropertiesForKeys: resourceKeys,
            options: enumerationOptions,
            errorHandler: { _, _ in true }
        ) else {
            throw CopyFinderError.invalidFolder
        }

        while let url = enumerator.nextObject() as? URL {
            try cancellation.check()
            do {
                let values = try url.resourceValues(forKeys: Set(resourceKeys))
                if values.isDirectory == true {
                    if shouldSkipDirectory(url: url, values: values, options: options) {
                        enumerator.skipDescendants()
                    }
                    continue
                }
                guard values.isRegularFile == true, values.isSymbolicLink != true else {
                    skippedFiles += 1
                    continue
                }
                if shouldSkipFile(url: url, values: values, options: options) {
                    skippedFiles += 1
                    continue
                }
                let size = Int64(values.fileSize ?? 0)
                guard size > 0, size >= options.minimumBytes else {
                    skippedFiles += 1
                    continue
                }
                let identity = physicalIdentity(values: values, path: url.path)
                guard seenPhysicalFiles.insert(identity).inserted else {
                    skippedFiles += 1
                    continue
                }
                let file = UnhashedFile(
                    url: url,
                    size: size,
                    modified: values.contentModificationDate ?? .distantPast,
                    resourceIdentifier: identity
                )
                filesBySize[size, default: []].append(file)
                scannedFiles += 1
            } catch {
                skippedFiles += 1
            }
        }

        progress("Comparing same-size files…")
        var grouped: [ContentKey: [FileSnapshot]] = [:]
        for (_, candidates) in filesBySize where candidates.count > 1 {
            for candidate in candidates {
                try cancellation.check()
                do {
                    let digest = try sha256(url: candidate.url, cancellation: cancellation)
                    guard try stillMatches(candidate) else {
                        skippedFiles += 1
                        continue
                    }
                    let snapshot = FileSnapshot(
                        path: candidate.url.path,
                        size: candidate.size,
                        modified: candidate.modified,
                        resourceIdentifier: candidate.resourceIdentifier,
                        digest: digest,
                        pixelArea: imagePixelArea(candidate.url)
                    )
                    grouped[ContentKey(size: candidate.size, digest: digest), default: []].append(snapshot)
                } catch CopyFinderError.scanCancelled {
                    throw CopyFinderError.scanCancelled
                } catch {
                    skippedFiles += 1
                }
            }
        }

        var groups = [DuplicateGroup]()
        var duplicateCount = 0
        var limitReached = false
        let duplicateSets = grouped.values.filter { $0.count > 1 }.sorted {
            ($0.first?.path ?? "") < ($1.first?.path ?? "")
        }
        for files in duplicateSets {
            let remaining = options.duplicateLimit - duplicateCount
            if remaining <= 0 {
                limitReached = true
                break
            }
            let maximumFiles = min(files.count, remaining + 1)
            let ordered = orderFiles(Array(files.prefix(maximumFiles)), options: options)
            groups.append(DuplicateGroup(id: groups.count + 1, files: ordered))
            duplicateCount += ordered.count - 1
            if maximumFiles < files.count || duplicateCount >= options.duplicateLimit {
                limitReached = true
                break
            }
        }
        return ScanResult(groups: groups, scannedFiles: scannedFiles, skippedFiles: skippedFiles, limitReached: limitReached)
    }

    func snapshotForValidation(path: String, cancellation: CancellationToken = CancellationToken()) throws -> FileSnapshot {
        let url = URL(fileURLWithPath: path)
        let values = try url.resourceValues(forKeys: Set(resourceKeys))
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw CopyFinderError.unsafeDuplicate(path)
        }
        let size = Int64(values.fileSize ?? 0)
        return FileSnapshot(
            path: path,
            size: size,
            modified: values.contentModificationDate ?? .distantPast,
            resourceIdentifier: physicalIdentity(values: values, path: path),
            digest: try sha256(url: url, cancellation: cancellation),
            pixelArea: imagePixelArea(url)
        )
    }

    private func shouldSkipDirectory(url: URL, values: URLResourceValues, options: ScanOptions) -> Bool {
        if options.skipHidden, values.isHidden == true {
            return true
        }
        guard options.skipSystem else { return false }
        let path = url.standardizedFileURL.path.lowercased()
        return systemFolders.contains { path == $0 || path.hasPrefix($0 + "/") }
    }

    private func shouldSkipFile(url: URL, values: URLResourceValues, options: ScanOptions) -> Bool {
        if options.skipHidden, values.isHidden == true {
            return true
        }
        let fileExtension = url.pathExtension.lowercased()
        return !fileExtension.isEmpty && options.excludedExtensions.contains(fileExtension)
    }

    private func physicalIdentity(values: URLResourceValues, path: String) -> String {
        let volume = values.volumeIdentifier.map { String(describing: $0) } ?? "unknown-volume"
        let file = values.fileResourceIdentifier.map { String(describing: $0) } ?? path
        return volume + ":" + file
    }

    private func stillMatches(_ file: UnhashedFile) throws -> Bool {
        let values = try file.url.resourceValues(forKeys: Set(resourceKeys))
        return values.isRegularFile == true
            && values.isSymbolicLink != true
            && Int64(values.fileSize ?? 0) == file.size
            && values.contentModificationDate == file.modified
            && physicalIdentity(values: values, path: file.url.path) == file.resourceIdentifier
    }

    private func sha256(url: URL, cancellation: CancellationToken) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { handle.closeFile() }
        var hasher = SHA256()
        while true {
            try cancellation.check()
            let data = handle.readData(ofLength: hashChunkBytes)
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func imagePixelArea(_ url: URL) -> Int {
        guard let image = NSImage(contentsOf: url), let representation = image.representations.first else {
            return 0
        }
        return max(0, representation.pixelsWide) * max(0, representation.pixelsHigh)
    }

    private func orderFiles(_ files: [FileSnapshot], options: ScanOptions) -> [FileSnapshot] {
        guard let keeper = files.min(by: { keepKey($0, options: options) < keepKey($1, options: options) }) else {
            return files
        }
        return [keeper] + files.filter { $0.path != keeper.path }.sorted { $0.path < $1.path }
    }

    private func keepKey(_ file: FileSnapshot, options: ScanOptions) -> KeepKey {
        let stem = file.url.deletingPathExtension().lastPathComponent
        let suffixScore: Int
        if copySuffixes.contains(where: { stem.lowercased().hasSuffix($0) }) {
            suffixScore = 10
        } else if stem.range(of: #"\(\d+\)$"#, options: .regularExpression) != nil {
            suffixScore = 20
        } else {
            suffixScore = 0
        }
        let original = [suffixScore, stem.count]
        switch options.keepRule {
        case .shortestName:
            return KeepKey(numbers: [stem.count] + original, date: file.modified, path: file.path)
        case .oldestFile:
            return KeepKey(numbers: original, date: file.modified, path: file.path)
        case .newestFile:
            return KeepKey(numbers: original, date: Date(timeIntervalSince1970: -file.modified.timeIntervalSince1970), path: file.path)
        case .folder:
            let preferred = options.preferredFolder.isEmpty || !file.path.hasPrefix(options.preferredFolder) ? 1 : 0
            return KeepKey(numbers: [preferred] + original, date: file.modified, path: file.path)
        case .highestResolution:
            return KeepKey(numbers: [-file.pixelArea] + original, date: file.modified, path: file.path)
        case .original:
            return KeepKey(numbers: original, date: file.modified, path: file.path)
        }
    }
}

private struct UnhashedFile {
    let url: URL
    let size: Int64
    let modified: Date
    let resourceIdentifier: String
}

private struct ContentKey: Hashable {
    let size: Int64
    let digest: String
}

private struct KeepKey: Comparable {
    let numbers: [Int]
    let date: Date
    let path: String

    static func < (left: KeepKey, right: KeepKey) -> Bool {
        if left.numbers != right.numbers {
            return left.numbers.lexicographicallyPrecedes(right.numbers)
        }
        if left.date != right.date {
            return left.date < right.date
        }
        return left.path < right.path
    }
}
