#!/usr/bin/env python3
"""Offline integrity checks for the archived research package."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "release_manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def release_files() -> set[str]:
    return {
        str(path.relative_to(ROOT))
        for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and "__pycache__" not in path.parts
        and path.name != MANIFEST.name
    }


def verify_manifest() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest["files"]
    current = release_files()
    assert current == set(recorded), (
        f"Release file set changed; missing={sorted(set(recorded)-current)}, "
        f"unexpected={sorted(current-set(recorded))}"
    )
    for relative, metadata in recorded.items():
        path = ROOT / relative
        assert path.stat().st_size == metadata["bytes"], f"Size mismatch: {relative}"
        assert sha256(path) == metadata["sha256"], f"Checksum mismatch: {relative}"
    return len(recorded)


def verify_database(relative: str, expected: int) -> dict:
    path = ROOT / relative
    connection = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok", f"SQLite integrity failed: {relative}"
        rows = connection.execute("SELECT scientific_id,payload,sha256 FROM observations").fetchall()
        assert len(rows) == expected, f"Observation count mismatch: {relative}"
        assert len({row[0] for row in rows}) == expected, f"Duplicate scientific IDs: {relative}"
        for scientific_id, payload, stored_hash in rows:
            value = json.loads(payload)
            assert value["scientific_id"] == scientific_id, f"Identity mismatch: {relative}"
            assert hashlib.sha256(canonical(value)).hexdigest() == stored_hash, f"Payload hash mismatch: {relative}"
        attempts = connection.execute("SELECT COUNT(*) FROM events WHERE kind='start'").fetchone()[0]
        return {"observations": len(rows), "attempts": attempts}
    finally:
        connection.close()


def verify_accounting(results: dict) -> None:
    study1 = json.loads((ROOT / "outputs/main_reconciliation.json").read_text())
    assert study1["integrity_passed"] and study1["all_planned_accounted"]
    assert study1["planned"] == study1["committed"] == results["study1"]["observations"] == 800
    assert study1["attempts"] == results["study1"]["attempts"] == 801
    assert study1["technical_retries"] == 1

    study2 = json.loads((ROOT / "outputs/study2_rag/main_reconciliation.json").read_text())
    assert study2["integrity_passed"] and study2["all_planned_accounted"] and study2["collection_complete"]
    assert study2["planned"] == study2["committed"] == results["study2"]["observations"] == 200
    assert study2["attempts"] == results["study2"]["attempts"] == 200

    followup = json.loads((ROOT / "outputs/followup_rag/main_reconciliation.json").read_text())
    assert followup["technical_pass"]
    assert followup["expected"] == followup["committed"] == results["followup"]["observations"] == 394
    assert followup["finish_events"] == followup["terminal_events"] == 394


def main() -> int:
    try:
        file_count = verify_manifest()
        results = {
            "study1": verify_database("outputs/main/collection.sqlite3", 800),
            "study2": verify_database("outputs/study2_rag/main/collection.sqlite3", 200),
            "followup": verify_database("outputs/followup_rag/main/collection.sqlite3", 394),
        }
        verify_accounting(results)
    except (AssertionError, OSError, ValueError, sqlite3.Error, KeyError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "verified_files": file_count, "collections": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
