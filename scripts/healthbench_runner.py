#!/usr/bin/env python3
"""Run Claude Opus 4.7 against the HealthBench Hard subset, grade, write JSON.

This is the T4.6 baseline runner for Prism's clinical rail. It calls
Claude Opus 4.7 directly via the Messages API — NOT Managed Agents —
because the baseline measures the bare model, not the harness. The
grader is the HealthBench rubric shipped with openai/simple-evals.

Default behavior is --dry-run: loads the manifest, prints the planned
API call count, planned seed, planned output path, and writes a
skeletal JSON marked dry_run:true. No network, no SDK import.

Real execution requires BOTH:
  1) --commit on the command line, AND
  2) PRISM_HEALTHBENCH_COMMIT=1 in the environment.

Missing either one prints a refusal and exits 1. The Anthropic SDK is
only imported inside do_commit(); dry-run never touches it.
scripts/check_sdk_containment.py enforces this with AST.

Grading uses `scripts/_healthbench_grader_bridge.py`, which holds
copies of openai/simple-evals' `RubricItem`, `calculate_score`, and
`GRADER_TEMPLATE` (MIT, 2024 OpenAI) pinned against
third_party/simple-evals/ at a specific SHA. The bridge hard-fails if
the upstream clone drifts off the pin. See NOTICE and
third_party/README.md §4.

Per-example grading requires a judge LLM to score each rubric item.
Three judge paths are supported:

  dry-run (--commit absent)
      Never grades. Skeletal JSON emitted. No SDK, no spend.

  heuristic judge (--heuristic-judge)
      Keyword-match stub. Produces MEANINGLESS numbers — development
      only. Gate-guarded by an explicit CLI flag and a loud WARN so
      these numbers never leak into a baseline or a published delta.

  Opus 4.7 judge (default when --commit)
      Real API call per rubric item using openai/simple-evals'
      GRADER_TEMPLATE verbatim. Built by _make_anthropic_judge. Safety
      contract (T4.6c, reviewed with trauma-CTO posture):
        - Pre-flight tiny call before any real work. Halts LOUD on
          401/403 rather than silently producing reward=0 everywhere.
        - Exponential-backoff retry on 429/5xx up to max_retries=3.
        - Immediate halt on auth errors (JudgeAuthError).
        - On exhausted retries, the rubric item records
          criteria_met=None; _real_grader then RECUSES the item (score
          denominator shrinks) rather than fabricating a pass/fail.
        - Every judge call streams to a JSONL audit log so a physician
          can re-review any single verdict.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

import yaml

REPO = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO / "results"

# Import the bridge via file path so this module stays runnable whether
# `scripts/` is on sys.path or not.
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from _healthbench_grader_bridge import (  # noqa: E402
    GRADER_TEMPLATE,
    RubricItem,
    assert_upstream_pinned,
    calculate_score,
)

HEALTHBENCH_AXES = (
    "accuracy",
    "completeness",
    "context_awareness",
    "instruction_following",
    # Upstream HealthBench tags this axis as `axis:communication_quality`
    # (not `axis:communication`). The name mismatch silently produced
    # axis=0.0 for this axis on every HealthBench run until 2026-04-23;
    # the T4.7b Stage 3 ship-gate exposed it when clinical-review came
    # back unmeasurable. Keep the full upstream name so `_canonical_axis`
    # matches `axis:communication_quality` correctly.
    "communication_quality",
)

MODEL_ID = "claude-opus-4-7"
MANAGED_AGENTS_BETA = "managed-agents-2026-04-01"  # unused here; baseline is direct API


def _stub_grader(response_text: str, example: dict) -> dict:
    """Zero-score fallback — only used in dry-run to skip grader work.

    Dry-run does NOT call a judge model; this stub lets the run still
    emit a shaped payload. Commit always calls `_real_grader`.
    """
    return {
        "score": 0.0,
        "per_axis": {a: 0.0 for a in HEALTHBENCH_AXES},
        "stub": True,
    }


def _heuristic_judge(conversation: str, rubric_item: RubricItem) -> dict:
    """Deterministic keyword-match judge for grader-path smoke tests.

    Used only when the caller does not inject a real judge. Marks a
    criterion 'met' if any low-case significant token from the criterion
    text (len>=5, alpha) appears in the conversation. NOT a real
    HealthBench grader; real use requires an LLM judge per
    GRADER_TEMPLATE. This exists so the grader pipeline is exercised
    in CI without external API calls.
    """
    lc = conversation.lower()
    tokens = [
        t
        for t in rubric_item.criterion.lower().replace(",", " ").split()
        if len(t) >= 5 and t.isalpha()
    ]
    met = any(t in lc for t in tokens)
    return {
        "criteria_met": met,
        "explanation": (
            "heuristic-judge: keyword-match over criterion text "
            f"(hit={met}, token_count={len(tokens)})"
        ),
    }


class JudgeAuthError(RuntimeError):
    """Raised when the judge API returns 401/403.

    Halts the run immediately. Per the operational rule: a 401 judge
    silently produces reward=0 across every rubric item; resume cannot
    detect the poisoning. The Level-1-trauma-CTO posture: fail loud
    rather than publish fabricated zeros.
    """


class JudgeExhaustedError(RuntimeError):
    """Raised if a per-call exhausted-retry condition should halt the run.

    The default behavior of _make_anthropic_judge is NOT to raise this;
    it records criteria_met=None and lets _real_grader recuse the item.
    Kept as a named type so a caller can swap in a strict fail-fast
    judge factory variant if policy changes.
    """


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_BARE_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_judge_json(raw: str) -> dict:
    """Parse {criteria_met, explanation} from a judge's text output.

    GRADER_TEMPLATE asks for a JSON object in markdown form. Accepts:
      - ```json {...} ``` fenced blocks
      - ``` {...} ``` untagged fences
      - bare {...} with no fence
    Raises ValueError on missing `criteria_met` or invalid JSON so the
    retry loop can catch it and decide whether to retry or recuse.
    """
    if not raw:
        raise ValueError("empty judge response")
    candidate = None
    m = _JSON_FENCE_RE.search(raw)
    if m:
        candidate = m.group(1)
    else:
        m = _JSON_BARE_RE.search(raw)
        if m:
            candidate = m.group(0)
    if candidate is None:
        raise ValueError("no JSON object in judge response")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge JSON invalid: {exc}") from exc
    if not isinstance(obj, dict):
        raise ValueError("judge response not a JSON object")
    if "criteria_met" not in obj:
        raise ValueError("judge response missing 'criteria_met'")
    return {
        "criteria_met": bool(obj["criteria_met"]),
        "explanation": str(obj.get("explanation", "")),
    }


def _status_code_of(exc: BaseException) -> int | None:
    """Best-effort extraction of HTTP status from an SDK exception.

    Checks the common attribute (status_code), the underlying response,
    and a `.response.status_code` pattern. SDK-agnostic so this module
    can stay free of any `from anthropic import ...` at module scope.
    """
    sc = getattr(exc, "status_code", None)
    if isinstance(sc, int):
        return sc
    response = getattr(exc, "response", None)
    if response is not None:
        sc = getattr(response, "status_code", None)
        if isinstance(sc, int):
            return sc
    return None


def _make_anthropic_judge(
    client: Any,
    model_id: str = None,
    audit_log_path: Path | None = None,
    max_retries: int = 3,
    max_output_tokens: int = 512,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Callable[[str, RubricItem], dict]:
    """Return a judge_fn backed by an Anthropic Messages client.

    The SDK import does NOT happen here; `client` is injected by the
    caller (do_commit) so scripts/check_sdk_containment.py remains green.

    Retry policy (per rubric item):
      - 429 / 5xx            : exponential backoff, up to max_retries
      - 401 / 403            : raise JudgeAuthError — halt the run
      - JSON parse failure   : retry up to max_retries with fresh call
      - exhausted retries    : return criteria_met=None, exhausted=True
                               (_real_grader recuses the item)

    Every call — successful or not — appends one JSONL record to
    `audit_log_path` (if provided). The record includes the prompt
    length, the raw response (truncated to 2000 chars), the parsed
    verdict, duration, attempt count, and any error. A physician can
    tail this file to re-review any single judgment.
    """
    # Fall-through for the model_id default so a caller that passes
    # None keeps the canonical MODEL_ID without introducing a cross-ref
    # at import time. (Function defaults are evaluated at def time; we
    # want MODEL_ID resolved at call time.)
    if model_id is None:
        model_id = MODEL_ID

    def _append_audit(record: dict) -> None:
        if audit_log_path is None:
            return
        audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with audit_log_path.open("a") as f:
            f.write(json.dumps(record, sort_keys=True, default=str) + "\n")

    def _judge(conversation: str, item: RubricItem) -> dict:
        prompt = (
            GRADER_TEMPLATE
            .replace("<<conversation>>", conversation)
            .replace("<<rubric_item>>", str(item))
        )
        messages = [{"role": "user", "content": prompt}]
        last_error: str | None = None
        raw_text = ""

        for attempt in range(max_retries):
            started = time.time()
            try:
                response = client.messages.create(
                    model=model_id,
                    max_tokens=max_output_tokens,
                    messages=messages,
                )
            except Exception as exc:  # noqa: BLE001 — intentional wide catch
                status = _status_code_of(exc)
                if status in (401, 403):
                    _append_audit(
                        {
                            "ts": _now_iso(),
                            "criterion": item.criterion[:200],
                            "tags": list(item.tags),
                            "attempt": attempt,
                            "error": f"auth-halt: {status}: {exc}",
                            "duration_ms": int((time.time() - started) * 1000),
                        }
                    )
                    raise JudgeAuthError(
                        f"judge auth failed ({status}); halting. A bad key "
                        "silently produces reward=0 across every rubric "
                        "item. Fix ANTHROPIC_API_KEY and rerun."
                    ) from exc
                is_retriable = status == 429 or (
                    status is not None and 500 <= status < 600
                )
                if is_retriable and attempt + 1 < max_retries:
                    last_error = f"http-{status}: {exc}"
                    sleep_fn(2 ** attempt)
                    continue
                # Non-retriable, or retries exhausted on transport
                last_error = f"{status or 'transport'}: {exc}"
                _append_audit(
                    {
                        "ts": _now_iso(),
                        "criterion": item.criterion[:200],
                        "tags": list(item.tags),
                        "attempt": attempt,
                        "error": last_error,
                        "duration_ms": int((time.time() - started) * 1000),
                    }
                )
                break

            raw_text = ""
            for block in getattr(response, "content", []) or []:
                if getattr(block, "type", None) == "text":
                    raw_text += getattr(block, "text", "") or ""
            duration_ms = int((time.time() - started) * 1000)

            try:
                parsed = _parse_judge_json(raw_text)
            except ValueError as exc:
                last_error = f"parse: {exc}"
                _append_audit(
                    {
                        "ts": _now_iso(),
                        "criterion": item.criterion[:200],
                        "tags": list(item.tags),
                        "attempt": attempt,
                        "raw": raw_text[:2000],
                        "error": last_error,
                        "duration_ms": duration_ms,
                    }
                )
                if attempt + 1 < max_retries:
                    sleep_fn(2 ** attempt)
                    continue
                break

            _append_audit(
                {
                    "ts": _now_iso(),
                    "criterion": item.criterion[:200],
                    "tags": list(item.tags),
                    "attempt": attempt,
                    "raw": raw_text[:2000],
                    "parsed": parsed,
                    "duration_ms": duration_ms,
                }
            )
            return {
                "criteria_met": parsed["criteria_met"],
                "explanation": parsed["explanation"],
                "attempt_count": attempt + 1,
                "duration_ms": duration_ms,
            }

        # Retries exhausted — recuse this item so we do not fabricate a verdict.
        return {
            "criteria_met": None,
            "explanation": f"judge-failed: {last_error or 'unknown'}",
            "exhausted": True,
        }

    return _judge


def _preflight_judge_key(client: Any, model_id: str) -> None:
    """Tiny Messages call so a bad key halts LOUD before any real spend.

    Hard rule (from session memory): ALWAYS pre-flight judge API keys
    before multi-hour evals — a 401 silently poisons all trajectories
    with reward=0 and resume cannot detect it.
    """
    try:
        client.messages.create(
            model=model_id,
            max_tokens=5,
            messages=[{"role": "user", "content": "ok"}],
        )
    except Exception as exc:  # noqa: BLE001 — intentional wide catch
        status = _status_code_of(exc)
        if status in (401, 403):
            raise JudgeAuthError(
                f"preflight: judge key auth failed ({status}). Fix "
                "ANTHROPIC_API_KEY before spending on T4.6c/T4.6d."
            ) from exc
        raise


def _per_axis_scores(
    rubric_items: list[RubricItem], grading_responses: list[dict]
) -> dict[str, float]:
    """Compute per-axis scores by grouping rubric items on tag.

    Each rubric item's `tags` field names the axis (or axes) it scores
    against. We compute a separate `calculate_score` per axis, using
    only the items carrying that tag. Axes with no items get 0.0 (not
    None) so downstream aggregation sees a scalar.

    Tag normalization (2026-04-23): HealthBench Hard rubric items use
    the canonical prefixed form `axis:accuracy`, `axis:completeness`,
    etc. Earlier bare-name form `accuracy` is also accepted for
    compatibility with hand-authored fixtures. Before this fix the
    lookup matched only the bare form, so every HealthBench Hard run
    silently produced per_axis={axis: 0.0 for all axes} while the
    overall score was correctly non-zero — the Stage 2 T4.7b pilot
    caught this.
    """
    def _canonical_axis(tag: str) -> str | None:
        if tag.startswith("axis:"):
            return tag[len("axis:"):]
        if tag in HEALTHBENCH_AXES:
            return tag
        return None

    by_axis: dict[str, list[tuple[RubricItem, dict]]] = defaultdict(list)
    for item, resp in zip(rubric_items, grading_responses, strict=True):
        for tag in item.tags:
            axis = _canonical_axis(tag)
            if axis is not None:
                by_axis[axis].append((item, resp))
    out: dict[str, float] = {}
    for axis in HEALTHBENCH_AXES:
        pairs = by_axis.get(axis, [])
        if not pairs:
            out[axis] = 0.0
            continue
        axis_items = [p[0] for p in pairs]
        axis_resps = [p[1] for p in pairs]
        score = calculate_score(axis_items, axis_resps)
        out[axis] = float(score) if score is not None else 0.0
    return out


def _real_grader(
    response_text: str,
    example: dict,
    judge_fn: Callable[[str, RubricItem], dict] = _heuristic_judge,
) -> dict:
    """Grade one response against its rubric via simple-evals arithmetic.

    Expects `example["rubrics"]` in HealthBench format:
        [{"criterion": "...", "points": X, "tags": [...]}, ...]

    For each rubric item, `judge_fn(conversation, item)` returns
        {"criteria_met": bool, "explanation": str}

    The overall score is `calculate_score` (positive-point-weighted);
    per-axis scores are computed by tag grouping.
    """
    assert_upstream_pinned()

    raw_rubrics = example.get("rubrics") or []
    rubric_items = [RubricItem.from_dict(r) for r in raw_rubrics]

    # Conversation wire format expected by GRADER_TEMPLATE: the last
    # assistant message is the completion being graded. We render a
    # minimal two-turn transcript (user prompt + assistant completion)
    # because simple-evals scores the LAST turn.
    prompt_text = ""
    msgs = example.get("messages") or [
        {"role": "user", "content": example.get("prompt", "")}
    ]
    for m in msgs:
        prompt_text += f"{m.get('role', 'user')}: {m.get('content', '')}\n"
    conversation = prompt_text + f"assistant: {response_text}"

    # Empty rubric is a legitimate pass-through: no items, no score to
    # fabricate, no judge failures. Return a 0.0 scalar to stay
    # compatible with downstream numeric pipelines.
    if not rubric_items:
        return {
            "score": 0.0,
            "per_axis": {a: 0.0 for a in HEALTHBENCH_AXES},
            "stub": False,
            "grading_responses": [],
            "rubric_items": [],
            "grader": "simple-evals@ee3b0318 via bridge",
            "judge_incomplete": 0,
            "judge_incomplete_fraction": 0.0,
        }

    grading_responses: list[dict] = []
    for item in rubric_items:
        grading_responses.append(judge_fn(conversation, item))

    # Recuse judge-failed items (criteria_met is None). Refuse to
    # fabricate a pass/fail when the judge could not produce one —
    # calculate_score runs over ONLY the successfully judged subset.
    paired = list(zip(rubric_items, grading_responses, strict=True))
    ok_pairs = [
        (it, resp) for (it, resp) in paired if resp.get("criteria_met") is not None
    ]
    n_total = len(paired)
    n_incomplete = n_total - len(ok_pairs)

    if not ok_pairs:
        # Non-empty rubric but every item recused — refuse to emit a
        # score. Delta-report consumers must handle None explicitly.
        return {
            "score": None,
            "per_axis": {a: None for a in HEALTHBENCH_AXES},
            "stub": False,
            "grading_responses": grading_responses,
            "rubric_items": [r.to_dict() for r in rubric_items],
            "grader": "simple-evals@ee3b0318 via bridge",
            "judge_incomplete": n_incomplete,
            "judge_incomplete_fraction": 1.0,
        }

    ok_items = [p[0] for p in ok_pairs]
    ok_resps = [p[1] for p in ok_pairs]
    overall = calculate_score(ok_items, ok_resps)
    per_axis = _per_axis_scores(ok_items, ok_resps)

    return {
        "score": float(overall) if overall is not None else 0.0,
        "per_axis": per_axis,
        "stub": False,
        "grading_responses": grading_responses,
        "rubric_items": [r.to_dict() for r in rubric_items],
        "grader": "simple-evals@ee3b0318 via bridge",
        "judge_incomplete": n_incomplete,
        "judge_incomplete_fraction": n_incomplete / n_total if n_total else 0.0,
    }


def _load_manifest(path: Path) -> dict:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: manifest must be a YAML mapping at top level")
    if "examples" not in data or not isinstance(data["examples"], list):
        raise ValueError(f"{path}: manifest missing required key 'examples' (list)")
    return data


def _aggregate(per_example: list[dict]) -> dict:
    """Aggregate per-example scores, skipping RECUSED examples (score=None).

    n_scored counts examples that produced a real score; n_recused counts
    examples where every rubric item was judge-failed. The mean is over
    n_scored only — we refuse to weight a recused example as 0.
    """
    if not per_example:
        return {
            "score": 0.0,
            "per_axis": {a: 0.0 for a in HEALTHBENCH_AXES},
            "n": 0,
            "n_scored": 0,
            "n_recused": 0,
        }
    scored = [e for e in per_example if e.get("score") is not None]
    n = len(per_example)
    n_scored = len(scored)
    n_recused = n - n_scored
    if n_scored == 0:
        return {
            "score": None,
            "per_axis": {a: None for a in HEALTHBENCH_AXES},
            "n": n,
            "n_scored": 0,
            "n_recused": n_recused,
        }
    score_mean = sum(e.get("score", 0.0) for e in scored) / n_scored
    per_axis_mean: dict[str, float] = {}
    for axis in HEALTHBENCH_AXES:
        vals = [
            e.get("per_axis", {}).get(axis)
            for e in scored
            if e.get("per_axis", {}).get(axis) is not None
        ]
        per_axis_mean[axis] = (sum(vals) / len(vals)) if vals else 0.0
    return {
        "score": score_mean,
        "per_axis": per_axis_mean,
        "n": n,
        "n_scored": n_scored,
        "n_recused": n_recused,
    }


def _write_out(out_path: Path, payload: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=str)
        f.write("\n")


def _now_iso() -> str:
    return (
        _dt.datetime.now(_dt.timezone.utc)
        .replace(tzinfo=None)
        .isoformat(timespec="seconds")
        + "Z"
    )


def do_dry_run(args: argparse.Namespace, run_id: str) -> int:
    """Load manifest, print plan, write skeletal dry-run JSON."""
    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()

    try:
        manifest = _load_manifest(manifest_path)
    except (FileNotFoundError, ValueError) as exc:
        # Dry-run tolerates a missing/empty manifest so the gate-check
        # refusal tests can run against /dev/null. Emit a placeholder.
        print(f"(dry-run) manifest not usable ({exc}); writing placeholder plan")
        manifest = {"examples": []}

    planned_calls = len(manifest.get("examples", []))
    print("(dry-run) healthbench_runner.py plan:")
    print(f"  manifest         : {manifest_path}")
    print(f"  out              : {out_path}")
    print(f"  seed             : {args.seed}")
    print(f"  run_id           : {run_id}")
    print(f"  budget_cap_usd   : {args.budget_cap_usd}")
    print(f"  planned api calls: {planned_calls}")
    print(f"  model            : {MODEL_ID}")
    print(f"  grader           : simple-evals@ee3b0318 (bridge; heuristic judge default)")
    print("(dry-run) no network activity; no anthropic SDK import")

    payload = {
        "dry_run": True,
        "run_id": run_id,
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "seed": args.seed,
        "model": MODEL_ID,
        "budget_cap_usd": args.budget_cap_usd,
        "planned_api_calls": planned_calls,
        "per_example": [],
        "aggregate": _aggregate([]),
    }
    _write_out(out_path, payload)
    print(f"(dry-run) wrote skeletal results to: {out_path}")
    return 0


def do_commit(args: argparse.Namespace, run_id: str) -> int:
    """Live Messages API sweep. Reached only when both gates pass."""
    # The Anthropic client is only constructed in this function. It is
    # never imported or instantiated at module scope and never touched
    # from dry-run. scripts/check_sdk_containment.py enforces this.
    from anthropic import Anthropic  # noqa: PLC0415  intentional lazy import

    manifest_path = Path(args.manifest).resolve()
    out_path = Path(args.out).resolve()
    manifest = _load_manifest(manifest_path)
    examples: list[dict] = manifest.get("examples", [])

    client = Anthropic()
    print(f"(commit) run_id={run_id} model={MODEL_ID} seed={args.seed}")
    print(f"(commit) examples={len(examples)} budget_cap=${args.budget_cap_usd}")

    # Pre-flight: halt LOUD on a bad key before any real spend.
    _preflight_judge_key(client, args.judge_model)
    print(f"(commit) preflight: judge key OK (model={args.judge_model})")

    # Build the per-example judge. --heuristic-judge is a testing
    # escape hatch; the banner below is deliberately alarming so heuristic
    # numbers cannot leak into the baseline without the reviewer noticing.
    if args.heuristic_judge:
        print(
            "(commit) WARN: --heuristic-judge is dev-only; these numbers "
            "are MEANINGLESS and MUST NOT be cited as a baseline."
        )
        judge_fn: Callable[[str, RubricItem], dict] = _heuristic_judge
    else:
        audit_path: Path | None = None
        if args.judge_audit_log:
            audit_path = Path(args.judge_audit_log).resolve()
            # Fresh run = fresh audit log, so per-run grep is clean.
            if audit_path.exists():
                audit_path.unlink()
        else:
            audit_path = RESULTS_DIR / f"judge-log-{run_id}.jsonl"
        judge_fn = _make_anthropic_judge(
            client,
            model_id=args.judge_model,
            audit_log_path=audit_path,
        )
        print(f"(commit) judge: {args.judge_model}; audit_log: {audit_path}")

    per_example: list[dict] = []
    total_cost_usd = 0.0
    halted_reason: str | None = None

    for idx, example in enumerate(examples):
        if total_cost_usd >= args.budget_cap_usd:
            halted_reason = (
                f"budget cap hit at example {idx} "
                f"(spent=${total_cost_usd:.2f} >= cap=${args.budget_cap_usd:.2f})"
            )
            print(f"(commit) HALT: {halted_reason}")
            break

        prompt_messages = example.get("messages") or [
            {"role": "user", "content": example.get("prompt", "")}
        ]
        # Opus 4.7 does not expose a seed parameter on messages.create
        # (CLAUDE.md §8). args.seed is recorded in the run payload for
        # provenance and used to distinguish two independent runs; model
        # sampler variance supplies the independence that backs the
        # seed-stability gate.
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=example.get("max_tokens", 2048),
            messages=prompt_messages,
        )
        response_text = ""
        for block in getattr(response, "content", []) or []:
            if getattr(block, "type", None) == "text":
                response_text += getattr(block, "text", "")

        # Grade against the rubric using the configured judge. Any
        # judge-failed items are recused by _real_grader; the
        # grading_responses list + judge_incomplete fields are retained.
        grade = _real_grader(response_text, example, judge_fn=judge_fn)
        usage = getattr(response, "usage", None)
        in_toks = getattr(usage, "input_tokens", 0) if usage else 0
        out_toks = getattr(usage, "output_tokens", 0) if usage else 0
        # Rough Opus 4.7 pricing placeholder: $15/Mtok in, $75/Mtok out.
        cost = (in_toks / 1_000_000) * 15.0 + (out_toks / 1_000_000) * 75.0
        total_cost_usd += cost

        per_example.append(
            {
                "id": example.get("id", f"ex-{idx}"),
                "score": grade["score"],
                "per_axis": grade["per_axis"],
                "stub_grader": grade.get("stub", False),
                "judge_incomplete": grade.get("judge_incomplete", 0),
                "judge_incomplete_fraction": grade.get(
                    "judge_incomplete_fraction", 0.0
                ),
                "input_tokens": in_toks,
                "output_tokens": out_toks,
                "est_cost_usd": round(cost, 6),
                "response_text": response_text,
            }
        )
        score_str = (
            f"{grade['score']:.3f}" if grade["score"] is not None else "RECUSED"
        )
        print(
            f"(commit) [{idx + 1}/{len(examples)}] id={example.get('id', '?')} "
            f"score={score_str} incomplete={grade.get('judge_incomplete', 0)} "
            f"cost=${cost:.4f} cum=${total_cost_usd:.2f}"
        )

    payload = {
        "dry_run": False,
        "run_id": run_id,
        "generated_at": _now_iso(),
        "manifest_path": str(manifest_path),
        "seed": args.seed,
        "model": MODEL_ID,
        "judge_model": args.judge_model,
        "judge_heuristic": args.heuristic_judge,
        "budget_cap_usd": args.budget_cap_usd,
        "total_cost_usd": round(total_cost_usd, 4),
        "halted_reason": halted_reason,
        "per_example": per_example,
        "aggregate": _aggregate(per_example),
    }
    _write_out(out_path, payload)
    print(f"(commit) wrote results to: {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--manifest",
        required=True,
        help="Path to corpus/clinical_subset.yaml (read-only).",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Path to write results JSON (e.g. results/baseline-opus47-NAME.json).",
    )
    ap.add_argument("--seed", type=int, default=42, help="Seed for Messages API calls.")
    ap.add_argument(
        "--commit",
        action="store_true",
        help="Run for real. Requires PRISM_HEALTHBENCH_COMMIT=1 in env.",
    )
    ap.add_argument(
        "--run-id",
        default=None,
        help="Optional UUID for this run; generated if absent.",
    )
    ap.add_argument(
        "--budget-cap-usd",
        type=float,
        default=25.0,
        help="Hard-stop if cumulative cost exceeds this (default 25.0).",
    )
    ap.add_argument(
        "--judge-model",
        default=MODEL_ID,
        help=f"Model for per-rubric-item judgment (default {MODEL_ID}).",
    )
    ap.add_argument(
        "--judge-audit-log",
        default=None,
        help=(
            "Optional path for per-call judge audit JSONL. Defaults to "
            "results/judge-log-<run_id>.jsonl under --commit."
        ),
    )
    ap.add_argument(
        "--heuristic-judge",
        action="store_true",
        help=(
            "DEV ONLY. Swap the LLM judge for the keyword heuristic. "
            "Numbers produced this way MUST NOT be cited as a baseline."
        ),
    )
    args = ap.parse_args()

    run_id = args.run_id or str(uuid.uuid4())

    if args.commit and os.environ.get("PRISM_HEALTHBENCH_COMMIT") != "1":
        print(
            "error: refusing — set BOTH --commit and PRISM_HEALTHBENCH_COMMIT=1",
            file=sys.stderr,
        )
        return 1

    if args.commit:
        return do_commit(args, run_id)

    return do_dry_run(args, run_id)


if __name__ == "__main__":
    sys.exit(main())
