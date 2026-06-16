# Headroom Real-World Evaluation

This folder is a fenced-off pilot for testing whether `chopratejas/headroom`
is useful for Laurence's Codex and agency-memory workflows.

The pilot is local, read-only, and uses safe real-shaped fixtures. Do not run it
over `.env` files, service-account JSON, inbox exports, raw Drive docs, Monday
comments/updates, private notes, or credential vault contents.

## Decision Question

Can Headroom reduce bulky agent context by at least 50% while preserving the
facts needed for BigQuery health, SEO crawl, reporting, Monday metadata, and log
debugging decisions?

## Safety Rules

- Keep `HEADROOM_TELEMETRY=off` for all Headroom runs.
- Use sanitized fixtures first.
- Do not insert Headroom into `scripts/bq_capped_query.py` or live loaders.
- Do not use proxy mode as a default Codex layer until this evaluation passes.
- Treat any privacy issue as an automatic fail for that fixture.

## Files

- `scripts/make_safe_fixtures.py`: creates synthetic/sanitized real-shaped JSON
  fixtures for the five target workflows.
- `scripts/evaluate_headroom.py`: runs the fixtures through Headroom when
  available, otherwise records deterministic baseline stats and preservation
  checks.
- `fixtures/*.json`: safe input fixtures.
- `results/evaluation.json`: latest machine-readable run result.
- `results/evaluation.md`: latest human-readable scorecard.

## Run

From `/Users/laurencedeer/Projects/Codex/Big Query`:

```bash
.venv/bin/python experiments/headroom-eval/scripts/make_safe_fixtures.py
HEADROOM_TELEMETRY=off .venv/bin/python experiments/headroom-eval/scripts/evaluate_headroom.py
```

Optional real Headroom run:

```bash
python3 -m venv experiments/headroom-eval/.venv-headroom
. experiments/headroom-eval/.venv-headroom/bin/activate
pip install "headroom-ai[all]"
HEADROOM_TELEMETRY=off python experiments/headroom-eval/scripts/evaluate_headroom.py
```

## Pass Threshold

Adopt lightly only if:

- at least 3 of 5 fixtures save 50%+ tokens with real Headroom,
- all must-preserve facts are present after compression,
- answer checks are `same` or `near_same`,
- no privacy flags are triggered,
- latency is acceptable for day-to-day Codex work.

Until then, keep Headroom as an experiment only.
