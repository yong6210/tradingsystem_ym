import AppKit
import Foundation
import Vision

func recognize(path: String) throws -> [String] {
    let url = URL(fileURLWithPath: path)
    guard let image = NSImage(contentsOf: url) else {
        throw NSError(domain: "ocr", code: 1, userInfo: [NSLocalizedDescriptionKey: "Unable to read image: \(path)"])
    }
    guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        throw NSError(domain: "ocr", code: 2, userInfo: [NSLocalizedDescriptionKey: "Unable to create CGImage: \(path)"])
    }

    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["ko-KR", "en-US"]

    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    try handler.perform([request])

    let observations = request.results ?? []
    return observations.compactMap { observation in
        observation.topCandidates(1).first?.string.trimmingCharacters(in: .whitespacesAndNewlines)
    }.filter { !$0.isEmpty }
}

let args = CommandLine.arguments.dropFirst()
if args.isEmpty {
    fputs("usage: swift ocr_storyboard_swift.swift IMAGE...\n", stderr)
    exit(64)
}

for path in args {
    do {
        let lines = try recognize(path: path)
        print("### \(path)")
        for line in lines {
            print(line)
        }
        print("")
    } catch {
        fputs("OCR failed for \(path): \(error)\n", stderr)
    }
}
