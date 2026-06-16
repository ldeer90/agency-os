#!/usr/bin/env python3
"""Evaluate Headroom on safe real-shaped agency fixtures."""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
RESULTS = ROOT / "results"
SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password|private[_-]?key)\s*[:=]"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"ya29\.[A-Za-z0-9_-]+"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
]


@dataclass
class CompressionResult:
    mode: str
    text: str
    tokens_before: int
    tokens_after: int
    tokens_saved: int
    compression_ratio: float
    transforms: list[str]
    latency_ms: int


def estimate_tokens(text: str) -> int:
    # Conservative local estimate for comparing fixtures without provider calls.
    return max(1, round(len(text) / 4))


def has_secret_like_text(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def compact_baseline(payload: dict[str, Any]) -> str:
    """A deterministic non-Headroom baseline that keeps anomalies and edges."""
    rows = payload.get("rows")
    if isinstance(rows, list):
        interesting = []
        for row in rows:
            row_text = json.dumps(row, sort_keys=True)
            if any(
                marker in row_text.lower()
                for marker in ["empty", "stale", "blocked", "404", "missing", "duplicate", "route_changed"]
            ):
                interesting.append(row)
        sample = rows[:3] + interesting + rows[-3:]
        return json.dumps(
            {
                "workflow": payload["workflow"],
                "privacy_level": payload["privacy_level"],
                "must_preserve": payload["must_preserve"],
                "row_count": len(rows),
                "sample_and_anomalies": sample,
            },
            indent=2,
            sort_keys=True,
        )
    lines = payload.get("lines")
    if isinstance(lines, list):
        interesting_lines = [
            line for line in lines if any(marker in line for marker in ["ERROR", "WARNING", "failed", "secret"])
        ]
        return json.dumps(
            {
                "workflow": payload["workflow"],
                "privacy_level": payload["privacy_level"],
                "must_preserve": payload["must_preserve"],
                "line_count": len(lines),
                "sample_and_anomalies": lines[:5] + interesting_lines + lines[-5:],
            },
            indent=2,
            sort_keys=True,
        )
    return json.dumps(payload, indent=2, sort_keys=True)


def try_headroom(original_text: str) -> CompressionResult | None:
    try:
        from headroom import compress  # type: ignore
    except Exception:
        return None

    messages = [
        {"role": "system", "content": "Analyze sanitized agency operations output. Preserve anomalies."},
        {"role": "user", "content": "Compress this safe fixture for later QA."},
        {"role": "assistant", "content": original_text},
    ]
    started = time.perf_counter()
    result = compress(messages, model="gpt-4o")
    latency_ms = round((time.perf_counter() - started) * 1000)
    compressed_text = json.dumps(result.messages, indent=2, sort_keys=True, default=str)
    tokens_before = int(getattr(result, "tokens_before", estimate_tokens(original_text)))
    tokens_after = int(getattr(result, "tokens_after", estimate_tokens(compressed_text)))
    transforms = list(getattr(result, "transforms_applied", []))
    return CompressionResult(
        mode="headroom",
        text=compressed_text,
        tokens_before=tokens_before,
        tokens_after=tokens_after,
        tokens_saved=tokens_before - tokens_after,
        compression_ratio=(tokens_before - tokens_after) / tokens_before if tokens_before else 0.0,
        transforms=transforms,
        latency_ms=latency_ms,
    )


def evaluate_fixture(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    original_text = json.dumps(payload, indent=2, sort_keys=True)
    privacy_flag = has_secret_like_text(original_text)

    compression = try_headroom(original_text)
    if compression is None:
        started = time.perf_counter()
        baseline_text = compact_baseline(payload)
        latency_ms = round((time.perf_counter() - started) * 1000)
        before = estimate_tokens(original_text)
        after = estimate_tokens(baseline_text)
        compression = CompressionResult(
            mode="local_baseline_no_headroom_installed",
            text=baseline_text,
            tokens_before=before,
            tokens_after=after,
            tokens_saved=before - after,
            compression_ratio=(before - after) / before if before else 0.0,
            transforms=["sample_edges_and_anomalies"],
            latency_ms=latency_ms,
        )

    missing = [fact for fact in payload["must_preserve"] if fact not in compression.text]
    answer_match = "same" if not missing and not privacy_flag else "fail"
    return {
        "fixture": path.name,
        "workflow": payload["workflow"],
        "mode": compression.mode,
        "tokens_before": compression.tokens_before,
        "tokens_after": compression.tokens_after,
        "tokens_saved": compression.tokens_saved,
        "compression_ratio": round(compression.compression_ratio, 4),
        "compression_pct": round(compression.compression_ratio * 100, 1),
        "latency_ms": compression.latency_ms,
        "transforms": compression.transforms,
        "must_preserve_missing": missing,
        "privacy_flag": privacy_flag,
        "answer_match": answer_match,
        "adopt_signal": (
            compression.mode == "headroom"
            and compression.compression_ratio >= 0.5
            and not missing
            and not privacy_flag
        ),
    }


def write_markdown(results: list[dict[str, Any]]) -> None:
    headroom_runs = [row for row in results if row["mode"] == "headroom"]
    passing = [row for row in results if row["adopt_signal"]]
    lines = [
        "# Headroom Evaluation Results",
        "",
        f"Generated with `HEADROOM_TELEMETRY={os.environ.get('HEADROOM_TELEMETRY', '')}`.",
        "",
        "| Fixture | Mode | Before | After | Saved | Preserve | Privacy | Answer | Adopt Signal |",
        "| --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for row in results:
        preserve = "pass" if not row["must_preserve_missing"] else "missing: " + ", ".join(row["must_preserve_missing"])
        privacy = "flag" if row["privacy_flag"] else "pass"
        adopt = "yes" if row["adopt_signal"] else "no"
        lines.append(
            f"| {row['fixture']} | {row['mode']} | {row['tokens_before']} | {row['tokens_after']} | "
            f"{row['compression_pct']}% | {preserve} | {privacy} | {row['answer_match']} | {adopt} |"
        )
    lines.extend(
        [
            "",
            "## Decision",
            "",
            (
                "Real Headroom adoption threshold met."
                if len(passing) >= 3 and len(headroom_runs) == len(results)
                else "Do not adopt globally yet. Keep this as a fenced local experiment until real Headroom runs meet the threshold."
            ),
            "",
            "Threshold: 3 of 5 fixtures must use real Headroom, save at least 50%, preserve all required facts, and raise no privacy flags.",
        ]
    )
    (RESULTS / "evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    fixture_paths = sorted(FIXTURES.glob("*.json"))
    if not fixture_paths:
        raise SystemExit(f"No fixtures found in {FIXTURES}. Run make_safe_fixtures.py first.")
    results = [evaluate_fixture(path) for path in fixture_paths]
    (RESULTS / "evaluation.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_markdown(results)
    print(f"Evaluated {len(results)} fixtures. Wrote {RESULTS / 'evaluation.md'}")


if __name__ == "__main__":
    main()
