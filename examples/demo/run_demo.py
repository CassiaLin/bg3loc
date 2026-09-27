"""Run a fictional, local-only production smoke test against installed BG3Loc.

This fixture contains no BG3 text or assets. The in-process HTTP endpoint stands in
for a translation provider, and the fake archive adapter stands in for LSLib. Its
output is evidence of CLI wiring, never a game-installable language file.
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
from threading import Thread

from bg3loc.cli import main
from bg3loc.production_finalize import ProductionFinalizeRequest, finalize_production_workspace


class _DemoProvider(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - standard library callback
        body = json.dumps(
            {
                "id": "fictional-request-1",
                "choices": [{"message": {"content": "Bonjour"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 2, "total_tokens": 14},
            }
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


class _FictionalArchiveAdapter:
    id = "fictional-demo"

    def convert_loca(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

    def create_package(self, source_dir: Path, destination: Path) -> None:
        raise RuntimeError("the fictional demo does not create game packages")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(*args: str) -> None:
    if main(list(args)) != 0:
        raise RuntimeError(f"BG3Loc command failed: {' '.join(args[:2])}")


def run_demo(root: Path) -> Path:
    root = root.resolve()
    if root.exists() and any(root.iterdir()):
        raise RuntimeError(f"demo output must be a fresh directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    extract_dir = root / "extract"
    normalized = extract_dir / "normalized"
    target_dir = extract_dir / "locales" / "French"
    normalized.mkdir(parents=True)
    target_dir.mkdir(parents=True)

    source = normalized / "English.jsonl"
    source.write_text(
        json.dumps(
            {
                "contentUid": "fictional-hello-1",
                "localeId": "English",
                "text": "Hello",
                "version": 1,
            }
        ) + "\n",
        encoding="utf-8",
    )
    target = normalized / "French.jsonl"
    target.write_text("", encoding="utf-8")
    target_xml = target_dir / "source.xml"
    target_xml.write_text(
        '<contentList><content contentuid="fictional-baseline" version="1">Salut</content></contentList>',
        encoding="utf-8",
    )
    target_loca = target_dir / "source.loca"
    target_loca.write_bytes(target_xml.read_bytes())
    package = root / "fictional" / "French.pak"
    package.parent.mkdir()
    package.write_bytes(b"FICTIONAL DEMO ONLY")
    extract = extract_dir / "extract-manifest.json"
    _write_json(
        extract,
        {
            "schemaVersion": "1.0",
            "scanManifest": str(root / "fictional-scan.json"),
            "sourceLocale": "English",
            "targetLocale": "French",
            "referenceLocales": [],
            "backend": {"id": "fictional-demo"},
            "locales": [
                {
                    "localeId": "English", "packageFile": str(root / "fictional" / "English.pak"),
                    "locaEntry": "Localization/English/english.loca",
                    "sourceLoca": str(root / "fictional" / "English.loca"),
                    "sourceXml": str(root / "fictional" / "English.xml"),
                    "normalized": str(source), "nodeCount": 1,
                },
                {
                    "localeId": "French", "packageFile": str(package),
                    "locaEntry": "Localization/French/french.loca",
                    "sourceLoca": str(target_loca), "sourceXml": str(target_xml),
                    "normalized": str(target), "nodeCount": 1,
                },
            ],
            "aligned": str(extract_dir / "aligned.jsonl"),
            "roundtripValidation": str(extract_dir / "roundtrip.json"),
        },
    )
    mappings = root / "research-mappings.jsonl"
    mappings.write_text(
        json.dumps(
            {
                "contentUid": "fictional-hello-1", "mappingType": "bark-speaker",
                "classification": "bark", "evidence": [], "version": "1", "metadata": {},
            }
        ) + "\n",
        encoding="utf-8",
    )
    ruleset = root / "ruleset.json"
    _write_json(
        ruleset,
        {
            "version": "fictional-demo-v1", "sourceLocale": "English", "targetLocale": "French",
            "commonRules": ["Preserve meaning."],
            "categoryRules": {"bark": ["Keep short lines concise."]}, "glossary": [],
        },
    )

    workspace = root / "production"
    _run(
        "production", "prepare", "--extract", str(extract), "--source", str(source),
        "--research-mappings", str(mappings), "--ruleset", str(ruleset),
        "--output", str(workspace),
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), _DemoProvider)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        _run(
            "production", "execute-openai-compatible", "--workspace", str(workspace),
            "--base-url", f"http://127.0.0.1:{server.server_port}",
            "--model", "fictional-local-model", "--run-id", "demo-run-1",
            "--worker-id", "demo-worker-1",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    _run("production", "qa", "--workspace", str(workspace))
    report_path = root / "report.json"
    _run("production", "report", "--workspace", str(workspace), "--json", str(report_path))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report["completion"]["MERGE_READY"]["count"] != 1:
        raise RuntimeError("fictional translation did not become merge-ready")
    output = root / "final-output"
    result = finalize_production_workspace(
        ProductionFinalizeRequest(workspace=workspace, output=output, container="loca-only"),
        rebuild_backend=_FictionalArchiveAdapter(),
    )
    if result.manifest["completion"]["mergeReadyCount"] != 1:
        raise RuntimeError("fictional finalize did not pass")
    print(f"Fictional demo PASS: {result.manifest_path}")
    print("Do not install demo artifacts into a game.")
    return result.manifest_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Fresh demo output directory")
    args = parser.parse_args()
    run_demo(args.output)
