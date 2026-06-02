# Prism42 seed medical knowledge graph

**Status: ILLUSTRATIVE — NOT clinically attested.** This 100-node seed graph
exists to exercise the `nx-cugraph 26.04` retrieval-lane runtime end-to-end
before the full SNOMED/ICD-10/StatPearls/AHA medical corpus lands. The
content is hand-curated from publicly-published MPDS-9 protocol categories,
common emergency-medicine ICD-10 codes, and lay-language chief-complaint
phrasings. **Every edge requires physician review before it is used in any
deployment that touches a real caller.**

Per the user (Brandon Dent, MD), the canonical corpus build is user-led;
this seed graph is the *runtime* demo. Replace the four CSVs in this
directory with the physician-reviewed corpus once it is available.

## Files

| File | Rows | Schema |
|---|---|---|
| `complaints.csv` | 50 | `complaint_id, lay_phrase, mpds9_id, primary_icd10, severity_tier` |
| `mpds9_rules.csv` | 30 | `mpds9_id, mpds9_name, key_rule, source_url` |
| `icd10_codes.csv` | 20 | `icd10, description, statpearls_url` |
| `edges.csv` | 150 | `source, target, edge_type, weight` |

Edge types:

| edge_type | semantics | typical fan-out |
|---|---|---|
| `complaint_to_protocol` | chief complaint → MPDS-9 dispatch protocol | 50 (one per complaint) |
| `complaint_to_icd10` | chief complaint → primary ICD-10 code | 50 (one per complaint) |
| `icd10_to_statpearls` | ICD-10 → public clinical-guideline URL | 20 |
| `protocol_to_rule_ref` | MPDS-9 protocol → key dispositional reference | 30 |

Total: 150 edges, ~100 nodes (50 complaints + 30 protocols + 20 codes).

## How the runtime uses it

`scripts/build_seed_kg.py` loads these CSVs, constructs a `networkx.DiGraph`,
and serializes it to `data/seed_kg/graph.gpickle`. At inference time the
worker (or a retrieval test harness) loads the gpickle, calls
`nx.ancestors(G, entity_id)` or `nx.shortest_path(G, source, target)`, and
— with `NX_CUGRAPH_AUTOCONFIG=1` and `nx-cugraph-cu13` installed — the
traversal is accelerated on GPU automatically.

GPU break-even (per `findings/research/2026-04-27-future-stack/nx-cugraph-26.04.md`)
is around 4 K nodes; 100 nodes runs faster on CPU. The seed graph
demonstrates the *plumbing*, not the perf win. Perf win arrives with the
full corpus (100 K-1 M nodes).

## Sources / provenance

- **MPDS-9 protocol categories** — derived from the publicly-published
  Medical Priority Dispatch System v9 protocol structure (the protocol
  numbering 1-33 is widely documented in EMS public materials; the
  *internal* dispatch logic that drives card-by-card decision trees is
  IAED-licensed and **NOT** in this repo). Use the protocol numbers as
  category anchors only.
- **ICD-10-CM codes** — from CMS public release (https://www.cms.gov/medicare/icd-10/2026-icd-10-cm).
- **StatPearls links** — point at the StatPearls Publishing entry on
  NCBI Bookshelf (https://www.ncbi.nlm.nih.gov/books/NBK430685/), which
  is open-access (CC BY 4.0). Resolution per code is illustrative.
- **Lay phrasings** — drafted to reflect typical 911 caller phrasing
  (e.g., "I can't catch my breath" → MPDS-9 #6 BRTH). Not adjudicated
  against any specific corpus.

## License

Same as the parent repository (MIT). Note that *content* derived from the
canonical IAED MPDS protocol cards is NOT redistributable; this seed
graph stays at the protocol-category level only.
