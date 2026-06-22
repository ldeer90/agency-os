#!/usr/bin/env python3
"""Create a compact AgencyOS Codex/Langfuse token usage report."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / ".codex" / "langfuse.json"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports" / "langfuse"
DEFAULT_TAGS = ("agency-os", "codex-app")
AGENT_RE = re.compile(r"\bagent=([a-zA-Z0-9_-]+)")
TASK_RE = re.compile(r"\btask=([a-zA-Z0-9_-]+)")


@dataclass(frozen=True)
class LangfuseConfig:
    public_key: str
    secret_key: str
    base_url: str
    tags: tuple[str, ...]


@dataclass(frozen=True)
class UsageRecord:
    trace_id: str
    trace_name: str
    agent: str
    task: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float
    observation_count: int
    url: str | None = None
    codex_turn_id: str | None = None


@dataclass(frozen=True)
class DuplicateTraceGroup:
    trace_ids: tuple[str, ...]
    tokens_per_trace: int
    cost_per_trace: float
    duplicate_tokens: int
    duplicate_cost: float
    reason: str


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> LangfuseConfig:
    config = _read_json(path)
    public_key = (
        os.environ.get("LANGFUSE_CODEX_PUBLIC_KEY")
        or os.environ.get("LANGFUSE_PUBLIC_KEY")
        or config.get("public_key")
    )
    secret_key = (
        os.environ.get("LANGFUSE_CODEX_SECRET_KEY")
        or os.environ.get("LANGFUSE_SECRET_KEY")
        or config.get("secret_key")
    )
    base_url = (
        os.environ.get("LANGFUSE_CODEX_BASE_URL")
        or os.environ.get("LANGFUSE_BASE_URL")
        or os.environ.get("LANGFUSE_HOST")
        or config.get("base_url")
    )
    if not public_key or not secret_key or not base_url:
        raise SystemExit("Missing Langfuse config. Provide .codex/langfuse.json or LANGFUSE_* env vars.")
    tags = tuple(str(tag) for tag in config.get("tags") or DEFAULT_TAGS)
    return LangfuseConfig(
        public_key=str(public_key),
        secret_key=str(secret_key),
        base_url=str(base_url).rstrip("/"),
        tags=tags,
    )


def _auth_header(config: LangfuseConfig) -> dict[str, str]:
    token = base64.b64encode(f"{config.public_key}:{config.secret_key}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_first_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_first_text(v) for v in value[:5])
    return ""


def _usage_from_row(row: dict[str, Any]) -> tuple[int, int, int, float]:
    usage = row.get("usage") or row.get("usageDetails") or row.get("usage_details") or {}
    metrics = row.get("metrics") or {}
    input_tokens = _int(
        usage.get("input")
        or usage.get("inputUsage")
        or usage.get("promptTokens")
        or usage.get("prompt_tokens")
        or row.get("inputUsage")
    )
    output_tokens = _int(
        usage.get("output")
        or usage.get("outputUsage")
        or usage.get("completionTokens")
        or usage.get("completion_tokens")
        or row.get("outputUsage")
    )
    total_tokens = _int(usage.get("total") or usage.get("totalUsage") or row.get("totalUsage"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    cost = _float(metrics.get("totalCost") or row.get("totalCost") or row.get("cost"))
    return input_tokens, output_tokens, total_tokens, cost


def _trace_context(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("trace") or row.get("traceContext") or row.get("trace_context") or {}


def _tags(row: dict[str, Any]) -> list[str]:
    context = _trace_context(row)
    tags = row.get("tags") or context.get("tags") or []
    return [str(tag) for tag in tags if tag]


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    context = _trace_context(row)
    trace_metadata = context.get("metadata") or {}
    if isinstance(metadata, dict) and isinstance(trace_metadata, dict):
        return {**trace_metadata, **metadata}
    return metadata if isinstance(metadata, dict) else {}


def classify_row(row: dict[str, Any], *, include_io: bool = False) -> tuple[str, str]:
    metadata = _metadata(row)
    text_parts = [str(row.get("name") or ""), str(_trace_context(row).get("name") or "")]
    if include_io:
        text_parts.extend([_first_text(row.get("input")), _first_text(row.get("output"))])
    text = " ".join(text_parts)
    tags = _tags(row)
    agent = str(metadata.get("agent_id") or metadata.get("agent") or "")
    task = str(metadata.get("task_type") or metadata.get("task") or "")
    if not agent:
        for tag in tags:
            if tag.startswith("agent:"):
                agent = tag.split(":", 1)[1]
                break
    if not task:
        for tag in tags:
            if tag.startswith("task:"):
                task = tag.split(":", 1)[1]
                break
    if not agent:
        match = AGENT_RE.search(text)
        agent = match.group(1) if match else "unknown"
    if not task:
        match = TASK_RE.search(text)
        task = match.group(1) if match else "unknown"
    return agent, task


def fetch_daily_metrics(
    config: LangfuseConfig,
    start: datetime,
    end: datetime,
    timeout: float,
) -> list[dict[str, Any]]:
    params: list[tuple[str, str | int]] = [
        ("fromTimestamp", _iso(start)),
        ("toTimestamp", _iso(end)),
        ("limit", 100),
    ]
    for tag in config.tags:
        params.append(("tags", tag))
    with httpx.Client(timeout=timeout, headers=_auth_header(config)) as client:
        response = client.get(f"{config.base_url}/api/public/metrics/daily", params=params)
        response.raise_for_status()
        return list((response.json()).get("data") or [])


def fetch_observations(
    config: LangfuseConfig,
    start: datetime,
    end: datetime,
    limit: int,
    timeout: float,
    *,
    include_io: bool = False,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    fields = "core,basic,trace_context,model,usage,metrics,metadata"
    if include_io:
        fields += ",io"
    with httpx.Client(timeout=timeout, headers=_auth_header(config)) as client:
        while len(rows) < limit:
            params: dict[str, Any] = {
                "fromTimestamp": _iso(start),
                "toTimestamp": _iso(end),
                "limit": min(100, limit - len(rows)),
                "fields": fields,
            }
            if cursor:
                params["cursor"] = cursor
            response = client.get(f"{config.base_url}/api/public/v2/observations", params=params)
            response.raise_for_status()
            payload = response.json()
            batch = payload.get("data") or []
            rows.extend(batch)
            meta = payload.get("meta") or {}
            cursor = meta.get("nextCursor") or meta.get("next_cursor")
            if not cursor or not batch:
                break
    return rows


def _trace_id(row: dict[str, Any]) -> str:
    context = _trace_context(row)
    return str(context.get("id") or row.get("traceId") or row.get("trace_id") or "unknown")


def _codex_turn_id(row: dict[str, Any]) -> str | None:
    metadata = _metadata(row)
    value = metadata.get("codex.turn_id") or metadata.get("codex_turn_id")
    return str(value) if value else None


def records_from_observations(
    rows: list[dict[str, Any]],
    base_url: str,
    *,
    include_io: bool = False,
) -> list[UsageRecord]:
    grouped: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"rows": [], "input": 0, "output": 0, "total": 0, "cost": 0.0}
    )
    for row in rows:
        trace_id = _trace_id(row)
        input_tokens, output_tokens, total_tokens, cost = _usage_from_row(row)
        bundle = grouped[trace_id]
        bundle["rows"].append(row)
        bundle["input"] += input_tokens
        bundle["output"] += output_tokens
        bundle["total"] += total_tokens
        bundle["cost"] += cost

    records: list[UsageRecord] = []
    for trace_id, bundle in grouped.items():
        trace_rows = bundle["rows"]
        first = trace_rows[0] if trace_rows else {}
        context = _trace_context(first)
        agent_votes: Counter[str] = Counter()
        task_votes: Counter[str] = Counter()
        models: Counter[str] = Counter()
        turn_ids: Counter[str] = Counter()
        for row in trace_rows:
            agent, task = classify_row(row, include_io=include_io)
            agent_votes[agent] += 1
            task_votes[task] += 1
            turn_id = _codex_turn_id(row)
            if turn_id:
                turn_ids[turn_id] += 1
            model = row.get("providedModelName") or row.get("model") or row.get("modelName") or "unknown"
            models[str(model)] += 1
        records.append(
            UsageRecord(
                trace_id=trace_id,
                trace_name=str(context.get("name") or first.get("name") or "Codex Turn"),
                agent=agent_votes.most_common(1)[0][0] if agent_votes else "unknown",
                task=task_votes.most_common(1)[0][0] if task_votes else "unknown",
                model=models.most_common(1)[0][0] if models else "unknown",
                input_tokens=bundle["input"],
                output_tokens=bundle["output"],
                total_tokens=bundle["total"],
                cost=bundle["cost"],
                observation_count=len(trace_rows),
                url=f"{base_url.rstrip('/')}/trace/{trace_id}",
                codex_turn_id=turn_ids.most_common(1)[0][0] if turn_ids else None,
            )
        )
    return sorted(records, key=lambda r: r.total_tokens, reverse=True)


def duplicate_trace_candidates(records: list[UsageRecord]) -> list[DuplicateTraceGroup]:
    turn_buckets: dict[str, list[UsageRecord]] = defaultdict(list)
    shape_buckets: dict[tuple[int, int, int, int], list[UsageRecord]] = defaultdict(list)
    records_without_turn_id: list[UsageRecord] = []

    for record in records:
        if record.codex_turn_id:
            turn_buckets[record.codex_turn_id].append(record)
        else:
            records_without_turn_id.append(record)

    groups: list[DuplicateTraceGroup] = []
    for turn_id, bucket in turn_buckets.items():
        if len(bucket) <= 1:
            continue
        unique_record = max(bucket, key=lambda record: (record.total_tokens, record.cost))
        groups.append(
            DuplicateTraceGroup(
                trace_ids=tuple(record.trace_id for record in bucket),
                tokens_per_trace=unique_record.total_tokens,
                cost_per_trace=unique_record.cost,
                duplicate_tokens=sum(record.total_tokens for record in bucket) - unique_record.total_tokens,
                duplicate_cost=sum(record.cost for record in bucket) - unique_record.cost,
                reason=f"same codex.turn_id `{turn_id}`",
            )
        )

    for record in records_without_turn_id:
        key = (
            record.observation_count,
            record.input_tokens,
            record.output_tokens,
            int(round(record.cost * 1_000_000)),
        )
        shape_buckets[key].append(record)

    for bucket in shape_buckets.values():
        if len(bucket) <= 1:
            continue
        unique_record = max(bucket, key=lambda record: (record.total_tokens, record.cost))
        groups.append(
            DuplicateTraceGroup(
                trace_ids=tuple(record.trace_id for record in bucket),
                tokens_per_trace=unique_record.total_tokens,
                cost_per_trace=unique_record.cost,
                duplicate_tokens=sum(record.total_tokens for record in bucket) - unique_record.total_tokens,
                duplicate_cost=sum(record.cost for record in bucket) - unique_record.cost,
                reason="same usage shape without codex.turn_id metadata",
            )
        )
    return sorted(groups, key=lambda group: group.duplicate_cost, reverse=True)


def summarize_daily(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {"traces": 0, "observations": 0, "cost": 0.0, "input": 0, "output": 0, "total": 0, "models": Counter()}
    for row in rows:
        summary["traces"] += _int(row.get("countTraces"))
        summary["observations"] += _int(row.get("countObservations"))
        summary["cost"] += _float(row.get("totalCost"))
        for usage in row.get("usage") or []:
            model = str(usage.get("model") or "unknown")
            input_tokens = _int(usage.get("inputUsage"))
            output_tokens = _int(usage.get("outputUsage"))
            total_tokens = _int(usage.get("totalUsage")) or input_tokens + output_tokens
            summary["input"] += input_tokens
            summary["output"] += output_tokens
            summary["total"] += total_tokens
            summary["models"][model] += total_tokens
    return summary


def input_share(record: UsageRecord) -> float:
    if not record.total_tokens:
        return 0.0
    return record.input_tokens / record.total_tokens


def efficiency_flags(record: UsageRecord) -> list[str]:
    flags: list[str] = []
    if record.agent == "unknown" or record.task == "unknown":
        flags.append("missing agent/task")
    if record.total_tokens >= 300_000:
        flags.append("review threshold")
    elif record.total_tokens >= 100_000:
        flags.append("deep threshold")
    if input_share(record) >= 0.85:
        flags.append("high input share")
    if record.observation_count >= 25:
        flags.append("many observations")
    if record.input_tokens >= 25_000 and record.output_tokens <= 2_000:
        flags.append("low output / high input")
    return flags


def recommended_actions(flag_counts: Counter[str], duplicate_groups: list[DuplicateTraceGroup]) -> list[str]:
    actions: list[str] = []
    if duplicate_groups:
        actions.append(
            "Duplicate traces detected: report gross and likely unique cost, then check whether Codex/Langfuse tracing is emitting the same turn twice."
        )
    if flag_counts.get("missing agent/task"):
        actions.append("Missing metadata: start substantive AgencyOS turns with `agent=<agent_id> task=<task_type>`.")
    if flag_counts.get("high input share") or flag_counts.get("low output / high input"):
        actions.append("Input-heavy sessions: narrow file reads and start a fresh handoff turn instead of continuing a large context.")
    if flag_counts.get("many observations"):
        actions.append("Many tool steps: batch read-only exploration and split implementation after repeated command/edit cycles.")
    if flag_counts.get("review threshold") or flag_counts.get("deep threshold"):
        actions.append("Review/deep thresholds: inspect the metadata-only report before repeating the same workflow.")
    if not actions:
        actions.append("No major advisory flags detected in fetched row-level observations.")
    return actions


def _counter_table(title: str, counter: Counter[str], unit: str = "tokens", limit: int = 10) -> list[str]:
    lines = [f"## {title}", "", "| Rank | Name | Total |", "| --- | --- | ---: |"]
    for index, (name, value) in enumerate(counter.most_common(limit), start=1):
        lines.append(f"| {index} | `{name}` | {value:,.0f} {unit} |")
    if not counter:
        lines.append("| - | No data yet | 0 |")
    lines.append("")
    return lines


def render_report(
    *,
    start: datetime,
    end: datetime,
    config: LangfuseConfig,
    daily_rows: list[dict[str, Any]],
    observation_records: list[UsageRecord],
    observation_error: str | None,
    include_io: bool,
) -> str:
    daily = summarize_daily(daily_rows)
    agent_tokens: Counter[str] = Counter()
    task_tokens: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    for record in observation_records:
        agent_tokens[record.agent] += record.total_tokens
        task_tokens[record.task] += record.total_tokens
        flag_counts.update(efficiency_flags(record))
    duplicates = duplicate_trace_candidates(observation_records)
    duplicate_cost = sum(group.duplicate_cost for group in duplicates)
    duplicate_tokens = sum(group.duplicate_tokens for group in duplicates)

    lines = [
        "# AgencyOS Langfuse Usage Report",
        "",
        f"Window: `{_iso(start)}` to `{_iso(end)}`",
        f"Base URL: `{config.base_url}`",
        f"Tags: `{', '.join(config.tags)}`",
        f"Row-level fields: `{'metadata+io' if include_io else 'metadata-only'}`",
        "",
        "## Snapshot",
        "",
        f"- Traces: {daily['traces']:,}",
        f"- Observations: {daily['observations']:,}",
        f"- Input tokens: {daily['input']:,}",
        f"- Output tokens: {daily['output']:,}",
        f"- Total tokens: {daily['total']:,}",
        f"- Estimated cost: ${daily['cost']:.4f} USD",
        f"- Duplicate candidate cost: ${duplicate_cost:.4f} USD across {duplicate_tokens:,} likely duplicated tokens",
        "",
    ]
    lines.extend(_counter_table("Models By Tokens", daily["models"]))
    lines.extend(_counter_table("Agents By Tokens", agent_tokens))
    lines.extend(_counter_table("Task Types By Tokens", task_tokens))
    lines.extend(_counter_table("Inefficiency Flags", flag_counts, unit="hits"))

    lines.extend(
        [
            "## Highest Token Sessions",
            "",
            "| Rank | Agent | Task | Tokens | Input | Output | Input Share | Observations | Flags |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for index, record in enumerate(observation_records[:10], start=1):
        flags = ", ".join(efficiency_flags(record)) or "-"
        lines.append(
            f"| {index} | `{record.agent}` | `{record.task}` | {record.total_tokens:,} | "
            f"{record.input_tokens:,} | {record.output_tokens:,} | {input_share(record):.1%} | "
            f"{record.observation_count:,} | {flags} |"
        )
    if not observation_records:
        lines.append("| - | No row-level data yet | - | 0 | 0 | 0 | 0.0% | 0 | - |")
    lines.append("")

    lines.extend(
        [
            "## Duplicate Trace Candidates",
            "",
            f"- Estimated duplicate cost: `${duplicate_cost:.4f}` USD",
            f"- Estimated duplicate tokens: `{duplicate_tokens:,}`",
            "",
        ]
    )
    if duplicates:
        for group in duplicates[:10]:
            lines.append(
                "- "
                + ", ".join(f"`{trace_id}`" for trace_id in group.trace_ids)
                + f" | {group.reason}; duplicate estimate: ${group.duplicate_cost:.4f} USD, {group.duplicate_tokens:,} tokens"
            )
    else:
        lines.append("- None detected in fetched row-level observations.")
    lines.append("")

    lines.extend(["## Recommended Next Actions", ""])
    for action in recommended_actions(flag_counts, duplicates):
        lines.append(f"- {action}")
    lines.append("")

    lines.extend(
        [
            "## Beginner Recommendations",
            "",
            "- Start each substantial prompt `agent=<agent_id> task=<task_type>` so reports group usage cleanly.",
            "- Keep default row-level fetches metadata-only; use `--include-io` only approved debugging.",
            "- If `high input share` appears often, narrow searches file reads before asking synthesis.",
            "- If `many observations` appears often, split large requests into plan, implementation, verification turns.",
            "- Treat review/deep threshold flags as soft review triggers, not hard token budgets.",
            "",
        ]
    )
    if observation_error:
        lines.extend(
            [
                "## Row-Level Data Note",
                "",
                "Daily totals loaded, but row-level observations unavailable.",
                f"Reason: `{observation_error}`",
                "",
            ]
        )
    return "\n".join(lines)

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create beginner-friendly AgencyOS Codex/Langfuse token usage report.")
    parser.add_argument("--days", type=int, default=7, help="Lookback window in days.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path ignored Langfuse JSON config.")
    parser.add_argument("--output", type=Path, help="Markdown output path.")
    parser.add_argument("--stdout", action="store_true", help="Print report to stdout.")
    parser.add_argument("--no-write", action="store_true", help="Do not write a report file.")
    parser.add_argument("--include-io", action="store_true", help="Fetch Langfuse input/output fields for approved debugging.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum row-level observations fetch.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    end = datetime.now(UTC)
    start = end - timedelta(days=args.days)

    daily_rows = fetch_daily_metrics(config, start, end, args.timeout)
    observation_error = None
    try:
        observation_rows = fetch_observations(
            config,
            start,
            end,
            args.limit,
            args.timeout,
            include_io=args.include_io,
        )
        records = records_from_observations(observation_rows, config.base_url, include_io=args.include_io)
    except httpx.HTTPError as exc:
        observation_error = f"{exc.__class__.__name__}: {exc}"
        records = []

    report = render_report(
        start=start,
        end=end,
        config=config,
        daily_rows=daily_rows,
        observation_records=records,
        observation_error=observation_error,
        include_io=args.include_io,
    )

    output = args.output
    if not args.no_write:
        if output is None:
            stamp = end.strftime("%Y-%m-%d")
            output = DEFAULT_REPORT_DIR / f"agencyos-langfuse-usage-{stamp}.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report + "\n", encoding="utf-8")

    if args.stdout:
        print(report)
    if not args.no_write and output:
        print(f"Wrote Langfuse usage report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
