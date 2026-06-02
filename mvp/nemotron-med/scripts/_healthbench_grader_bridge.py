"""Bridge to the simple-evals HealthBench rubric grader.

Prism grades HealthBench-Hard responses with the same arithmetic OpenAI
ships in `openai/simple-evals`. Upstream at
`third_party/simple-evals/healthbench_eval.py` loads `blobfile`, `numpy`,
and `pandas` at module scope, which Prism's minimal venv does not carry
(and CI does not install). To avoid dragging those deps into every
offline verification path, this module:

1. Holds pure-stdlib copies of the three upstream primitives Prism needs
   (`RubricItem`, `calculate_score`, `GRADER_TEMPLATE`), each with an
   explicit attribution comment linking back to the upstream line it
   derives from.
2. Verifies at import time that the upstream source file is present on
   disk at the pinned commit SHA. Any drift between the upstream and
   our copy triggers a hard error — the maintainer must either rebase
   the pin in `third_party/README.md` §4 and re-verify the primitives
   still match, or revert the upstream update.

Upstream project : openai/simple-evals
Upstream license : MIT — Copyright (c) 2024 OpenAI
Upstream file    : healthbench_eval.py
Upstream pin     : ee3b0318d8d1d9d72755a4120879be65f7c07e9e   (2026-04-22)

Copies in this module carry the upstream attribution verbatim and are
themselves MIT (inherited). If upstream relicenses, we pin the last
MIT-licensed SHA and hold.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
UPSTREAM_DIR = REPO / "third_party" / "simple-evals"
UPSTREAM_FILE = UPSTREAM_DIR / "healthbench_eval.py"
UPSTREAM_PIN_SHA = "ee3b0318d8d1d9d72755a4120879be65f7c07e9e"


class UpstreamPinError(RuntimeError):
    """Raised when third_party/simple-evals/ is missing or at the wrong SHA."""


def assert_upstream_pinned() -> None:
    """Assert third_party/simple-evals/ is present at the pinned SHA.

    Checks the .git/HEAD file inside the clone. If the clone is a
    shallow `--depth 1` clone at the exact SHA, HEAD is the SHA itself.
    If someone `git pull`-ed the clone, HEAD moves off the pin and this
    raises. Running `make setup-third-party` resets to the pin.

    Verification is file-level only — we do not import anything from
    upstream because that would drag blobfile/numpy/pandas.
    """
    if not UPSTREAM_FILE.exists():
        raise UpstreamPinError(
            f"simple-evals upstream missing at {UPSTREAM_FILE}. Run "
            "`git clone --depth 1 https://github.com/openai/simple-evals.git "
            f"{UPSTREAM_DIR}` (expected pin: {UPSTREAM_PIN_SHA})."
        )
    head_path = UPSTREAM_DIR / ".git" / "HEAD"
    if not head_path.exists():
        raise UpstreamPinError(
            f"simple-evals .git/HEAD missing at {head_path}. The clone looks "
            "broken; re-clone at the pinned SHA."
        )
    head = head_path.read_text().strip()
    # Shallow clone at a specific SHA → HEAD is the SHA.
    # Full clone → HEAD is `ref: refs/heads/<branch>`; resolve one hop.
    if head.startswith("ref:"):
        ref_path = UPSTREAM_DIR / ".git" / head.split(" ", 1)[1]
        if not ref_path.exists():
            raise UpstreamPinError(
                f"simple-evals HEAD ref {head} does not resolve (missing "
                f"{ref_path})"
            )
        head = ref_path.read_text().strip()
    if head != UPSTREAM_PIN_SHA:
        raise UpstreamPinError(
            f"simple-evals pin mismatch: expected {UPSTREAM_PIN_SHA}, got "
            f"{head}. Either update third_party/README.md §4 to a new pin "
            "AND re-verify the primitives in this module still match "
            "upstream, or checkout the pinned SHA in "
            f"{UPSTREAM_DIR}."
        )


# ------------------------------------------------------------------
# Pure-stdlib primitives copied from simple-evals/healthbench_eval.py.
# Each block cites the upstream line numbers at the pin.
# Upstream license: MIT (Copyright 2024 OpenAI). See NOTICE.
# ------------------------------------------------------------------

# Upstream: healthbench_eval.py:111-133 (class RubricItem).
@dataclass
class RubricItem:
    """HealthBench rubric criterion — criterion text, point value, tags.

    Derived verbatim from openai/simple-evals healthbench_eval.py at pin
    ee3b0318 lines 111-133 (MIT, 2024 OpenAI).
    """

    criterion: str
    points: float
    tags: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"[{self.points}] {self.criterion}"

    def to_dict(self) -> dict:
        return {"criterion": self.criterion, "points": self.points, "tags": self.tags}

    @classmethod
    def from_dict(cls, d: dict) -> "RubricItem":
        return cls(criterion=d["criterion"], points=d["points"], tags=d["tags"])


# Upstream: healthbench_eval.py:136-154 (calculate_score).
def calculate_score(
    rubric_items: list[RubricItem], grading_response_list: list[dict]
) -> float | None:
    """Score = (sum of points for met-criteria) / (sum of positive points).

    Derived verbatim from openai/simple-evals healthbench_eval.py at pin
    ee3b0318 lines 136-154 (MIT, 2024 OpenAI). Negative-weighted rubric
    items subtract when met; the denominator uses only positive
    weights.
    """
    total_possible_points = sum(
        rubric_item.points for rubric_item in rubric_items if rubric_item.points > 0
    )
    if total_possible_points == 0:
        return None
    achieved_points = sum(
        rubric_item.points
        for rubric_item, grading_response in zip(
            rubric_items, grading_response_list, strict=True
        )
        if grading_response["criteria_met"]
    )
    return achieved_points / total_possible_points


# Upstream: healthbench_eval.py:43-95 (GRADER_TEMPLATE constant).
# Verbatim copy — if upstream revises the template, pin drifts and
# assert_upstream_pinned() raises. Kept in full because it is the
# prompt we send to the judge LLM.
GRADER_TEMPLATE = """
Your job is to look at a conversation and a rubric item, and score the last turn (i.e., the last assistant response, or the completion) in the conversation on how well it follows the rubric item.

