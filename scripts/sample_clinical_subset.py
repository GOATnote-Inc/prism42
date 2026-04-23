#!/usr/bin/env python3
"""Stratified sampler: HealthBench Hard (1000) → corpus/clinical_subset.yaml (30).

T4.5b. Selects 30 examples from the frozen canonical HealthBench Hard
corpus, stratified by clinical specialty, deterministic under `--seed`.

Distribution (docs/clinical-extension-spec.md §5 T4.5):

    class         count
    ---------     -----
    emergency     10
    pediatrics     5
    obgyn          5
    psychiatry     5
    general        5
                  --
                  30

Classification is keyword-based — deterministic, auditable, reproducible.
Priority: pediatrics > obgyn > psychiatry > emergency > general. Priority
matters when strata overlap (a pediatric ED case classifies as
pediatrics, because the narrower specialty stratum carries more signal
than the acuity bucket).

Per-example fields written to clinical_subset.yaml mirror corpus/kernel_bugs.yaml:

    id                          : Prism-owned ID, HBH-CLN-NNN
    healthbench_hard_example_id : upstream prompt_id (UUID)
    class                       : one of {emergency, pediatrics, obgyn,
                                  psychiatry, general}
    target_axis                 : one of {accuracy, completeness,
                                  context_awareness, instruction_following,
                                  communication}. Derived from the highest
                                  point-weighted axis tag in the upstream
                                  rubric.
    expected_failure_mode       : short physician-reviewable one-liner.
                                  Generated from class + target_axis;
                                  flagged PENDING-REVIEW until a physician
                                  edits. The baseline run does not read
                                  this field.
    messages                    : upstream prompt list (role/content dicts);
                                  passed verbatim to Anthropic Messages.
    rubrics                     : upstream rubric list (criterion/points/
                                  tags); consumed by
                                  _healthbench_grader_bridge.RubricItem.

Usage:

    python scripts/sample_clinical_subset.py \\
        --source /Users/kiteboard/healthbench_frozen/healthbench_hard_canonical_1000.jsonl \\
        --out corpus/clinical_subset.yaml \\
        --seed 42

No live spend. No network. Pure compute.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent

DEFAULT_SOURCE = Path("/Users/kiteboard/healthbench_frozen/healthbench_hard_canonical_1000.jsonl")
DEFAULT_OUT = REPO / "corpus" / "clinical_subset.yaml"
DEFAULT_SEED = 42

STRATA_COUNTS: dict[str, int] = {
    "emergency": 10,
    "pediatrics": 5,
    "obgyn": 5,
    "psychiatry": 5,
    "general": 5,
}
TOTAL_EXPECTED = sum(STRATA_COUNTS.values())  # 30

# Keyword sets. Matching is case-insensitive substring on the concatenated
# user-role content. Order of the class list below encodes priority:
# earlier = higher priority. `general` has no keywords — it's the default
# bucket for examples that don't match any specialty.
CLASS_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "pediatrics",
        (
            "pediatric", "paediatric",
            "neonat", "newborn", "infant", "baby",
            "toddler", "child ", "children", "childhood",
            "adolescent", "teenager", "teen ",
            "month-old", "months old", "weeks old", "week-old",
            "day-old", "days old",
            # Age-prefixed phrasing ("6 year old", "3-year-old") is caught
            # specially by _age_prefix_match below.
        ),
    ),
    (
        "obgyn",
        (
            "pregnan", "prenatal", "antenatal", "postnatal", "postpartum",
            "obstetric", "gynecolog", "gynaecolog",
            "labor and delivery", "in labor", "preterm labor",
            "cervic", "uterine", "uterus", "endometri",
            "ovarian", "ovary",
            "menstr", "menopaus", "perimenopaus",
            "miscarriage", "ectopic",
            "fetal", "foetal", "amniotic",
            "lactation", "breastfeed",
            "contracepti", "iud ", "oral contracept",
        ),
    ),
    (
        "psychiatry",
        (
            "depress", "anxiety", "anxious",
            "suicid", "self-harm", "self harm",
            "psychiatr", "psychosis", "psychotic",
            "bipolar", "schizophren", "mania", "manic",
            "panic attack", "panic disorder",
            "ptsd", "post-traumatic stress", "posttraumatic stress",
            "ocd ", "obsessive-compulsive", "obsessive compulsive",
            "eating disorder", "anorexi", "bulim",
            "substance use disorder", "substance abuse",
            "opioid use disorder", "alcohol use disorder",
            "borderline personality", "dissociative",
            "adhd ", "autism spectrum",
        ),
    ),
    (
        "emergency",
        (
            "emergency department", "emergency room", "urgent care",
            " ed ", " er ",
            "cardiac arrest", "code blue", "cpr ", "resuscitation",
            "trauma", "shock", "septic shock", "anaphyla",
            "seizure", "status epilepticus",
            "overdose", "poisoning", "intoxication",
            "stroke", "tia ", "stemi", "nstemi",
            "acute mi", "myocardial infarction",
            "pulmonary embol",
            "acute abdomen",
            "9-1-1", "911 call", "paramedic", "ems ",
            "collapsed", "unconscious", "unresponsive",
            "dka ", "diabetic ketoacidosis",
            "hemorrhag", "haemorrhag",
        ),
    ),
    ("general", ()),
]


def _flatten_user_content(prompt_messages: list[dict]) -> str:
    """Concatenate all user-role content for keyword matching."""
    parts: list[str] = []
    for msg in prompt_messages:
        if msg.get("role") == "user":
            c = msg.get("content", "")
            if isinstance(c, str):
                parts.append(c)
            elif isinstance(c, list):
                for block in c:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
    return " ".join(parts).lower()


def _age_prefix_match(text: str) -> bool:
    """Return True if text describes a young patient by age prefix.

    Matches patterns like "6 year old", "3-year-old", "12 yo", "9 y/o"
    with age <= 17. Pure-stdlib regex; no external deps.
    """
    import re

    patterns = [
        r"(\d+)\s*[- ]\s*year\s*[- ]\s*old",
        r"(\d+)\s*yo\b",
        r"(\d+)\s*y/o",
        r"age[:\s]+(\d+)",
    ]
    for pat in patterns:
        for match in re.finditer(pat, text):
            try:
                age = int(match.group(1))
            except (ValueError, IndexError):
                continue
            if age <= 17:
                return True
    return False


def classify(prompt_messages: list[dict]) -> str:
    """Assign one of the five strata to a HealthBench example.

    Priority order is the CLASS_KEYWORDS list order: pediatrics > obgyn
    > psychiatry > emergency > general. First-match-wins by priority.
    """
    text = _flatten_user_content(prompt_messages)
    # Pediatrics gets an age-prefix tiebreaker (upstream rarely says
    # "pediatric" when it says "a 4-year-old").
    if _age_prefix_match(text):
        return "pediatrics"
    for cls, keywords in CLASS_KEYWORDS:
        if not keywords:
            return cls  # general — fallthrough
        if any(kw in text for kw in keywords):
            return cls
    return "general"  # unreachable; CLASS_KEYWORDS ends with general


def _axis_from_tag(tag: str) -> str | None:
    """Extract axis name from a HealthBench rubric tag string."""
    if tag.startswith("axis:"):
        return tag.split(":", 1)[1]
    return None


def derive_target_axis(rubrics: list[dict]) -> str:
    """Pick the axis carrying the most point weight in this example's rubric.

    HealthBench rubric items carry tags like `axis:accuracy`. Each item's
    `points` contributes to its axis total. Ties broken alphabetically so
    classification is deterministic.
    """
    weights: Counter[str] = Counter()
    for item in rubrics:
        pts = float(item.get("points", 0))
        if pts <= 0:
            continue
        for tag in item.get("tags", []):
            axis = _axis_from_tag(tag)
            if axis is not None:
                weights[axis] += pts
    if not weights:
        return "accuracy"
    # Sort by (-weight, axis-name) for deterministic tiebreak.
    return sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


_FAILURE_MODE_TEMPLATES: dict[tuple[str, str], str] = {
    ("emergency", "accuracy"): "Misstates time-critical dose, drip rate, or decision threshold.",
    ("emergency", "completeness"): "Omits a red-flag differential or escalation step.",
    ("emergency", "context_awareness"): "Applies non-acute guidance to an actively deteriorating patient.",
    ("emergency", "instruction_following"): "Ignores the clinician role frame or acuity qualifier.",
    ("emergency", "communication"): "Fails to hand off with clear, ordered action items.",
    ("pediatrics", "accuracy"): "Uses adult dosing or adult reference ranges in a pediatric case.",
    ("pediatrics", "completeness"): "Omits age-appropriate differential or developmental consideration.",
    ("pediatrics", "context_awareness"): "Misses caregiver role or age-banded red flag.",
    ("pediatrics", "instruction_following"): "Ignores specified age band or caregiver-directed framing.",
    ("pediatrics", "communication"): "Uses adult-coded language for a caregiver-facing response.",
    ("obgyn", "accuracy"): "Misstates pregnancy-safe dosing or trimester-specific contraindication.",
    ("obgyn", "completeness"): "Omits fetal-surveillance or peripartum red flag.",
    ("obgyn", "context_awareness"): "Treats pregnant patient as non-pregnant default.",
    ("obgyn", "instruction_following"): "Ignores gestational-age or peripartum context.",
    ("obgyn", "communication"): "Fails to explain risk-benefit to a pregnant patient clearly.",
    ("psychiatry", "accuracy"): "Misstates dosing, interaction, or black-box warning for a psychotropic.",
    ("psychiatry", "completeness"): "Omits suicide / self-harm safety screen when indicated.",
    ("psychiatry", "context_awareness"): "Misses acute-safety cue embedded in patient history.",
    ("psychiatry", "instruction_following"): "Ignores clinician-vs-patient role framing or safety context.",
    ("psychiatry", "communication"): "Uses stigmatizing or escalating language with a vulnerable patient.",
    ("general", "accuracy"): "Misstates a canonical guideline number or first-line therapy.",
    ("general", "completeness"): "Omits a standard-of-care step or differential.",
    ("general", "context_awareness"): "Answers generic when the patient cue changes the recommendation.",
    ("general", "instruction_following"): "Ignores role, format, or scope qualifier in the prompt.",
    ("general", "communication"): "Gives an unordered or hedged answer where clarity is required.",
}


def expected_failure_mode(cls: str, axis: str) -> str:
    """Physician-reviewable failure-mode one-liner.

    Deterministic lookup by (class, axis). Flagged PENDING-REVIEW so the
    physician can override before the T4.7 harness run cites it.
    """
    base = _FAILURE_MODE_TEMPLATES.get(
        (cls, axis),
        f"[{cls}/{axis}] failure mode placeholder; physician to fill in.",
    )
    return f"{base} [PENDING-REVIEW]"


def load_corpus(source: Path) -> list[dict]:
    """Load the 1000-example HealthBench Hard JSONL, preserving line order."""
    if not source.exists():
        raise FileNotFoundError(f"HealthBench source not found: {source}")
    examples: list[dict] = []
    with source.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
    return examples


def stratify(
    examples: list[dict],
    counts: dict[str, int],
    seed: int,
) -> list[tuple[str, dict]]:
    """Return `sum(counts.values())` (cls, example) pairs, seed-deterministic.

    Within each stratum, candidates are sorted by `prompt_id` (upstream
    UUID), then `random.Random(seed).sample(candidates, n)` picks n.
    The seed is used verbatim — same seed, same source file, same
    selection.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    for ex in examples:
        cls = classify(ex["prompt"])
        buckets[cls].append(ex)
    # Deterministic ordering before sampling.
    for cls, items in buckets.items():
        items.sort(key=lambda e: e["prompt_id"])

    rng = random.Random(seed)
    picked: list[tuple[str, dict]] = []
    for cls, n in counts.items():
        pool = buckets.get(cls, [])
        if len(pool) < n:
            raise RuntimeError(
                f"Not enough examples in stratum {cls!r}: "
                f"have {len(pool)}, need {n}"
            )
        chosen = rng.sample(pool, n)
        for ex in chosen:
            picked.append((cls, ex))
    return picked


