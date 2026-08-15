//
//  BatteryBarNativeApp.swift
//  BatteryBarNative
//
//  Created by l351i3 on 2026/7/14.
//

import SwiftUI
import WidgetKit
import Foundation
import Darwin

final class WidgetReloadMonitor {
    private var directorySource: DispatchSourceFileSystemObject?
    private var directoryDescriptor: CInt = -1
    private var lastSnapshotModification: Date?

    private var snapshotURL: URL {
        FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0]
        .appendingPathComponent(
            "Battery Bar",
            isDirectory: true
        )
        .appendingPathComponent(
            "snapshot.json",
            isDirectory: false
        )
    }

    private var snapshotDirectoryURL: URL {
        snapshotURL.deletingLastPathComponent()
    }

    init() {
        ensureLoginItem()
        startWatching()
    }

    private func ensureLoginItem() {
        let bundlePath = Bundle.main.bundlePath

        let checkProcess = Process()
        checkProcess.executableURL = URL(
            fileURLWithPath: "/usr/bin/osascript"
        )
        checkProcess.arguments = [
            "-e",
            "tell application \"System Events\" "
                + "to get the name of every login item"
        ]

        let checkPipe = Pipe()
        checkProcess.standardOutput = checkPipe

        do {
            try checkProcess.run()
            checkProcess.waitUntilExit()

            let data = checkPipe
                .fileHandleForReading
                .readDataToEndOfFile()

            if let names = String(
                data: data,
                encoding: .utf8
            ),
               names.contains(
                   "BatteryBarNative"
               ) {
                return
            }
        } catch {
            return
        }

        let addProcess = Process()
        addProcess.executableURL = URL(
            fileURLWithPath: "/usr/bin/osascript"
        )
        addProcess.arguments = [
            "-e",
            "tell application \"System Events\" "
                + "to make login item at end "
                + "with properties {path:\"\(bundlePath)\", "
                + "hidden:true}"
        ]

        do {
            try addProcess.run()
            addProcess.waitUntilExit()
        } catch {
            // Best effort
        }
    }

    private func startWatching() {
        let fm = FileManager.default
        let dir = snapshotDirectoryURL

        try? fm.createDirectory(
            at: dir,
            withIntermediateDirectories: true
        )

        directoryDescriptor = open(
            dir.path,
            O_EVTONLY
        )

        guard directoryDescriptor >= 0 else {
            return
        }

        let source = DispatchSource.makeFileSystemObjectSource(
            fileDescriptor: directoryDescriptor,
            eventMask: .write,
            queue: .main
        )

        source.setEventHandler { [weak self] in
            self?.checkAndReloadWidget()
        }

        source.setCancelHandler { [weak self] in
            if let fd = self?.directoryDescriptor,
               fd >= 0 {
                close(fd)
                self?.directoryDescriptor = -1
            }
        }

        source.resume()
        directorySource = source

        checkAndReloadWidget()
    }

    private func checkAndReloadWidget() {
        let fm = FileManager.default

        guard fm.fileExists(
            atPath: snapshotURL.path
        ) else {
            return
        }

        do {
            let attrs = try fm.attributesOfItem(
                atPath: snapshotURL.path
            )
            let modDate = attrs[.modificationDate]
                as? Date

            guard modDate
                != lastSnapshotModification
            else {
                return
            }

            lastSnapshotModification = modDate
            WidgetCenter.shared.reloadTimelines(
                ofKind: "BatteryBarWidget"
            )
        } catch {
            // Best effort — ignore errors
        }
    }
}

@main
struct BatteryBarNativeApp: App {
    private let monitor = WidgetReloadMonitor()

    var body: some Scene {
        Settings {
            EmptyView()
        }
    }
}
