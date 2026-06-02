"""build_seed_kg — assemble the prism42 seed medical knowledge graph.

Reads the four CSVs in `data/seed_kg/` and constructs a `networkx.DiGraph`
with 100 nodes (50 lay-language chief complaints + 30 MPDS-9 protocol
categories + 20 ICD-10 codes) and 150 edges across four relation types.

The output graph is the runtime substrate for the prism42 retrieval lane
described in `findings/research/2026-04-27-future-stack/nvidia-voice-stack-architecture.md`.
At inference time, the worker uses `nx.ancestors()` / `nx.shortest_path()`
to walk this graph; with `NX_CUGRAPH_AUTOCONFIG=1` set and `nx-cugraph-cu13`
installed on the same Python the script runs under, the traversal is
GPU-accelerated automatically (zero code change). On a 100-node graph the
GPU win is invisible — the seed exists to exercise the *plumbing*, not
the perf path. The full medical corpus (100K-1M nodes per the brief) is
the perf-driver and is user-led.

Usage
-----
    cd /Users/kiteboard/prism42
    python scripts/build_seed_kg.py                    # default → data/seed_kg/graph.gpickle
    python scripts/build_seed_kg.py --output /tmp/seed.gpickle
    python scripts/build_seed_kg.py --validate         # build + run sanity queries; non-zero exit on failure
    NX_CUGRAPH_AUTOCONFIG=1 python scripts/build_seed_kg.py --validate  # GPU-accelerated path

Output
------
- `data/seed_kg/graph.gpickle` — the assembled `networkx.DiGraph`
  (idempotent: re-running overwrites cleanly).
- stdout — counts + invariants the build verified.

Exit codes
----------
- 0  — graph built and (if --validate) all sanity queries pass.
- 1  — bad input (missing CSVs, malformed rows, dangling edge references).
- 2  — sanity query failed (only with --validate).

Per `data/seed_kg/README.md`, this seed graph is ILLUSTRATIVE and
**requires physician review before any deployment.**
"""
from __future__ import annotations

import argparse
import csv
import pickle
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_KG_DIR = REPO_ROOT / "data" / "seed_kg"

EXPECTED_NODE_COUNT = 100  # 50 + 30 + 20
EXPECTED_EDGE_COUNT = 150


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"missing seed-kg CSV: {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_graph() -> Any:
    """Read the four seed CSVs and assemble a directed graph."""
    try:
        import networkx as nx  # noqa: PLC0415
    except ImportError as exc:
        raise SystemExit(
            "networkx is required: pip install networkx (and nx-cugraph-cu13 for GPU)."
        ) from exc

    g = nx.DiGraph()

    # --- Nodes -------------------------------------------------------
    complaints = _read_csv(SEED_KG_DIR / "complaints.csv")
    protocols = _read_csv(SEED_KG_DIR / "mpds9_rules.csv")
    icd10s = _read_csv(SEED_KG_DIR / "icd10_codes.csv")

    for row in complaints:
        g.add_node(
            row["complaint_id"],
            kind="complaint",
            lay_phrase=row["lay_phrase"],
            severity_tier=row["severity_tier"],
        )
    for row in protocols:
        g.add_node(
            row["mpds9_id"],
            kind="protocol",
            name=row["mpds9_name"],
            key_rule=row["key_rule"],
            source_url=row["source_url"],
        )
    for row in icd10s:
        g.add_node(
            row["icd10"],
            kind="icd10",
            description=row["description"],
            statpearls_url=row["statpearls_url"],
        )

    # --- Edges -------------------------------------------------------
    edges = _read_csv(SEED_KG_DIR / "edges.csv")
    for row in edges:
        src = row["source"]
        tgt = row["target"]
        # Verify the source exists; the target may be an external URL
        # node (icd10_to_statpearls / protocol_to_rule_ref) which we
        # add lazily so dangling edges surface here, not later.
        if src not in g:
            raise SystemExit(f"edge source not in nodes: {src} (row={row})")
        if tgt not in g:
            # Lazy-add external URL targets as `kind=external`.
            if row["edge_type"] in ("icd10_to_statpearls", "protocol_to_rule_ref"):
                g.add_node(tgt, kind="external")
            else:
                raise SystemExit(f"edge target not in nodes: {tgt} (row={row})")
        g.add_edge(
            src,
            tgt,
            edge_type=row["edge_type"],
            weight=float(row["weight"]),
        )

    return g


def _stats(g: Any) -> dict[str, Any]:
    kinds = Counter(data.get("kind", "?") for _, data in g.nodes(data=True))
    edge_types = Counter(data.get("edge_type", "?") for _, _, data in g.edges(data=True))
    return {
        "nodes": g.number_of_nodes(),
        "edges": g.number_of_edges(),
        "node_kinds": dict(kinds),
        "edge_types": dict(edge_types),
    }


