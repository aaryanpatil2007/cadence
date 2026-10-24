// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "gait-sign",
    platforms: [.macOS(.v13)],
    targets: [
        .executableTarget(name: "gait-sign", path: "Sources")
    ]
)
