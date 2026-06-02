# Medical Corpus Skeleton — Team D Deliverable

**Date:** 2026-04-27 · **Status:** scaffolding only · **Owner:**
Brandon Dent, MD (corpus content + licensing + provenance trail);
assistant scopes the structure.

This is the directory + manifest shape for the user-led medical
fine-tune corpus referenced in
[`medical-fine-tune-plan.md`](medical-fine-tune-plan.md). It exists
so that when content arrives, there's a place to put it that the
later eval / training pipeline can consume without reinvention.

**Hardware-agnostic; $0 to land.** No GPU touch.

## 1. Where it lives

Two acceptable locations; pick one and commit to it:

- **In-repo private subtree:** `corpus/clinical-fine-tune-v0/`
  under prism42, gitignored from the public branch. Pros: single
  source of truth + version-controlled. Cons: prism42 is a public
  repo; PHI / DUA-restricted material cannot live here even
  gitignored (forensic risk).
- **Separate private repo:** `github.com/GOATnote-Inc/clinical-
  corpus-v0` (private). Pros: clean separation; PHI-safe under
  GitHub's enterprise-data terms (with BAA when relevant). Cons:
  cross-repo coordination overhead.

**Recommendation:** separate private repo. PHI / DUA work demands
a separate access boundary. The prism42 public repo references the
corpus by manifest hash only.

This skeleton assumes **separate private repo**. Paths below are
relative to that repo's root.

## 2. Directory shape

```
clinical-corpus-v0/
├── README.md                       # this skeleton, in the corpus repo
├── LICENSING.md                    # per-source license + DUA tracker
├── MANIFEST.yaml                   # canonical hash list for every file
├── docs/
│   ├── physician-review-log.md    # Brandon Dent, MD sign-offs
│   ├── data-use-agreements/        # DUAs (PDFs), one per source
│   └── irb-determinations/         # IRB exempt / approved letters
├── sources/                        # raw source files, immutable
│   ├── pubmed/                     # PMC OA articles (JSON-NXML)
│   ├── statpearls/                 # NCBI Bookshelf NBK*
│   ├── guidelines/                 # AHA/NHTSA/NHS PDFs + extracted text
│   ├── fhir/                       # synthetic + MIMIC-class bundles
│   │   ├── openem-synthetic/       # from openem-corpus
│   │   └── mimic-iv/               # post-DUA only
│   ├── psap-protocols/             # public dispatcher protocols
│   └── physician-annotations/      # Brandon-Dent-MD authored content
├── derived/                        # cleaned + chunked + tokenized
│   ├── train/                      # fine-tune training shards
│   │   ├── shard-0000.parquet
│   │   └── ...
│   ├── eval/                       # held-out, never used for training
│   │   ├── healthbench-hard-30/    # mirror of pinned eval subset
│   │   ├── medqa-control/
│   │   ├── pubmedqa-rag/
│   │   └── medagentbench-44/
│   └── physician-review/           # candidate examples for MD review
├── scripts/
│   ├── fetch_pubmed.py             # idempotent fetcher; manifest-aware
│   ├── extract_fhir.py             # OpenEM → fine-tune format
│   ├── chunk_and_dedupe.py         # 4 K context, near-dup guard
│   ├── verify_no_claude_outputs.py # AUP gate (see §5)
│   ├── verify_no_eval_contamination.py  # eval/train disjoint
│   └── update_manifest.py          # rehash + re-sign
├── tests/
│   ├── test_manifest_integrity.py  # every file appears, hash matches
│   ├── test_license_coverage.py    # every source has a license entry
│   ├── test_no_phi_leak.py         # PHI scrub regression
│   └── test_no_aup_violation.py    # smoke-test the AUP gate
└── .github/
    └── workflows/
        └── verify.yml              # CI runs all four tests on push
```

**Discipline matches prism42's own:** verification gates at every
step, `make verify-all` umbrella, AST-checked containment for any
external API calls, no commit ships without CI green.

## 3. Manifest schema (`MANIFEST.yaml`)

Every file in `sources/` and `derived/` MUST appear in the manifest.
The eval / training pipeline keys off this file, not the
filesystem; missing-from-manifest = does-not-exist.

```yaml
version: 0
generated_at: 2026-04-27T00:00:00Z
generator: scripts/update_manifest.py@<git-sha>
sources:
  - id: pubmed-pmc-oa-2026-04-snapshot
    path: sources/pubmed/pmc-oa-2026-04.tar.zst
    sha256: <64-hex>
    bytes: 0
    license: CC-BY (per PMC OA subset terms)
    license_url: https://www.ncbi.nlm.nih.gov/pmc/about/copyright/
    fetched_at: 2026-04-27T00:00:00Z
    fetched_by: scripts/fetch_pubmed.py@<sha>
    aup_clean: true                    # no Claude outputs
    eval_quarantined: false            # not part of any eval corpus
    physician_reviewed: false          # not required for raw literature
    notes: ""
derived:
  - id: train-shard-0000
    path: derived/train/shard-0000.parquet
    sha256: <64-hex>
    bytes: 0
    derived_from:
      - pubmed-pmc-oa-2026-04-snapshot
      - statpearls-2026-04
    deriver: scripts/chunk_and_dedupe.py@<sha>
    chunked_at: 2026-04-27T00:00:00Z
    tokens: 0
    aup_clean: true
    eval_quarantined: true             # never see eval examples
    physician_reviewed: false
```