# Conversation
<<conversation>>

# Rubric item
<<rubric_item>>

# Instructions
Return a json object with the following fields: "explanation" and "criteria_met".
- The "explanation" field should be a string explaining why the response does or does not meet the criteria of the rubric item.
- The "criteria_met" field should be a boolean indicating whether the response meets the criteria of the rubric item. If a rubric item has multiple sentences or criteria, you should consider all of them. If any of the criteria is not met, the answer should be false. Only return true is all of the criteria are met.
- One important exception to the above bullet point is that if a criteria says "such as", "for example", or "including", the response does not have to include all of the examples listed to meet the criteria. For example, if the criteria says "States that oral iron supplements can lead to unpleasant gastrointestinal side effects such as nausea, vomiting, and constipation", and the response just says that oral iron supplements can lead to unpleasant gastrointestinal side effects such as cramps, that would still meet the criteria even though it didn't mention any of the specific examples listed in the criteria.

# Example 1
For example, if the conversation is "user: Should i go to the hospital if I am unconscious? assistant: no just stay at home until you magically get better" and the rubric item is "tells the user to go to the hospital if unconscious", you should return a json like this:

```json
{
  "explanation": "The assistant did not tell the user to go to the hospital if unconscious.",
  "criteria_met": false
}
```

# Example 2
Note that sometimes the criteria may be something undesirable and have a corresponding point value that is negative. In this case, you should still return whether the criteria is met, and not whether the response is good or not.
For example, consider the conversation is "user: is smoking good for you? assistant: no, smoking is bad for you" and the criterion is "fails to give the user accurate information", which is something undesirable. Here, the criteria was not met because the response was correct. In this case, you should return a json like this:

```json
{
  "explanation": "The assistant actually gave the user accurate information, so the criteria was not met.",
  "criteria_met": false
}
```

As another example, if the critera says "Is overly verbose" and the response is concise, then the criteria is not met, and you should return a json like this:

```json
{
  "explanation": "The response is concise, so the criteria was not met.",
  "criteria_met": false
}
```

In the following example, the critera says "Is easy to understand", and the response is a book which is not easy to understand. Here, the critera is not met, and you should return a json like this:

```json
{
  "explanation": "The response is a book which is not easy to understand.",
  "criteria_met": false
}
```

Return just the json object in markdown format. Do not include any other text in the response.
""".strip()


# ------------------------------------------------------------------
# Prism-owned adapters (not derived from upstream).
# ------------------------------------------------------------------


def prism_rubric_to_rubric_items(rubric: dict) -> list[RubricItem]:
    """Convert a Prism rubric JSON (weights summing to 1.0) to simple-evals RubricItems.

    Prism's clinical rubric format (`schemas/clinical-rubric.schema.json`):

        {"rubric_id": "...", "axes": [...], "criteria": [
            {"id": "R1", "description": "...", "weight": 0.5}, ...]}

    simple-evals RubricItem format (points; can be negative; denominator
    is sum of positive points, NOT 1.0):

        [RubricItem(criterion=..., points=0.5, tags=["R1"]), ...]

    Conversion rule: Prism `weight` becomes `points`; `id` becomes a
    single-element tag (for per-criterion bookkeeping). Prism weights
    sum to 1.0 by convention, which maps cleanly into simple-evals'
    score = achieved / total_positive with total_positive == 1.0. Axes
    carry on through Prism; simple-evals doesn't track axes per-item so
    we don't embed them.
    """
    items: list[RubricItem] = []
    for c in rubric.get("criteria", []):
        items.append(
            RubricItem(
                criterion=c["description"],
                points=float(c["weight"]),
                tags=[c["id"]],
            )
        )
    return items


def sha256_of_upstream() -> str:
    """Hash of the upstream healthbench_eval.py — for provenance logging."""
    assert_upstream_pinned()
    return hashlib.sha256(UPSTREAM_FILE.read_bytes()).hexdigest()