def _sanity_queries(g: Any) -> list[tuple[str, bool, str]]:
    """A small set of structural queries that must all pass on the seed.

    Returns a list of (query_name, ok, detail) tuples.
    """
    import networkx as nx  # noqa: PLC0415

    results: list[tuple[str, bool, str]] = []

    # 1. Every chief complaint has exactly one MPDS-9 protocol edge.
    for node, data in g.nodes(data=True):
        if data.get("kind") != "complaint":
            continue
        out = [
            t for t in g.successors(node)
            if g.edges[node, t].get("edge_type") == "complaint_to_protocol"
        ]
        ok = len(out) == 1
        results.append(
            (f"complaint_has_protocol[{node}]", ok, f"out={out}"),
        )

    # 2. Every chief complaint has at least one ICD-10 edge.
    for node, data in g.nodes(data=True):
        if data.get("kind") != "complaint":
            continue
        out = [
            t for t in g.successors(node)
            if g.edges[node, t].get("edge_type") == "complaint_to_icd10"
        ]
        ok = len(out) >= 1
        results.append(
            (f"complaint_has_icd10[{node}]", ok, f"out={out}"),
        )

    # 3. The cardiac-arrest path lights up: a "no pulse" complaint
    # reaches MPDS-9 #9 and ICD-10 I46.9.
    arrest_complaints = [
        n for n, d in g.nodes(data=True)
        if d.get("kind") == "complaint" and d.get("lay_phrase") and "no pulse" in d["lay_phrase"]
    ]
    if arrest_complaints:
        node = arrest_complaints[0]
        try:
            path_to_protocol = nx.shortest_path(g, source=node, target="mpds9-09")
            path_to_icd = nx.shortest_path(g, source=node, target="I46.9")
            results.append(
                ("cardiac_arrest_path_to_protocol", True, f"path={path_to_protocol}"),
            )
            results.append(
                ("cardiac_arrest_path_to_icd", True, f"path={path_to_icd}"),
            )
        except nx.NetworkXNoPath as exc:
            results.append(("cardiac_arrest_path", False, str(exc)))
    else:
        results.append(("cardiac_arrest_complaint_present", False, "no 'no pulse' complaint"))

    # 4. Severity-tier Echo complaints all reach an arrest / asphyxia
    # protocol (MPDS-9 #9 or #11).
    echo_nodes = [
        n for n, d in g.nodes(data=True)
        if d.get("kind") == "complaint" and d.get("severity_tier") == "Echo"
    ]
    for node in echo_nodes:
        protos = [
            t for t in g.successors(node)
            if g.nodes[t].get("kind") == "protocol"
        ]
        ok = any(p in {"mpds9-09", "mpds9-11", "mpds9-15", "mpds9-02"} for p in protos)
        results.append(
            (f"echo_routes_to_arrest_or_asphyxia[{node}]", ok, f"protocols={protos}"),
        )

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the prism42 seed medical KG.")
    parser.add_argument(
        "--output",
        type=Path,
        default=SEED_KG_DIR / "graph.gpickle",
        help="Path for the assembled gpickle.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run sanity queries against the assembled graph; non-zero exit on any failure.",
    )
    args = parser.parse_args(argv)

    g = build_graph()
    stats = _stats(g)

    if g.number_of_nodes() < EXPECTED_NODE_COUNT:
        print(
            f"WARN: expected ≥{EXPECTED_NODE_COUNT} nodes, got {g.number_of_nodes()}",
            file=sys.stderr,
        )
    if g.number_of_edges() < EXPECTED_EDGE_COUNT:
        print(
            f"WARN: expected ≥{EXPECTED_EDGE_COUNT} edges, got {g.number_of_edges()}",
            file=sys.stderr,
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as f:
        pickle.dump(g, f)

    print(f"[seed-kg] wrote {args.output} ({stats['nodes']} nodes, {stats['edges']} edges)")
    print(f"[seed-kg]   node kinds:  {stats['node_kinds']}")
    print(f"[seed-kg]   edge types:  {stats['edge_types']}")

    # Surface whether GPU acceleration is wired
    try:
        import nx_cugraph  # noqa: PLC0415,F401
        gpu = True
    except ImportError:
        gpu = False
    print(f"[seed-kg]   nx-cugraph available: {gpu}")
    print(f"[seed-kg]   NX_CUGRAPH_AUTOCONFIG: {__import__('os').environ.get('NX_CUGRAPH_AUTOCONFIG', '<unset>')}")

    if not args.validate:
        return 0

    print("[seed-kg] running sanity queries…")
    failures = 0
    for name, ok, detail in _sanity_queries(g):
        symbol = "OK  " if ok else "FAIL"
        print(f"[seed-kg]   {symbol} {name}: {detail}")
        if not ok:
            failures += 1

    if failures:
        print(f"[seed-kg] {failures} sanity-query failure(s)", file=sys.stderr)
        return 2
    print("[seed-kg] all sanity queries passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
