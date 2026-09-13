import AppKit
import SwiftUI

private let accentBlue = Color(red: 0.02, green: 0.60, blue: 0.96)
private let panelBackground = Color(red: 0.10, green: 0.11, blue: 0.13)
private let groupBackground = Color(red: 0.10, green: 0.16, blue: 0.23)
private let alternateRowBackground = Color(red: 0.07, green: 0.08, blue: 0.09)
private let windowPadding: CGFloat = 8

struct ContentView: View {
    @ObservedObject var model: AppModel
    @State private var settingsExpanded = false

    var body: some View {
        VStack(spacing: 7) {
            HeaderView()
            folderControls
            settings
            statusStrip
            columnHeader
            results
            actionBar
        }
        .padding(windowPadding)
        .frame(minWidth: 800, minHeight: 700)
        .background(Color.black)
    }

    private var folderControls: some View {
        HStack(spacing: 8) {
            TextField("Folder to scan", text: $model.folderPath)
                .textFieldStyle(RoundedBorderTextFieldStyle())
            Button("Browse", action: model.chooseFolder)
            Button("Scan", action: model.startScan)
                .disabled(model.folderPath.isEmpty || model.isScanning)
                .foregroundColor(accentBlue)
            Button("Cancel", action: model.cancelScan)
                .disabled(!model.isScanning)
        }
        .padding(7)
        .background(panelBackground)
        .cornerRadius(3)
    }

    private var settings: some View {
        VStack(alignment: .leading, spacing: 7) {
            Button(action: { settingsExpanded.toggle() }) {
                Text((settingsExpanded ? "▼" : "▶") + " Scan Settings")
                    .foregroundColor(.white)
            }
            .buttonStyle(BorderlessButtonStyle())

            if settingsExpanded {
                VStack(spacing: 10) {
                    HStack(spacing: 12) {
                        Text("Keep")
                        Picker("", selection: $model.keepRule) {
                            ForEach(KeepRule.allCases) { rule in
                                Text(rule.rawValue).tag(rule)
                            }
                        }
                        .labelsHidden()
                        .frame(width: 170)

                        Spacer()
                        Text("Folder")
                        TextField("Used only by Folder rule", text: $model.preferredFolder)
                            .textFieldStyle(RoundedBorderTextFieldStyle())
                            .frame(minWidth: 190)
                        Button("Choose", action: model.choosePreferredFolder)
                    }
                    HStack(spacing: 12) {
                        Text("Limit")
                        TextField("500", text: $model.duplicateLimitText)
                            .textFieldStyle(RoundedBorderTextFieldStyle())
                            .frame(width: 80)
                        Text("Min KB")
                        TextField("0", text: $model.minimumKilobytesText)
                            .textFieldStyle(RoundedBorderTextFieldStyle())
                            .frame(width: 80)
                        Spacer()
                        Text("Exclude")
                        TextField("tmp, bak, log", text: $model.excludedExtensionsText)
                            .textFieldStyle(RoundedBorderTextFieldStyle())
                            .frame(minWidth: 210)
                    }
                    HStack(spacing: 24) {
                        Toggle("Skip hidden files", isOn: $model.skipHidden)
                        Toggle("Skip system files", isOn: $model.skipSystem)
                        Spacer()
                    }
                }
                .padding(10)
                .background(panelBackground)
                .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.gray.opacity(0.35)))
            }
        }
    }

    private var statusStrip: some View {
        HStack {
            if model.isScanning {
                Text("Scanning")
                    .foregroundColor(accentBlue)
            }
            Spacer()
            Text(model.summaryMessage)
                .foregroundColor(accentBlue)
        }
        .padding(8)
        .background(panelBackground)
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.gray.opacity(0.35)))
    }

    private var columnHeader: some View {
        HStack(spacing: 8) {
            Text("Actions").frame(width: 205)
            Text("File Name").frame(maxWidth: .infinity, alignment: .leading)
            Text("Size").frame(width: 80, alignment: .trailing)
            Text("Modified").frame(width: 125, alignment: .leading)
            Text("Path").frame(width: 235, alignment: .leading)
        }
        .font(.system(size: 13, weight: .semibold))
        .padding(.horizontal, 8)
        .frame(height: 32)
        .background(accentBlue)
    }

    private var results: some View {
        ScrollView(.vertical) {
            VStack(spacing: 0) {
                if model.groups.isEmpty && !model.isScanning {
                    Text("Duplicate groups will appear here after the scan.")
                        .foregroundColor(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 220)
                }
                ForEach(model.groups) { group in
                    DuplicateGroupView(model: model, group: group)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(red: 0.04, green: 0.05, blue: 0.06))
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.gray.opacity(0.35)))
    }

    private var actionBar: some View {
        HStack(spacing: 8) {
            Text(model.statusMessage)
                .foregroundColor(accentBlue)
                .lineLimit(2)
            Spacer()
            Button("Export report", action: model.exportReport)
            Button("Select duplicates", action: model.selectAll)
            Button("Deselect all", action: model.deselectAll)
            Button("Delete Duplicates", action: model.deleteSelected)
                .foregroundColor(.red)
        }
        .padding(8)
        .background(panelBackground)
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(Color.gray.opacity(0.35)))
    }
}

