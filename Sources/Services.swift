import AppKit
import Foundation

private let commaReplacement = ";"

struct TrashService {
    private let fileManager = FileManager.default
    private let scanner = DuplicateScanner()

    func moveToTrash(candidate: FileSnapshot, keeper: FileSnapshot) throws {
        let currentCandidate = try scanner.snapshotForValidation(path: candidate.path)
        let currentKeeper = try scanner.snapshotForValidation(path: keeper.path)

        guard currentCandidate == candidate else {
            throw CopyFinderError.fileChanged(candidate.path)
        }
        guard currentKeeper == keeper else {
            throw CopyFinderError.fileChanged(keeper.path)
        }
        guard currentCandidate.resourceIdentifier != currentKeeper.resourceIdentifier,
              currentCandidate.size == currentKeeper.size,
              currentCandidate.digest == currentKeeper.digest else {
            throw CopyFinderError.unsafeDuplicate(candidate.path)
        }

        let attributes = try fileManager.attributesOfItem(atPath: candidate.path)
        let referenceCount = (attributes[.referenceCount] as? NSNumber)?.intValue ?? 1
        guard referenceCount == 1 else {
            throw CopyFinderError.unsafeDuplicate(candidate.path)
        }

        do {
            var trashedURL: NSURL?
            try fileManager.trashItem(at: candidate.url, resultingItemURL: &trashedURL)
        } catch {
            throw CopyFinderError.trashFailed(error.localizedDescription)
        }

        guard !fileManager.fileExists(atPath: candidate.path) else {
            throw CopyFinderError.trashFailed("The original file still exists.")
        }
        guard try scanner.snapshotForValidation(path: keeper.path) == currentKeeper else {
            throw CopyFinderError.fileChanged(keeper.path)
        }
    }
}

struct ReportService {
    func export(groups: [DuplicateGroup], to url: URL) throws {
        let fileExtension = url.pathExtension.lowercased()
        let text = fileExtension == "json" ? json(groups: groups) : csv(groups: groups)
        do {
            try text.write(to: url, atomically: true, encoding: .utf8)
        } catch {
            throw CopyFinderError.exportFailed(error.localizedDescription)
        }
    }

    private func csv(groups: [DuplicateGroup]) -> String {
        var rows = ["group,status,path,size,modified,sha256"]
        for group in groups {
            for file in group.files {
                let status = file.path == group.keeperPath ? "keep" : "duplicate"
                let values = [
                    String(group.id), status, file.path, String(file.size),
                    isoDate(file.modified), file.digest
                ]
                rows.append(values.map(csvValue).joined(separator: ","))
            }
        }
        return rows.joined(separator: "\n") + "\n"
    }

    private func json(groups: [DuplicateGroup]) -> String {
        let rows = groups.flatMap { group in
            group.files.map { file -> [String: Any] in
                [
                    "group": group.id,
                    "status": file.path == group.keeperPath ? "keep" : "duplicate",
                    "path": file.path,
                    "size": file.size,
                    "modified": isoDate(file.modified),
                    "sha256": file.digest
                ]
            }
        }
        guard JSONSerialization.isValidJSONObject(rows),
              let data = try? JSONSerialization.data(withJSONObject: rows, options: [.prettyPrinted, .sortedKeys]),
              let value = String(data: data, encoding: .utf8) else {
            return "[]\n"
        }
        return value + "\n"
    }

    private func csvValue(_ value: String) -> String {
        let safeValue = value.replacingOccurrences(of: "\r", with: " ")
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: ",", with: commaReplacement)
            .replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(safeValue)\""
    }

    private func isoDate(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }
}

enum SmokeTest {
    static func run() -> Int32 {
        let fileManager = FileManager.default
        let root = fileManager.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        do {
            try fileManager.createDirectory(at: root, withIntermediateDirectories: true)
            defer { try? fileManager.removeItem(at: root) }
            let content = Data("copyfinder-smoke".utf8)
            try content.write(to: root.appendingPathComponent("original.txt"))
            try content.write(to: root.appendingPathComponent("original - copy.txt"))
            try Data("different".utf8).write(to: root.appendingPathComponent("different.txt"))

            let result = try DuplicateScanner().scan(
                folder: root,
                options: ScanOptions(),
                cancellation: CancellationToken(),
                progress: { _ in }
            )
            let passed = result.groups.count == 1 && result.groups[0].files.count == 2
            let output: [String: Any] = [
                "application": applicationName,
                "version": applicationVersion,
                "smoke_test": passed ? "passed" : "failed",
                "duplicate_groups": result.groups.count,
                "duplicate_files": result.groups.first?.files.count ?? 0
            ]
            let data = try JSONSerialization.data(withJSONObject: output, options: [.prettyPrinted, .sortedKeys])
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
            return passed ? 0 : 1
        } catch {
            FileHandle.standardError.write(Data("Smoke test failed: \(error.localizedDescription)\n".utf8))
            return 1
        }
    }
}
