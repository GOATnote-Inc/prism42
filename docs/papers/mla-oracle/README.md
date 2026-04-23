# MLA decode oracle — arxiv paper

Phase M / M8 deliverable. See `docs/mla-oracle-roadmap.md` §3 M8.

**Working title:** A Cross-Accelerator Correctness Oracle for MLA Decode:
Finding FP4 Failures on NVIDIA Blackwell and Verifying on Google Trillium.

**Target venue:** arXiv preprint before 2026-04-24 (MLSys 2026
FlashInfer kernel-contest submission deadline). No contest entry; arxiv
precedence anchors the work.

## Files

| File | Role |
|---|---|
| `paper.tex` | Main body, 8–10 pages, four tables + two figures |
| `refs.bib` | BibTeX, primary sources only (arxiv, github, NVIDIA docs) |
| `figures/` | Generated from M6/M7 results — `architecture.pdf`, `divergence.pdf` |
| `arxiv-v1/` | Submission tarball — `paper.tex` + `refs.bib` + `figures/*.pdf` + `reproduction.sh` |

## Build

```bash
cd docs/papers/mla-oracle
pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper
open paper.pdf
```

Every `[M6-RESULT]` and `[M7-RESULT]` placeholder is a table cell that
fills in once the corresponding live run completes. The placeholders are
deliberately colored `blue` in the TeX so they're visually impossible to
miss in a pre-submission review.

## Provenance requirement (hard)

Every number in the paper must trace to an executed artifact under
`results/mla-oracle/<run_id>/verdict.json` with `(hardware_id,
commit_SHA, timestamp)` triple. Before submission, a grep sweep
confirms no numerical claim is inline-hardcoded:

```bash
# All numerical tables should reference \placeholder{M6-RESULT} or
# \placeholder{M7-RESULT} until filled; after filling, a sidecar
# results-digest.json must match every cell.
grep -nE '\\placeholder\{(M6|M7)-RESULT\}' paper.tex | wc -l    # 0 before submission
grep -nE '\\placeholder\{FAIL\}' paper.tex | wc -l              # 0 before submission
```

## Arxiv submission bundle

The `arxiv-v1/` subdir is the tarball scaffolding. Contents:

```
arxiv-v1/
  paper.tex              # identical to ../paper.tex at submission commit SHA
  refs.bib
  figures/
    architecture.pdf
    divergence.pdf
  reproduction.sh        # one-command replay of every M6/M7 number
  README.md              # points at the commit SHA + rental hardware IDs
```

`reproduction.sh` fetches the exact repo commit, sets up the venv,
ensures numpy is installed, and runs the oracle against each committed
golden. It does NOT rent live hardware — instead it loads the verdict
JSONs committed under `results/mla-oracle/` at that SHA and re-grades
them against the committed goldens. This gives bit-exact reproduction
without requiring the reader to spin up a B200 / Trillium.

For the live runs themselves, the release note in `arxiv-v1/README.md`
points at the commit-pinned version of `scripts/mla_oracle_runner.py`
plus the reproducer scripts under `corpus/mla/reproducers/`, with
the rented-hardware instructions.

## Pre-submission gate

Before upload to arxiv:

- [ ] `pdflatex` clean build, no warnings
- [ ] All `[M6-RESULT]` / `[M7-RESULT]` / `[FAIL]` placeholders replaced
- [ ] `arxiv-v1/` tarball builds reproduction.sh that exits 0
- [ ] HUMAN read-through (Brandon) before upload
- [ ] arxiv categories: cs.PF (primary), cs.LG, cs.DC (cross-list)

## v2 plan

After v1 lands, expected follow-ups:

- Fleshed-out kernel trigger bodies in `corpus/mla/reproducers/*.py`
  (scaffold → full trigger + dependency pins).
- NVFP4 MLA decode kernel in CUTLASS CuTe DSL that passes the oracle
  (the positive-case counterpart to the three bug repros).
- Empirical tolerance-preset tightening after a calibration sweep.
- Full MLSys / SC workshop paper submission.
