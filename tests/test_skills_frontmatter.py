"""Skill frontmatter invariants — Anthropic Skills spec + Prism conventions.

Every `skills/prism-*/SKILL.md` carries YAML frontmatter with `name` and
`description`. The Anthropic Skills spec
(https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview,
re-verified 2026-04-22) pins:

- `name` <= 64 chars, lowercase + digits + hyphens only. **Reserved:** the
  tokens `anthropic` and `claude` may not appear as the full name.
- `description` <= 1024 chars, third person, must state what + when.
- SKILL.md body kept under 500 lines (progressive-disclosure Level 2
  target; skills blog recommendation).

Prism layers its own conventions on top:

- Parent directory name == `prism-{role}`; `name` frontmatter MUST match.
- Description starts with the literal tokens `Use this skill` so the
  coordinator's progressive-disclosure trigger is uniform across the
  bound set.
- Body contains at least one `self-check passed:` line so agents have a
  canonical "done" marker that the harness can pattern-match on.

These tests are offline, zero-cost, and ~1 ms per skill. They are wired
into `make verify-all` via the existing `smoke-t3` pytest target — the
"governance + skill-compatibility testing" pattern the Anthropic skills
blog (claude.com/blog/building-agents-with-skills-equipping-agents-for-
specialized-work) explicitly calls out as infrastructure-critical.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"

# Anthropic Skills spec caps (2026-04-22).
NAME_MAX = 64
DESCRIPTION_MAX = 1024
BODY_LINE_MAX = 500

NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
RESERVED_NAMES = {"anthropic", "claude"}

# Prism convention: every skill description begins with this literal.
PRISM_DESC_PREFIX = "Use this skill"
# Prism convention: every skill body emits this marker on completion.
PRISM_SELF_CHECK = "self-check passed:"


def _iter_skill_files() -> list[Path]:
    """Return every skills/prism-*/SKILL.md path, sorted for deterministic IDs."""
    return sorted(SKILLS_DIR.glob("prism-*/SKILL.md"))


def _parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Return (frontmatter_dict, body_text). Raises pytest.fail on a malformed doc."""
    text = path.read_text()
    if not text.startswith("---\n"):
        pytest.fail(f"{path.relative_to(REPO_ROOT)}: missing leading '---' frontmatter fence")
    rest = text[4:]
    end = rest.find("\n---\n")
    if end < 0:
        pytest.fail(f"{path.relative_to(REPO_ROOT)}: missing closing '---' frontmatter fence")
    fm_raw = rest[:end]
    body = rest[end + len("\n---\n"):]
    try:
        fm = yaml.safe_load(fm_raw) or {}
    except yaml.YAMLError as exc:
        pytest.fail(f"{path.relative_to(REPO_ROOT)}: frontmatter YAML parse error: {exc}")
    if not isinstance(fm, dict):
        pytest.fail(f"{path.relative_to(REPO_ROOT)}: frontmatter must be a mapping, got {type(fm).__name__}")
    return fm, body


# Parametrize every check by skill file so pytest reports per-skill
# failures granularly.
SKILL_FILES = _iter_skill_files()
SKILL_IDS = [p.parent.name for p in SKILL_FILES]


