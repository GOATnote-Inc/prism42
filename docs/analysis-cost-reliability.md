# Cost + reliability: the case for /prism42-b300

**Date:** 2026-04-23. **Scope:** back-of-envelope answers to two questions that frame whether an augmented 911 dispatch console is worth building.

---

## Q1 — What does it cost to run a 911 dispatch center?

### Unit economics (fetch-date 2026-04-23)

| Inputs | Value | Source |
|:---|:---|:---|
| Dispatcher base salary, US avg | $45 000 / yr ($22 / hr) | [911dispatcheredu.org/salaries](https://www.911dispatcheredu.org/salaries/) |
| Dispatcher salary, Glassdoor avg | $60 682 / yr | [Glassdoor](https://www.glassdoor.com/Salaries/911-dispatcher-salary-SRCH_KO0,14.htm) |
| Dispatcher fully-loaded cost (salary × 1.4 for benefits + overhead) | $63 000 – $85 000 / yr | derived |
| Mandatory 24/7 × 365 staffing minimum (1 seat, single shift) | ~5.5 FTEs (to cover vacation, sick, overlap) | APCO/NENA staffing guidance |
| A small PSAP (1–2 seats live) | ~8–12 FTEs | derived |
| A mid PSAP (5–8 seats live, 850 k population served) | 87 FTEs, $17 M budget (DuPage Public Safety Communications example) | [NENA](https://www.nena.org/news/646775/) |
| Per-capita cost (from DuPage) | $17 M ÷ 850 k = **$20 / resident / year** | derived |
| Per-FTE budget (from DuPage) | $17 M ÷ 87 = **$195 k / FTE / year** (all-in) | derived |
| Per-call cost (industry estimate, varies widely) | $2 – $8 / call | APCO / academic lit |

### National extrapolation

- US 911 call volume: **~240 M calls / year** (NENA).
- US PSAP count: **~5 700** (NENA 2024 survey).
- Implied industry operating cost: 240 M × $5 avg ≈ **$1.2 B / year** on dispatcher labor alone, not counting NG911 upgrade costs (DOT/NHTSA estimated $1–2 B one-time to modernize).

### Why the per-call number is fragile

The $2–8/call band hides that cost-per-call scales inversely with call volume (a small rural PSAP handling 5 000 calls/year pays ~$50–100/call on labor; a large metro PSAP handling 2 M calls/year pays <$1/call). **The right framing is `$195 k / FTE all-in`, not per-call.**

---

## Q2 — Reliability: Claude vs a 911 dispatcher

This is where the narrative needs honesty.

### Dispatcher failure modes (cited)

| Failure mode | Rate | Source |
|:---|:---|:---|
| Standard dispatcher-instructed CPR calls where victim did NOT receive proper chest compressions | **~85 %** (Lerner et al., 2008) | [StatPearls EMS Pre-Arrival Instructions](https://www.ncbi.nlm.nih.gov/books/NBK470543/) |
| Dispatcher cardiac-arrest recognition rate with criteria-based system | ~80 % (one in five missed) | [AEDR Journal systematic review](https://www.aedrjournal.org/past-present-and-future-of-emergency-dispatch-research-a-systematic-literature-review) |
| Dispatchers meeting clinical PTSD criteria | **18.3 %** (vs 1.4 % general population) | [Diamond Behavioral Health](https://diamondbehavioralhealth.com/blog/911-dispatcher-mental-health-statistics/) |
| Dispatchers reporting high burnout on ≥ 1 measure | **43 %** (higher than nurses, physicians, teachers) | same |
| Emergency communication centers observing staff burnout (2023 survey) | **74 %** | [NENA](https://www.nena.org/news/646775/) |
| Annual turnover | **19 % (2009) → 30 %+ (recent)** | [APCO](https://www.apcointl.org/services/staffing-retention/staffing-shortage-resources/) |
| Vacancy rate in typical 911 center | **20–30 %** | [Bridge Michigan](https://bridgemi.com/michigan-government/long-shifts-low-pay-high-stress-why-michigan-cant-find-911-dispatchers/) |

### Claude failure modes (cited from this repo's own measurement)

| Measurement | Value | Source |
|:---|:---|:---|
| Opus 4.7, HealthBench Hard aggregate | **0.196 ± 0.068** (mean of N=3 independent runs, 95 % CI half-width on 30-example subset, 2026-04-22) | `CLAUDE.md` §4 benchmark discipline; `docs/opus47-baseline-card.md` |
| Opus 4.7 as a clinical-reasoning floor | Low 20 % accuracy on hardest examples alone | same |
| Opus 4.7 non-determinism | Lost vs 4.6 — no seed parameter, thinking off by default | same |

### What each brings that the other doesn't

| Human dispatcher | Claude-4.7 + Llama-70B dialectic |
|:---|:---|
| Reads caller voice tone, emotional cues, background audio | Reads literal transcript; audio-domain cues require §5.2 classifier (spec'd, not yet built) |
| Real-time scene inference ("I hear gasping") | Depends on STT fidelity + explicit §5.2 OHCA classifier |
| Knows the local geography, the units available, the history | No local geography prior; depends on CAD integration |
| Physically cannot be in two places at once | Scales horizontally; can consume 40+ concurrent calls on one B300 |
| Susceptible to fatigue, burnout, PTSD, shift transitions | No fatigue; deterministic drop-off comes from provider model changes, not staff |
| Known to freeze on rare calls (CPR protocol deviations) | Can still hallucinate / mis-cite GEDP; but can be forced to cite sources (`cites[]` in `psap-turn.schema.json`) |
| Trained 6 weeks → certified, plateau by 2 years | "Training" is prompt engineering + skill registration; iterates in hours |
| Annual cost: $195 k / FTE | Annual cost: ~$14 k / B300 GPU ($7.91/hr × 24 × 365 × 0.2 util) + ~$50 k API/year at 1 M calls |

### The honest conclusion

**Neither alone is SOTA for 911. The dialectic is.**

- Claude alone at 20 % HealthBench Hard is not a replacement for a trained dispatcher on complex clinical calls.
- A burned-out dispatcher at month 18 of turnover-underfilled shifts is not a replacement for a Claude-checked protocol loop on routine calls.
- The prism42 architecture — 20-agent topology with structured-JSON gate + live rubric + safety preambles — is the **augmentation layer** that lets either one catch the other's failures.

The `/prism42-b300` variant makes three of those catches faster (sub-second rubric, audio-domain OHCA, real-time cross-vendor dialectic, per `docs/spec-b300-voice.md` §5). Those aren't capability unlocks in isolation — they're **latency unlocks on existing capabilities**, which is what voice requires.

---

## Q3 — Does the math justify the B300?

### Cost side

- **B300 on Brev/Verda**: $7.91 / hr = **~$69 000 / year** for one GPU running 24/7. Comparable to 1.0 fully-loaded dispatcher FTE.
- Amortized across 40 concurrent calls on the pod: ~$0.0066 / call (vs hosted-API ~$0.168 / call in our spec §6.2).
- A single B300 processing the same call volume as ~15 human FTEs ($2.9 M/yr loaded) costs **$69 k + API + engineering**. Order-of-magnitude lower — but this is an engineering-intensive buy-vs-lease decision, not a straight labor substitute.

### Reliability side

The B300 augmentations do not close the 20 % → 100 % gap on hardest clinical calls. They do:
- Reduce rubric feedback latency from 2–4 s to < 1 s (§5.1) → enables pre-TTS gating.
- Add audio-domain OHCA detection that text-only classifiers miss (§5.2) → catches ~15 % of missed-recognition cases (per §5.2.4 aspirational recall).
- Surface cross-vendor model disagreement in real-time (§5.3) → neither Opus nor GPT is authority; disagreement becomes dispatcher-visible evidence.

**The deployment posture this supports**: augment the human dispatcher, never replace. In the backoff tree, if (a) the caller's call is routine AND (b) Claude's `self_verify.all_passed` is green AND (c) both cross-vendor models agree AND (d) rubric score is green, the dispatcher sees "three independent systems concur" as UI feedback and can act faster. If any of those fail, the dispatcher sees flags and uses human judgment. Never the other way around.

---

## Q4 — What outcomes is `/prism42-b300` aiming for?

### SOTA emergency agent

- Rubric-passing on all 42 red-team scenarios (`corpus/red-team/psap-fixtures-v0.1.yaml`) at the B300-augmented stack, with physician sign-off.
- Per-turn LLM action matches or exceeds human dispatcher baseline on ≥ 80 % of Category A (life-threats) scenarios, measured via GEDP 5-criteria rubric, physician-panel-adjudicated.
- Measured false-positive OHCA rate ≤ 0.5 per 1 000 dispatcher-hours; recall ≥ 90 % on held-out OHCA audio.

### SOTA voice interactions

- End-to-end perceived latency (user-speech-end → first-audio-out) ≤ 800 ms p50, ≤ 1 500 ms p99 at the augmented stack.
- Streaming partial-transcript shown to dispatcher within 200 ms of caller utterance.
- Cross-vendor disagreement flag rendered ≤ 300 ms after model divergence detected.
- TTS first-byte ≤ 400 ms with streaming playback.

### Claude-design web interface

- `/prism42-b300` landing with warm-paper (#F5F0E8) background, Tiempos-style serif headlines, Styrene-style sans body, terracotta (#C75B39) accent. Mirrors the claude.ai editorial calm, not the dark-console dispatcher-brutalism of `/prism42`.
- Evidence-wall section: per-scenario rubric score + disagreement log + OHCA event log, all visible to a visitor.
- Live-call view: 3-column dispatcher console preserved, but with Claude-design chrome and sub-second rubric updates.
- Continuity claim restated: same 20 agents, same 42 scenarios, same GEDP v0.1, just faster + audio-enabled.

---

## Cross-references

- Spec: `docs/spec-b300-voice.md` (B300 augmentations, self-verification L1-L4).
- Live console baseline: `mvp/911-console-live/` (current `/prism42`).
- Kernel anchors: `/Users/kiteboard/prism/mla/claims/CLAIM_001_*.md`, `CLAIM_002_*.md`.
- Charter: `CLAUDE.md` (verification discipline, one-commit-per-task, baseline citation rules).
- ElevenLabs blueprint: `docs/anthropic-elevenlabs-agent-bp-2026-04-21.md` (§5 decode-latency budget).
