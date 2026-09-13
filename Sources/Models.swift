import Foundation

let applicationName = "CopyFinder"
let applicationVersion = "0.1.0-beta.1"
let defaultDuplicateLimit = 500
let maximumDuplicateLimit = 10_000
let bytesPerKilobyte: Int64 = 1_024

enum KeepRule: String, CaseIterable, Identifiable {
    case original = "Original"
    case shortestName = "Shortest name"
    case oldestFile = "Oldest file"
    case newestFile = "Newest file"
    case folder = "Folder"
    case highestResolution = "Highest Resolution"

    var id: String { rawValue }
}

struct ScanOptions {
    var duplicateLimit = defaultDuplicateLimit
    var keepRule = KeepRule.original
    var preferredFolder = ""
    var minimumBytes: Int64 = 0
    var skipHidden = true
    var skipSystem = true
    var excludedExtensions = Set<String>()
}

struct FileSnapshot: Identifiable, Hashable {
    let path: String
    let size: Int64
    let modified: Date
    let resourceIdentifier: String
    let digest: String
    let pixelArea: Int

    var id: String { path }
    var url: URL { URL(fileURLWithPath: path) }
    var name: String { url.lastPathComponent }
}

struct DuplicateGroup: Identifiable {
    let id: Int
    var files: [FileSnapshot]
    var keeperPath: String
    var selectedPaths: Set<String>
    var expanded = true

    init(id: Int, files: [FileSnapshot]) {
        self.id = id
        self.files = files
        keeperPath = files.first?.path ?? ""
        selectedPaths = Set(files.dropFirst().map(\.path))
    }

    var selectedCount: Int { selectedPaths.count }
}

struct ScanResult {
    let groups: [DuplicateGroup]
    let scannedFiles: Int
    let skippedFiles: Int
    let limitReached: Bool
}

enum CopyFinderError: LocalizedError {
    case invalidFolder
    case scanCancelled
    case fileChanged(String)
    case unsafeDuplicate(String)
    case trashFailed(String)
    case exportFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidFolder:
            return "Choose a real folder to scan."
        case .scanCancelled:
            return "Scan cancelled."
        case .fileChanged(let path):
            return "The file changed after scanning and was left alone: \(path)"
        case .unsafeDuplicate(let path):
            return "CopyFinder could not safely confirm this duplicate: \(path)"
        case .trashFailed(let message):
            return "Trash failed: \(message)"
        case .exportFailed(let message):
            return "Export failed: \(message)"
        }
    }
}

func formattedFileSize(_ bytes: Int64) -> String {
    ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
}

func formattedModifiedDate(_ date: Date) -> String {
    let formatter = DateFormatter()
    formatter.dateStyle = .short
    formatter.timeStyle = .short
    return formatter.string(from: date)
}
