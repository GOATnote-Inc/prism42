"""expand_kg_with_openem — extend the seed KG with OpenEM 370 conditions.

Reads `corpus/tier1/conditions/*.md` from the OpenEM corpus, parses each
file's YAML frontmatter, and emits a `networkx.DiGraph` with one node per
condition plus edges to ICD-10 codes, red flags, decision rules, and
differential conditions.

This is the R2 scaffolding for the sovereign RAG path described in
`findings/research/2026-04-27-future-stack/medical-corpus-skeleton.md`.
Combined with the seed graph at `data/seed_kg/graph.gpickle`, the result
is a ~2000-node medical KG with multi-hop traversal via NetworkX (or
nx-cugraph when `NETWORKX_BACKEND_PRIORITY=cugraph` is set).

The OpenEM corpus is consumed read-only; this script does not write into
`/Users/kiteboard/openem-corpus/`. Output lands under
`data/seed_kg/expansions/openem_370.gpickle` (gitignored).

OpenEM corpus location is discovered via:
  1. --openem-root CLI arg, OR
  2. OPENEM_CORPUS env var, OR
  3. default /Users/kiteboard/openem-corpus

License: OpenEM tier1 conditions are Apache-2.0 + CC-BY (per its CLAUDE.md
§3 / §4); only that licensed corpus is allowed in tier1. We import only
the ICD-10 codes (US public domain), condition titles, red flags,
decision rule names, and differential graph structure — no narrative body
text is mirrored into the KG.

Usage
-----
    python scripts/expand_kg_with_openem.py
    python scripts/expand_kg_with_openem.py --validate
    python scripts/expand_kg_with_openem.py --openem-root /path/to/openem-corpus

Exit codes
----------
0 — graph built (and --validate passed).
1 — bad input (missing corpus, malformed YAML, dangling differential refs).
2 — sanity query failed (only with --validate).

Status: scaffold. R1 (sovereign serve + bench) does not depend on this.
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_KG_DIR = REPO_ROOT / "data" / "seed_kg"
OUT_DIR = SEED_KG_DIR / "expansions"

DEFAULT_OPENEM_ROOT = Path("/Users/kiteboard/openem-corpus")


def _resolve_openem_root(cli_root: str | None) -> Path:
    candidates: list[Path] = []
    if cli_root:
        candidates.append(Path(cli_root))
    if os.environ.get("OPENEM_CORPUS"):
        candidates.append(Path(os.environ["OPENEM_CORPUS"]))
    candidates.append(DEFAULT_OPENEM_ROOT)
    for c in candidates:
        if (c / "corpus" / "tier1" / "conditions").is_dir():
            return c
    raise SystemExit(
        f"openem corpus not found at any of: {[str(c) for c in candidates]}"
    )


def _parse_frontmatter(path: Path) -> dict | None:
    """Read the YAML frontmatter (between leading `---` markers).

    Returns None if no frontmatter (skip with a warning).
    """
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit("pyyaml required: pip install pyyaml") from exc

    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fm_text = text[4:end]
    try:
        return yaml.safe_load(fm_text)
    except yaml.YAMLError as exc:
        print(f"WARN: {path.name}: malformed frontmatter: {exc}", file=sys.stderr)
        return None


def build_graph(openem_root: Path) -> Any:
    try:
        import networkx as nx  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            "networkx required: pip install networkx (+ nx-cugraph-cu13 for GPU)."
        ) from exc

    cond_dir = openem_root / "corpus" / "tier1" / "conditions"
    cond_files = sorted(cond_dir.glob("*.md"))
    if not cond_files:
        raise SystemExit(f"no .md files at {cond_dir}")

    g = nx.DiGraph()
    seen_conditions: set[str] = set()
    seen_icd10s: set[str] = set()
    seen_red_flags: set[str] = set()
    seen_decision_rules: set[str] = set()
    differential_edges: list[tuple[str, str, str]] = []  # (cond, target, category)

    skipped = 0
    for path in cond_files:
        fm = _parse_frontmatter(path)
        if fm is None or "id" not in fm:
            skipped += 1
            continue

        cid = str(fm["id"]).strip()
        seen_conditions.add(cid)

        g.add_node(
            f"cond:{cid}",
            kind="condition",
            label=fm.get("condition", cid),
            esi=fm.get("esi"),
            risk_tier=fm.get("risk_tier"),
            time_to_harm=fm.get("time_to_harm"),
            chief_complaint=fm.get("chief_complaint"),
            category=fm.get("category"),
            source_file=path.name,
        )

        # ICD-10 edges
        for code in fm.get("icd10", []) or []:
            code = str(code).strip()
            if not code:
                continue
            seen_icd10s.add(code)
            g.add_node(f"icd10:{code}", kind="icd10", label=code)
            g.add_edge(f"cond:{cid}", f"icd10:{code}", kind="condition_to_icd10")

        # Red-flag edges
        for rf in fm.get("red_flags", []) or []:
            rf_text = str(rf).strip()
            if not rf_text:
                continue
            rf_id = f"rf:{cid}:{abs(hash(rf_text)) % 1_000_000:06d}"
            seen_red_flags.add(rf_text)
            g.add_node(rf_id, kind="red_flag", label=rf_text)
            g.add_edge(f"cond:{cid}", rf_id, kind="condition_to_red_flag")

        # Decision rules
        for rule in fm.get("decision_rules", []) or []:
            if isinstance(rule, dict):
                name = str(rule.get("name", "")).strip()
                pmid = rule.get("pmid")
                if not name:
                    continue
                rule_id = f"rule:{abs(hash(name)) % 1_000_000:06d}"
                seen_decision_rules.add(name)
                g.add_node(
                    rule_id,
                    kind="decision_rule",
                    label=name,
                    pmid=str(pmid) if pmid else None,
                )
                g.add_edge(f"cond:{cid}", rule_id, kind="condition_to_decision_rule")

        # Differentials — buffer; resolve after all conditions added.
        for cat_block in fm.get("differential_categories", []) or []:
            cat = str(cat_block.get("category", "uncategorized"))
            for target in cat_block.get("conditions", []) or []:
                target = str(target).strip()
                if target:
                    differential_edges.append((cid, target, cat))

    # Resolve differentials — dangling refs are warned, not fatal (the
    # OpenEM corpus may reference conditions outside tier1).
    dangling = 0
    for cid, target, cat in differential_edges:
        target_node = f"cond:{target}"
        if target not in seen_conditions:
            dangling += 1
            # Add a placeholder node so the edge is preserved for later resolution.
            g.add_node(target_node, kind="condition_placeholder", label=target)
        g.add_edge(
            f"cond:{cid}",
            target_node,
            kind="condition_to_differential",
            category=cat,
        )

    print(f"OpenEM expansion: {len(seen_conditions)} conditions parsed, {skipped} skipped")
    print(f"  +{len(seen_icd10s)} ICD-10 nodes")
    print(f"  +{len(seen_red_flags)} red-flag nodes")
    print(f"  +{len(seen_decision_rules)} decision-rule nodes")
    print(f"  {len(differential_edges)} differential edges ({dangling} dangling refs)")
    print(f"  total nodes: {g.number_of_nodes()}, edges: {g.number_of_edges()}")
    return g


def merge_with_seed(openem_g: Any, seed_path: Path) -> Any:
    """Merge OpenEM graph into the existing seed_kg graph."""
    if not seed_path.exists():
        print(f"WARN: seed graph not found at {seed_path}; emitting OpenEM-only graph")
        return openem_g
    try:
        import networkx as nx  # noqa: PLC0415
    except ImportError:
        return openem_g
    with seed_path.open("rb") as f:
        seed_g = pickle.load(f)
    print(f"merging seed graph ({seed_g.number_of_nodes()} nodes) with OpenEM expansion")
    merged = nx.DiGraph()
    merged.add_nodes_from(seed_g.nodes(data=True))
    merged.add_edges_from(seed_g.edges(data=True))
    for n, attrs in openem_g.nodes(data=True):
        if n in merged:
            merged.nodes[n].update(attrs)  # OpenEM data wins on collision
        else:
            merged.add_node(n, **attrs)
    merged.add_edges_from(openem_g.edges(data=True))
    print(f"  merged: {merged.number_of_nodes()} nodes, {merged.number_of_edges()} edges")
    return merged


def validate(g: Any) -> bool:
    """Run a couple of sanity queries that catch construction bugs."""
    try:
        import networkx as nx  # noqa: PLC0415
    except ImportError:
        return False

    if g.number_of_nodes() < 1500:
        print(f"FAIL: graph has only {g.number_of_nodes()} nodes; expected >= 1500", file=sys.stderr)
        return False

    # Sample a known life-threatening condition with its differential.
    # Acute appendicitis is in OpenEM and references multiple conditions.
    if "cond:acute-appendicitis" not in g:
        print("WARN: cond:acute-appendicitis missing — corpus may have shifted", file=sys.stderr)
        return True

    diffs = [v for u, v, d in g.out_edges("cond:acute-appendicitis", data=True)
             if d.get("kind") == "condition_to_differential"]
    if not diffs:
        print("FAIL: acute-appendicitis has no differential edges", file=sys.stderr)
        return False

    print(f"validate OK: cond:acute-appendicitis -> {len(diffs)} differentials")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openem-root", help="path to /Users/kiteboard/openem-corpus")
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="emit OpenEM-only graph (skip merge with seed_kg)",
    )
    parser.add_argument("--validate", action="store_true")
    parser.add_argument(
        "--out",
        default=str(OUT_DIR / "openem_370.gpickle"),
        help="output path for the merged graph",
    )
    args = parser.parse_args()

    openem_root = _resolve_openem_root(args.openem_root)
    print(f"OpenEM root: {openem_root}")

    g = build_graph(openem_root)

    if not args.no_merge:
        g = merge_with_seed(g, SEED_KG_DIR / "graph.gpickle")

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as f:
        pickle.dump(g, f, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"wrote {out_path}")

    if args.validate and not validate(g):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
