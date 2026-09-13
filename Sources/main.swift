import AppKit
import Darwin

if CommandLine.arguments.contains("--smoke-test") {
    exit(SmokeTest.run())
}

let application = NSApplication.shared
let applicationDelegate = AppDelegate()
application.delegate = applicationDelegate
application.run()
