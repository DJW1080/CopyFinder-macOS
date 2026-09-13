import AppKit
import Combine
import Foundation

private let settingsKeyPrefix = "copyfinder."

final class AppModel: ObservableObject {
    @Published var folderPath = ""
    @Published var statusMessage = "Choose a folder to find duplicate files."
    @Published var summaryMessage = "No scan yet"
    @Published var groups = [DuplicateGroup]()
    @Published var isScanning = false
    @Published var keepRule = KeepRule.original
    @Published var preferredFolder = ""
    @Published var duplicateLimitText = String(defaultDuplicateLimit)
    @Published var minimumKilobytesText = "0"
    @Published var excludedExtensionsText = ""
    @Published var skipHidden = true
    @Published var skipSystem = true

    private let scanner = DuplicateScanner()
    private let trashService = TrashService()
    private let reportService = ReportService()
    private var cancellation: CancellationToken?

    init() {
        restoreSettings()
    }

    func chooseFolder() {
        let panel = NSOpenPanel()
        panel.title = "Choose a folder to scan"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            folderPath = url.path
        }
    }

    func choosePreferredFolder() {
        let panel = NSOpenPanel()
        panel.title = "Choose the folder whose copies should be kept"
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        if panel.runModal() == .OK, let url = panel.url {
            preferredFolder = url.path
        }
    }

    func startScan() {
        guard !isScanning else { return }
        let folder = URL(fileURLWithPath: folderPath)
        let options = currentOptions()
        saveSettings()
        let token = CancellationToken()
        cancellation = token
        groups = []
        isScanning = true
        summaryMessage = "Scanning…"
        statusMessage = "Reading folders…"

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self = self else { return }
            do {
                let result = try self.scanner.scan(
                    folder: folder,
                    options: options,
                    cancellation: token,
                    progress: { message in
                        DispatchQueue.main.async { self.statusMessage = message }
                    }
                )
                DispatchQueue.main.async {
                    self.groups = result.groups
                    self.isScanning = false
                    self.cancellation = nil
                    let duplicates = result.groups.reduce(0) { $0 + max(0, $1.files.count - 1) }
                    self.summaryMessage = "\(result.groups.count) groups • \(duplicates) duplicates"
                    let limitMessage = result.limitReached ? " The result limit was reached." : ""
                    self.statusMessage = "Scanned \(result.scannedFiles) files; skipped \(result.skippedFiles).\(limitMessage)"
                }
            } catch {
                DispatchQueue.main.async {
                    self.isScanning = false
                    self.cancellation = nil
                    self.statusMessage = error.localizedDescription
                    self.summaryMessage = "Scan did not finish"
                }
            }
        }
    }

    func cancelScan() {
        cancellation?.cancel()
        statusMessage = "Cancelling…"
    }

    func toggleExpanded(groupID: Int) {
        guard let index = groupIndex(groupID) else { return }
        groups[index].expanded.toggle()
    }

    func setSelected(groupID: Int, path: String, selected: Bool) {
        guard let index = groupIndex(groupID), path != groups[index].keeperPath else { return }
        if selected {
            groups[index].selectedPaths.insert(path)
        } else {
            groups[index].selectedPaths.remove(path)
        }
    }

    func keep(groupID: Int, path: String) {
        guard let index = groupIndex(groupID), groups[index].files.contains(where: { $0.path == path }) else { return }
        let previousKeeper = groups[index].keeperPath
        groups[index].keeperPath = path
        groups[index].selectedPaths.remove(path)
        if !previousKeeper.isEmpty {
            groups[index].selectedPaths.insert(previousKeeper)
        }
        groups[index].files.sort { left, _ in left.path == path }
    }

    func selectAll() {
        for index in groups.indices {
            groups[index].selectedPaths = Set(groups[index].files.map(\.path).filter { $0 != groups[index].keeperPath })
        }
    }

    func deselectAll() {
        for index in groups.indices {
            groups[index].selectedPaths.removeAll()
        }
    }

    func reveal(path: String) {
        NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
    }

    func deleteSelected() {
        let selectedCount = groups.reduce(0) { $0 + $1.selectedPaths.count }
        guard selectedCount > 0 else {
            statusMessage = "Select at least one duplicate first."
            return
        }

        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = "Move \(selectedCount) selected duplicate\(selectedCount == 1 ? "" : "s") to Trash?"
        alert.informativeText = "CopyFinder will check every selected file against the kept copy immediately before moving it."
        alert.addButton(withTitle: "Move to Trash")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }

        var removedPaths = Set<String>()
        var failureMessages = [String]()
        for group in groups {
            guard let keeper = group.files.first(where: { $0.path == group.keeperPath }) else { continue }
            for candidate in group.files where group.selectedPaths.contains(candidate.path) {
                do {
                    try trashService.moveToTrash(candidate: candidate, keeper: keeper)
                    removedPaths.insert(candidate.path)
                } catch {
                    failureMessages.append(error.localizedDescription)
                }
            }
        }
        removeFiles(paths: removedPaths)
        if failureMessages.isEmpty {
            statusMessage = "Moved \(removedPaths.count) duplicate\(removedPaths.count == 1 ? "" : "s") to Trash."
        } else {
            statusMessage = "Moved \(removedPaths.count); left \(failureMessages.count) alone. \(failureMessages[0])"
        }
    }

    func exportReport() {
        guard !groups.isEmpty else {
            statusMessage = "Scan for duplicates before exporting a report."
            return
        }
        let panel = NSSavePanel()
        panel.title = "Export duplicate report"
        panel.nameFieldStringValue = "CopyFinder-report.csv"
        panel.allowedFileTypes = ["csv", "json"]
        guard panel.runModal() == .OK, let url = panel.url else { return }
        do {
            try reportService.export(groups: groups, to: url)
            statusMessage = "Report saved to \(url.path)."
        } catch {
            statusMessage = error.localizedDescription
        }
    }

    private func currentOptions() -> ScanOptions {
        let requestedLimit = Int(duplicateLimitText) ?? defaultDuplicateLimit
        let minimumKilobytes = max(0, Int64(minimumKilobytesText) ?? 0)
        let extensions = excludedExtensionsText
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased().replacingOccurrences(of: ".", with: "") }
            .filter { !$0.isEmpty }
        return ScanOptions(
            duplicateLimit: min(max(1, requestedLimit), maximumDuplicateLimit),
            keepRule: keepRule,
            preferredFolder: preferredFolder,
            minimumBytes: minimumKilobytes * bytesPerKilobyte,
            skipHidden: skipHidden,
            skipSystem: skipSystem,
            excludedExtensions: Set(extensions)
        )
    }

    private func groupIndex(_ id: Int) -> Int? {
        groups.firstIndex(where: { $0.id == id })
    }

    private func removeFiles(paths: Set<String>) {
        guard !paths.isEmpty else { return }
        for index in groups.indices {
            groups[index].files.removeAll { paths.contains($0.path) }
            groups[index].selectedPaths.subtract(paths)
        }
        groups.removeAll { $0.files.count < 2 }
    }

    private func restoreSettings() {
        let defaults = UserDefaults.standard
        if let value = defaults.string(forKey: settingsKeyPrefix + "keepRule"), let rule = KeepRule(rawValue: value) {
            keepRule = rule
        }
        preferredFolder = defaults.string(forKey: settingsKeyPrefix + "preferredFolder") ?? ""
        duplicateLimitText = defaults.string(forKey: settingsKeyPrefix + "duplicateLimit") ?? String(defaultDuplicateLimit)
        minimumKilobytesText = defaults.string(forKey: settingsKeyPrefix + "minimumKilobytes") ?? "0"
        excludedExtensionsText = defaults.string(forKey: settingsKeyPrefix + "excludedExtensions") ?? ""
        if defaults.object(forKey: settingsKeyPrefix + "skipHidden") != nil {
            skipHidden = defaults.bool(forKey: settingsKeyPrefix + "skipHidden")
        }
        if defaults.object(forKey: settingsKeyPrefix + "skipSystem") != nil {
            skipSystem = defaults.bool(forKey: settingsKeyPrefix + "skipSystem")
        }
    }

    private func saveSettings() {
        let defaults = UserDefaults.standard
        defaults.set(keepRule.rawValue, forKey: settingsKeyPrefix + "keepRule")
        defaults.set(preferredFolder, forKey: settingsKeyPrefix + "preferredFolder")
        defaults.set(duplicateLimitText, forKey: settingsKeyPrefix + "duplicateLimit")
        defaults.set(minimumKilobytesText, forKey: settingsKeyPrefix + "minimumKilobytes")
        defaults.set(excludedExtensionsText, forKey: settingsKeyPrefix + "excludedExtensions")
        defaults.set(skipHidden, forKey: settingsKeyPrefix + "skipHidden")
        defaults.set(skipSystem, forKey: settingsKeyPrefix + "skipSystem")
    }
}