def test_at_least_six_role_skills_present() -> None:
    """Regression: the six phase-triggered role skills must all exist.

    Adding rail-triggered skills (clinical-review, etc.) is expansion.
    Dropping a role skill is drift that breaks the coordinator's bound
    set — catch it here before `scripts/register_skills.py` tries to
    upload.
    """
    names = {p.parent.name for p in SKILL_FILES}
    required = {
        "prism-defender",
        "prism-attacker",
        "prism-synthesizer",
        "prism-executor",
        "prism-adjudicator",
        "prism-planner",
    }
    missing = required - names
    assert not missing, f"missing required role skills: {sorted(missing)}"


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_name_key_present_and_string(skill_path: Path) -> None:
    fm, _ = _parse_frontmatter(skill_path)
    assert "name" in fm, "frontmatter missing required key `name`"
    assert isinstance(fm["name"], str), "`name` must be a string"
    assert fm["name"].strip() != "", "`name` must be non-empty"


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_name_matches_directory(skill_path: Path) -> None:
    """Prism convention: `name` frontmatter == parent directory name."""
    fm, _ = _parse_frontmatter(skill_path)
    expected = skill_path.parent.name
    assert fm["name"] == expected, (
        f"frontmatter name={fm['name']!r} does not match dir={expected!r}"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_name_obeys_spec_regex(skill_path: Path) -> None:
    """Anthropic Skills spec: lowercase alphanumeric + hyphens only, <= 64 chars."""
    fm, _ = _parse_frontmatter(skill_path)
    name = fm["name"]
    assert len(name) <= NAME_MAX, f"name {name!r} is {len(name)} chars (spec cap {NAME_MAX})"
    assert NAME_PATTERN.match(name), (
        f"name {name!r} violates spec pattern "
        f"(lowercase alnum + hyphens, no leading/trailing/double hyphen)"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_name_not_reserved(skill_path: Path) -> None:
    """Anthropic Skills spec: `anthropic` and `claude` are reserved."""
    fm, _ = _parse_frontmatter(skill_path)
    assert fm["name"] not in RESERVED_NAMES, (
        f"name {fm['name']!r} is reserved per Anthropic Skills spec"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_description_key_present_and_string(skill_path: Path) -> None:
    fm, _ = _parse_frontmatter(skill_path)
    assert "description" in fm, "frontmatter missing required key `description`"
    assert isinstance(fm["description"], str), "`description` must be a string"
    assert fm["description"].strip() != "", "`description` must be non-empty"


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_description_within_spec_length(skill_path: Path) -> None:
    """Anthropic Skills spec: `description` <= 1024 chars."""
    fm, _ = _parse_frontmatter(skill_path)
    desc = fm["description"]
    assert len(desc) <= DESCRIPTION_MAX, (
        f"description is {len(desc)} chars (spec cap {DESCRIPTION_MAX})"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_description_uses_prism_prefix(skill_path: Path) -> None:
    """Prism convention: descriptions begin with 'Use this skill' so the
    coordinator's progressive-disclosure trigger is uniform. Not an
    Anthropic spec constraint, but a Prism house-style invariant."""
    fm, _ = _parse_frontmatter(skill_path)
    assert fm["description"].startswith(PRISM_DESC_PREFIX), (
        f"description must start with {PRISM_DESC_PREFIX!r}; "
        f"got leading {fm['description'][:40]!r}"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_body_has_self_check_marker(skill_path: Path) -> None:
    """Prism convention: body emits a 'self-check passed:' line so the
    harness can pattern-match completion. Without this, the coordinator
    cannot reliably detect phase-end and will loop or hang."""
    _, body = _parse_frontmatter(skill_path)
    assert PRISM_SELF_CHECK in body, (
        f"body missing required marker {PRISM_SELF_CHECK!r} — "
        f"coordinator cannot detect phase-end without it"
    )


@pytest.mark.parametrize("skill_path", SKILL_FILES, ids=SKILL_IDS)
def test_body_under_line_cap(skill_path: Path) -> None:
    """Skills-blog recommendation: keep SKILL.md body under ~500 lines so
    it fits the Level-2 progressive-disclosure budget (<5k tokens)."""
    _, body = _parse_frontmatter(skill_path)
    line_count = body.count("\n")
    assert line_count <= BODY_LINE_MAX, (
        f"body is {line_count} lines (skills-blog Level-2 cap {BODY_LINE_MAX}); "
        f"move reference material into a REFERENCE.md or bundled script"
    )


def test_no_unknown_frontmatter_keys() -> None:
    """Allow `name` + `description` + a short allowlist of optional keys.

    Rejecting unknown keys early prevents silent divergence if someone
    copies a Claude Code subagent frontmatter (which uses different keys
    like `tools`, `model`) into a SKILL.md. A Skill's frontmatter surface
    is deliberately tiny per the spec.
    """
    allowed = {"name", "description", "license", "metadata"}
    problems: list[str] = []
    for path in SKILL_FILES:
        fm, _ = _parse_frontmatter(path)
        extras = sorted(set(fm.keys()) - allowed)
        if extras:
            problems.append(f"{path.relative_to(REPO_ROOT)}: unknown frontmatter keys {extras}")
    assert not problems, "\n".join(problems)