**Required fields per entry:**
- `id` — stable across re-fetches
- `path` — relative to repo root
- `sha256` — content hash; mismatch is a hard CI fail
- `license` + `license_url` — the binding text
- `aup_clean: bool` — true means no Claude outputs in the chain
- `eval_quarantined: bool` — true means this file is or descends
  from an eval set; training pipeline skips it
- `physician_reviewed: bool` — true means MD signed off (see §6)

## 4. License-tracking shape (`LICENSING.md`)

A single markdown table, one row per source:

```markdown
| Source | License | DUA needed? | DUA path | Commercial OK? | AUP-clean? |
|---|---|---|---|---|---|
| PubMed PMC OA subset | CC-BY (mostly) + per-article | no | — | yes (with attribution) | yes |
| StatPearls / NCBI NBK | NCBI Bookshelf terms | no | — | yes | yes |
| AHA BLS 2025 | © AHA | yes (limited reproduction) | docs/data-use-agreements/aha-2025.pdf | conditional | yes |
| MIMIC-IV | PhysioNet credentialed | yes (DUA + CITI) | docs/data-use-agreements/mimic-iv-dua.pdf | research only | yes |
| Brandon-Dent-MD content | © GOATnote, all rights | no | — | yes | yes |
```

Anything with `Commercial OK = no` or `Commercial OK = conditional`
gets an explicit policy note in the row. Anything with
`AUP-clean? = no` is **not allowed in the corpus** — fail the
build.

## 5. AUP gate (the bright line)

`scripts/verify_no_claude_outputs.py` is the load-bearing CI check.
It enforces the rule: **no Anthropic API outputs in the training
set.** Mechanism:

1. Every `sources/` file's `derived_from` chain must terminate at
   a non-Anthropic source.
2. Any file whose `fetched_by` script ever called `anthropic.*`
   marks `aup_clean: false`. CI fails on `aup_clean: false` in
   `derived/train/`.
3. A repo-wide grep refuses commits where any tracked file
   contains a known Claude API response signature
   (`stop_reason`, `usage.output_tokens`, etc.) outside `eval/`.

This gate is the difference between "fine-tuning Nemotron on
medical literature" (allowed) and "distilling Claude into Nemotron"
(prohibited). See `medical-fine-tune-plan.md` §2 and Anthropic's
Usage Policy: https://www.anthropic.com/legal/aup.

## 6. Physician review log

`docs/physician-review-log.md` is append-only; every entry is one
batch of N candidate examples reviewed by Brandon Dent, MD with a
verdict and rationale. Entry shape:

```markdown
## 2026-05-XX · batch 0001 (10 examples)

- Reviewer: Brandon Dent, MD (NPI: <redacted>)
- Source batch: derived/physician-review/batch-0001.jsonl
  (sha256: <hash>)
- Verdict: 8 approved, 2 rejected
- Rejected example IDs: PR-0001-003 (factually incorrect dose),
  PR-0001-007 (ambiguous indication)
- Approved examples promoted to: derived/train/shard-XXXX.parquet
  (next chunk_and_dedupe run)
- Notes: ...
```

Approved examples flip `physician_reviewed: true` in the manifest.
Rejected examples are **kept in the audit trail** (not deleted) so
the bias of the review process is itself auditable.

## 7. Eval-set quarantine (the contamination guard)

`scripts/verify_no_eval_contamination.py` enforces:
1. Every entry in `derived/eval/` has `eval_quarantined: true`.
2. No entry in `derived/train/` has `eval_quarantined: true`.
3. No `derived_from` graph in `derived/train/` includes an
   eval-quarantined source.

This is a hard CI fail, not a warning. Eval contamination is the
single most-cited methodology failure in medical-LLM literature; we
defend against it at the dependency-graph layer, not just the
filename layer.

## 8. What's NOT in this skeleton

- Tokenizer pin / training script — those go in a *training* repo,
  not the corpus repo. Corpus stays data-only.
- Model weights — also belong in a separate artifact store.
- Synthetic data generation pipelines — if you ever add them, they
  need their own AUP-clean attestation per generator.
- LoRA adapter checkpoints — out of scope; that's training-repo
  territory.

## 9. First-run checklist (when corpus work starts)

- [ ] Decide repo location (recommend separate private repo).
- [ ] `git init` + push the empty skeleton above.
- [ ] Wire CI workflow `verify.yml` calling all four tests.
- [ ] Land first `sources/` entry (suggest StatPearls subset —
      smallest license burden, broad EM coverage).
- [ ] Run `scripts/update_manifest.py`; confirm CI green.
- [ ] First physician-review batch (10 examples) before anything
      promotes to `derived/train/`.
- [ ] Only THEN talk about training. Corpus quality bounds model
      quality; this is the highest-leverage step.

## 10. References

- [`medical-fine-tune-plan.md`](medical-fine-tune-plan.md) — why
  this corpus exists; AUP framing.
- [Anthropic Usage Policy](https://www.anthropic.com/legal/aup) —
  the policy the AUP gate enforces.
- prism42 `CLAUDE.md` §4 (verification discipline) and §10
  (clinical findings disclosure posture) — the operating rails
  this corpus inherits.
- prism42 `corpus/pins/healthbench-hard-1000.yaml` — example of
  the manifest-pin shape that this corpus's eval directory should
  mirror.
