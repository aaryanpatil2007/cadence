// gait-sign: Secure Enclave P-256 keygen + raw (r||s) ECDSA signing CLI.
//   gait-sign gen   -> create SE key at ~/.gait/key.bin (0600), print pubkey PEM
//   gait-sign pub   -> print pubkey PEM
//   gait-sign sign <base64url payload> -> print base64url raw r||s signature
import Foundation
import CryptoKit

func gaitDir() -> URL {
    let home = FileManager.default.homeDirectoryForCurrentUser
    let dir = home.appendingPathComponent(".gait")
    try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true,
        attributes: [.posixPermissions: 0o700])
    return dir
}

func keyURL() -> URL { gaitDir().appendingPathComponent("key.bin") }

func b64uDecode(_ s: String) -> Data? {
    var t = s.replacingOccurrences(of: "-", with: "+")
             .replacingOccurrences(of: "_", with: "/")
    while t.count % 4 != 0 { t += "=" }
    return Data(base64Encoded: t)
}

func b64uEncode(_ d: Data) -> String {
    d.base64EncodedString()
        .replacingOccurrences(of: "+", with: "-")
        .replacingOccurrences(of: "/", with: "_")
        .replacingOccurrences(of: "=", with: "")
}

func loadKey() throws -> SecureEnclave.P256.Signing.PrivateKey {
    let data = try Data(contentsOf: keyURL())
    return try SecureEnclave.P256.Signing.PrivateKey(dataRepresentation: data)
}

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
guard args.count >= 2 else { fail("usage: gait-sign gen|pub|sign <b64url>") }

guard SecureEnclave.isAvailable else { fail("secure enclave unavailable") }

switch args[1] {
case "gen":
    let key: SecureEnclave.P256.Signing.PrivateKey
    do { key = try SecureEnclave.P256.Signing.PrivateKey() }
    catch { fail("keygen failed: \(error)") }
    do {
        try key.dataRepresentation.write(to: keyURL())
        try FileManager.default.setAttributes([.posixPermissions: 0o600],
            ofItemAtPath: keyURL().path)
    } catch { fail("key write failed: \(error)") }
    print(key.publicKey.pemRepresentation)
case "pub":
    do { print(try loadKey().publicKey.pemRepresentation) }
    catch { fail("no key: \(error)") }
case "sign":
    guard args.count >= 3, let payload = b64uDecode(args[2]) else {
        fail("sign: need base64url payload")
    }
    do {
        let key = try loadKey()
        let sig = try key.signature(for: payload)
        print(b64uEncode(sig.rawRepresentation))
    } catch { fail("sign failed: \(error)") }
default:
    fail("unknown command \(args[1])")
}
