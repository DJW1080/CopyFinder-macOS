import AppKit
import SwiftUI

private let initialWindowWidth: CGFloat = 860
private let initialWindowHeight: CGFloat = 800

final class AppDelegate: NSObject, NSApplicationDelegate {
    private let model = AppModel()
    private var window: NSWindow?

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.appearance = NSAppearance(named: .darkAqua)
        configureMenu()
        configureIcon()

        let content = ContentView(model: model)
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: initialWindowWidth, height: initialWindowHeight),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = applicationName
        window.minSize = NSSize(width: 800, height: 650)
        window.center()
        window.contentView = NSHostingView(rootView: content)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        self.window = window
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    private func configureIcon() {
        guard let iconPath = Bundle.main.path(forResource: "copyfinder", ofType: "png"),
              let icon = NSImage(contentsOfFile: iconPath) else { return }
        NSApp.applicationIconImage = icon
    }

    private func configureMenu() {
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        menu.addItem(applicationItem)
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "About \(applicationName)", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)), keyEquivalent: "")
        applicationMenu.addItem(NSMenuItem.separator())
        applicationMenu.addItem(withTitle: "Quit \(applicationName)", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        NSApp.mainMenu = menu
    }
}
