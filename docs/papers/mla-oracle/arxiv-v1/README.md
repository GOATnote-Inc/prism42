# arxiv v1 submission bundle

This directory is the **self-contained** arxiv submission artifact for
the Phase M MLA decode oracle paper. Contents are pinned to the
commit that ships v1.

## Contents

| File | Role |
|---|---|
| `paper.tex` | Main text, 8 pages, uses `plainnat.bst`. Identical to `../paper.tex` at submission SHA. |
| `refs.bib`  | BibTeX, 18 primary-source entries. |
| `reproduction.sh` | Offline verification + hardware-rerun instructions. |
| `README.md` | This file. |

## Build

```bash
cd docs/papers/mla-oracle/arxiv-v1
pdflatex paper && bibtex paper && pdflatex paper && pdflatex paper
```

Expected: 8 pages, 0 errors, 0 undefined citations. If you see
`\placeholder{FIGURE 1/2}` in the body, those are **intentional**
figure stubs (`\fbox{...}` boxes describing what final figures will
show once M6b data lands); they render as visible gray boxes and do
not produce LaTeX warnings.

## What v1 claims (scoped, honest)

Two live executed reference rails (H100 CUDA bf16 + Trillium XLA
bf16), both PASS against the FP32 oracle within the bf16 tolerance
preset and within $7\times 10^{-6}$ of each other in cosine
similarity. This is **suggestive evidence** that the absorbed-form
MLA decode algebra is substrate-consistent at bf16 precision on
seeded inputs.

## What v1 does NOT claim

Kernel-local attribution for the three target public Blackwell bugs
(SGLang #10284, vLLM #38439, FlashInfer #3047) is explicitly labeled
**provisional** throughout the paper. Neither bf16 rail exercises
NVFP4 microscaling, TMEM/DSMEM, or trtllm-gen cubin dispatch. M6b
(B200 live run) is deferred pending RunPod B200 capacity; a v2
arxiv update is planned when capacity materializes.

## Submission metadata

- **Primary category:** `cs.PF` (Performance).
- **Cross-list:** `cs.LG` (Learning), `cs.DC` (Distributed Computing).
- **License:** MIT (code), arXiv non-exclusive (paper).
- **Endorsement:** required if the author has no prior arXiv
  submissions in `cs.PF` / `cs.LG` / `cs.DC`.
- **Companion artifact:** the live repo at
  <https://github.com/GOATnote-Inc/prism42> (tree/main/corpus/mla).
  Reviewers can clone, run `reproduction.sh`, and verify everything
  offline that doesn't require rented hardware.

## Pre-submission checklist

- [x] `pdflatex` clean (0 errors, 0 undefined citations).
- [x] All `\placeholder{M6-RESULT}` and `\placeholder{FAIL}` replaced
      with `\textit{deferred (v2)}`.
- [x] Abstract + Introduction + Conclusion framed as suggestive /
      provisional, not conclusion-first.
- [x] Every live number in Table 2 + Table 4 traces to a committed
      findings doc under `../../../findings/mla-oracle-*.md`.
- [x] `reproduction.sh` runs and exits 0 from a fresh clone.
- [ ] HUMAN (Brandon) final read-through.
- [ ] arXiv account set up + endorsement obtained if needed.
- [ ] Upload tarball via arxiv.org submission UI.

## v2 plan (when M6b lands)

1. Execute `corpus/mla/reproducers/MLA_BUG_{001,002,003}_*.py` on a
   RunPod B200 pod via `scripts/mla_oracle_runner.py`.
2. Replace `\textit{deferred (v2)}` cells in Table 1 (three bug rows)
   and Table 4 (three kernel rows) with the logged verdicts.
3. Update §6 Discussion: resolve the "provisional" kernel-local
   attribution to confirmed / revised based on what the data shows.
4. Bump arxiv version (same ID, v2). No retraction — v1 is honest
   about what was executed; v2 adds the deferred data.