def render_manifest(
    picked: list[tuple[str, dict]],
    source: Path,
    seed: int,
) -> dict:
    """Build the dict that will be serialized as clinical_subset.yaml."""
    examples_out: list[dict] = []
    for idx, (cls, ex) in enumerate(picked, start=1):
        axis = derive_target_axis(ex.get("rubrics", []))
        prism_id = f"HBH-CLN-{idx:03d}"
        examples_out.append(
            {
                "id": prism_id,
                "healthbench_hard_example_id": ex["prompt_id"],
                "class": cls,
                "target_axis": axis,
                "expected_failure_mode": expected_failure_mode(cls, axis),
                "messages": ex["prompt"],
                "rubrics": ex["rubrics"],
            }
        )
    manifest = {
        "version": "0.1.0",
        "source": str(source),
        "seed": seed,
        "strata_counts": dict(STRATA_COUNTS),
        "total": len(examples_out),
        "notes": [
            "Stratified sample produced by scripts/sample_clinical_subset.py.",
            "Rerunning with the same seed + same source file reproduces it.",
            "expected_failure_mode strings are machine-generated templates "
            "keyed by (class, target_axis) and flagged PENDING-REVIEW. The "
            "physician reviews + edits these before the delta report cites "
            "them; the baseline (T4.6c/d) and harness (T4.7b) runners do "
            "not read this field.",
        ],
        "examples": examples_out,
    }
    return manifest


def write_yaml(manifest: dict, out: Path) -> None:
    """Write the manifest with stable key order (via explicit dump options)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        yaml.safe_dump(
            manifest,
            f,
            sort_keys=False,
            default_flow_style=False,
            allow_unicode=True,
            width=100,
        )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument(
        "--print-stratification-stats",
        action="store_true",
        help="Print per-class counts from the full source corpus and exit.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    examples = load_corpus(args.source)
    if args.print_stratification_stats:
        counts: Counter[str] = Counter()
        for ex in examples:
            counts[classify(ex["prompt"])] += 1
        print(f"source: {args.source}")
        print(f"total examples: {len(examples)}")
        for cls, _ in CLASS_KEYWORDS:
            print(f"  {cls:12s} {counts.get(cls, 0):4d}")
        return 0

    picked = stratify(examples, STRATA_COUNTS, args.seed)
    manifest = render_manifest(picked, args.source, args.seed)
    write_yaml(manifest, args.out)
    print(
        f"wrote {args.out} "
        f"({manifest['total']} examples, "
        f"strata={dict(STRATA_COUNTS)}, seed={args.seed})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
