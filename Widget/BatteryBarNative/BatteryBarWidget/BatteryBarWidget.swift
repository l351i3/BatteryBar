//
//  BatteryBarWidget.swift
//  BatteryBarWidget
//
//  Battery Bar snapshot-reading prototype.
//

import Foundation
import SwiftUI
import WidgetKit

private let widgetKind = "BatteryBarWidget"

private struct BatterySnapshot: Decodable {
    let schemaVersion: Int
    let updatedAt: TimeInterval
    let devices: [BatteryDevice]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case updatedAt = "updated_at"
        case devices
    }
}

private struct BatteryDevice: Decodable, Identifiable {
    let deviceID: String
    let name: String
    let category: String
    let level: Int
    let charging: Bool?
    let powerState: String
    let cached: Bool

    var id: String {
        deviceID
    }

    enum CodingKeys: String, CodingKey {
        case deviceID = "device_id"
        case name
        case category
        case level
        case charging
        case powerState = "power_state"
        case cached
    }
}

private enum SnapshotLoadState {
    case loaded(BatterySnapshot)
    case fileNotFound(String)
    case invalid(String)
}

private enum SnapshotLoader {
    static var snapshotURL: URL {
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


    static func load() -> SnapshotLoadState {
        let url = snapshotURL

        guard FileManager.default.fileExists(
            atPath: url.path
        ) else {
            return .fileNotFound(url.path)
        }

        do {
            let data = try Data(contentsOf: url)
            let decoder = JSONDecoder()
            let snapshot = try decoder.decode(
                BatterySnapshot.self,
                from: data
            )

            guard snapshot.schemaVersion == 2 else {
                return .invalid(
                    "不支持的快照版本：\(snapshot.schemaVersion)"
                )
            }

            return .loaded(snapshot)
        } catch {
            return .invalid(
                "\(type(of: error)): \(error.localizedDescription)"
            )
        }
    }
}

struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> BatteryEntry {
        BatteryEntry(
            date: Date(),
            state: .loaded(
                BatterySnapshot(
                    schemaVersion: 2,
                    updatedAt: Date().timeIntervalSince1970,
                    devices: [
                        BatteryDevice(
                            deviceID: "preview-keyboard",
                            name: "MX Keys",
                            category: "keyboard",
                            level: 80,
                            charging: nil,
                            powerState: "unknown",
                            cached: false
                        ),
                        BatteryDevice(
                            deviceID: "preview-microphone",
                            name: "DJI Mic Mini",
                            category: "microphone",
                            level: 70,
                            charging: false,
                            powerState: "discharging",
                            cached: false
                        )
                    ]
                )
            )
        )
    }

    func getSnapshot(
        in context: Context,
        completion: @escaping (BatteryEntry) -> Void
    ) {
        completion(
            BatteryEntry(
                date: Date(),
                state: SnapshotLoader.load()
            )
        )
    }

    func getTimeline(
        in context: Context,
        completion: @escaping (Timeline<BatteryEntry>) -> Void
    ) {
        let now = Date()
        let entry = BatteryEntry(
            date: now,
            state: SnapshotLoader.load()
        )
        let nextRefresh = Calendar.current.date(
            byAdding: .minute,
            value: 15,
            to: now
        ) ?? now.addingTimeInterval(15 * 60)

        completion(
            Timeline(
                entries: [entry],
                policy: .after(nextRefresh)
            )
        )
    }
}

struct BatteryEntry: TimelineEntry {
    let date: Date
    fileprivate let state: SnapshotLoadState
}

struct BatteryBarWidgetEntryView: View {
    var entry: Provider.Entry

    @Environment(\.widgetFamily)
    private var family

    var body: some View {
        switch entry.state {
        case .loaded(let snapshot):
            loadedView(snapshot)

        case .fileNotFound(let path):
            diagnosticView(
                title: "未找到快照",
                detail: path
            )

        case .invalid(let message):
            diagnosticView(
                title: "快照读取失败",
                detail: message
            )
        }
    }

    @ViewBuilder
    private func loadedView(
        _ snapshot: BatterySnapshot
    ) -> some View {
        let limit = deviceLimit(for: family)
        let devices = Array(
            snapshot.devices.prefix(limit)
        )

        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Label(
                    "Battery Bar",
                    systemImage: "battery.75percent"
                )
                .font(.headline)

                Spacer()

                Text("\(snapshot.devices.count) 台")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            if devices.isEmpty {
                Spacer()

                Text("暂无可读取电量的外设")
                    .font(.callout)
                    .foregroundStyle(.secondary)

                Spacer()
            } else {
                ForEach(devices) { device in
                    deviceRow(device)
                }

                if snapshot.devices.count > devices.count {
                    Text(
                        "另有 \(snapshot.devices.count - devices.count) 台设备"
                    )
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }

                Spacer(minLength: 0)
            }

            Text(
                Date(
                    timeIntervalSince1970:
                        snapshot.updatedAt
                ),
                style: .relative
            )
            .font(.caption2)
            .foregroundStyle(.tertiary)
        }
        .padding()
    }

    private func deviceRow(
        _ device: BatteryDevice
    ) -> some View {
        HStack(spacing: 8) {
            Image(
                systemName: categorySymbol(
                    device.category
                )
            )
            .frame(width: 18)
            .foregroundStyle(
                levelColor(device.level)
            )

            Text(device.name)
                .font(.caption)
                .lineLimit(1)

            Spacer(minLength: 6)

            if device.charging == true {
                Image(
                    systemName:
                        "bolt.fill"
                )
                .font(.caption2)
                .foregroundStyle(.green)
            }

            Text("\(device.level)%")
                .font(.caption.monospacedDigit())
                .fontWeight(.semibold)
                .foregroundStyle(
                    levelColor(device.level)
                )
        }
    }

    private func diagnosticView(
        title: String,
        detail: String
    ) -> some View {
        VStack(
            alignment: .leading,
            spacing: 10
        ) {
            Label(
                title,
                systemImage:
                    "exclamationmark.triangle"
            )
            .font(.headline)

            Text(detail)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(6)

            Spacer()

            Text("Battery Bar Widget 读取探针")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .padding()
    }

    private func deviceLimit(
        for family: WidgetFamily
    ) -> Int {
        switch family {
        case .systemSmall:
            return 3

        case .systemMedium:
            return 5

        case .systemLarge:
            return 10

        default:
            return 5
        }
    }

    private func categorySymbol(
        _ category: String
    ) -> String {
        switch category {
        case "keyboard":
            return "keyboard"

        case "mouse":
            return "computermouse"

        case "microphone":
            return "mic"

        case "headphones":
            return "headphones"

        case "speaker":
            return "hifispeaker"

        case "trackpad":
            return "rectangle.and.hand.point.up.left"

        case "stylus":
            return "pencil.tip"

        case "controller":
            return "gamecontroller"

        default:
            return "battery.50percent"
        }
    }

    private func levelColor(
        _ level: Int
    ) -> Color {
        if level <= 10 {
            return .red
        }

        if level <= 25 {
            return .orange
        }

        return .primary
    }
}

struct BatteryBarWidget: Widget {
    let kind = widgetKind

    var body: some WidgetConfiguration {
        StaticConfiguration(
            kind: kind,
            provider: Provider()
        ) { entry in
            BatteryBarWidgetEntryView(
                entry: entry
            )
            .containerBackground(
                .fill.tertiary,
                for: .widget
            )
        }
        .configurationDisplayName(
            "Battery Bar"
        )
        .description(
            "显示已连接外设的电量。"
        )
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .systemLarge
        ])
    }
}