private struct HeaderView: View {
    var body: some View {
        Group {
            if let image = bundledImage(named: "banner", extension: "png") {
                Image(nsImage: image)
                    .resizable()
                    .scaledToFit()
            } else {
                HStack {
                    Text(applicationName).font(.system(size: 34, weight: .bold))
                    Spacer()
                    Text("Technification").font(.system(size: 30, weight: .bold))
                }
                .padding(24)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 86, maxHeight: 86)
        .background(Color(red: 0.0, green: 0.0, blue: 0.07))
    }
}

private struct DuplicateGroupView: View {
    @ObservedObject var model: AppModel
    let group: DuplicateGroup

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 7) {
                Button((group.expanded ? "▼" : "▶") + " Group \(group.id)") {
                    model.toggleExpanded(groupID: group.id)
                }
                Button("Select") {
                    for file in group.files where file.path != group.keeperPath {
                        model.setSelected(groupID: group.id, path: file.path, selected: true)
                    }
                }
                Button("Deselect") {
                    for file in group.files {
                        model.setSelected(groupID: group.id, path: file.path, selected: false)
                    }
                }
                Text("Same size and SHA-256 hash \(group.files.first?.digest.prefix(12).uppercased() ?? "")")
                    .foregroundColor(accentBlue)
                    .lineLimit(1)
                Spacer()
            }
            .padding(6)
            .background(groupBackground)

            if group.expanded {
                ForEach(group.files.indices, id: \.self) { index in
                    FileRowView(
                        model: model,
                        group: group,
                        file: group.files[index],
                        alternate: index.isMultiple(of: 2)
                    )
                }
            }
        }
    }
}

private struct FileRowView: View {
    @ObservedObject var model: AppModel
    let group: DuplicateGroup
    let file: FileSnapshot
    let alternate: Bool

    var body: some View {
        HStack(spacing: 8) {
            Toggle("", isOn: Binding(
                get: { group.selectedPaths.contains(file.path) },
                set: { model.setSelected(groupID: group.id, path: file.path, selected: $0) }
            ))
            .labelsHidden()
            .disabled(file.path == group.keeperPath)
            .frame(width: 26)

            Image(nsImage: NSWorkspace.shared.icon(forFile: file.path))
                .resizable()
                .frame(width: 38, height: 38)
            Button("Keep") { model.keep(groupID: group.id, path: file.path) }
                .disabled(file.path == group.keeperPath)
                .frame(width: 50)
            Button("Open") { model.reveal(path: file.path) }
                .frame(width: 50)
            Text(file.name)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(formattedFileSize(file.size))
                .frame(width: 80, alignment: .trailing)
            Text(formattedModifiedDate(file.modified))
                .lineLimit(1)
                .frame(width: 125, alignment: .leading)
            Text(file.url.deletingLastPathComponent().path)
                .lineLimit(1)
                .truncationMode(.middle)
                .frame(width: 235, alignment: .leading)
        }
        .padding(.horizontal, 8)
        .frame(minHeight: 66)
        .background(alternate ? alternateRowBackground : groupBackground.opacity(0.65))
    }
}

private func bundledImage(named name: String, extension fileExtension: String) -> NSImage? {
    guard let path = Bundle.main.path(forResource: name, ofType: fileExtension) else { return nil }
    return NSImage(contentsOfFile: path)
}
