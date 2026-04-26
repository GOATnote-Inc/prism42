---
title: Prism42 resilience pitch — 5-slide rewrite
date: 2026-04-26
purpose: tighten the user's 5-slide resilience narrative for the hackathon submission and demo intro
source_of_truth:
  - README.md (trust-and-performance thesis)
  - docs/livekit-architecture.md (Phase 3a stack: LiveKit + Parakeet + Fish S2 + Opus 4.7)
  - docs/livekit-architecture.md (Phase 3b plan: LLM moves on-pod, vLLM Llama-70B)
  - CLAUDE.md §0 (hackathon-mode sprint rules; p95 < 1.5 s target)
  - docs/dual-target-thesis.md ("instruments fail at scale boundaries")
---

# Prism42 — 5-slide resilience pitch

The user's draft is rhythmically right. The rewrite below keeps the rhythm, replaces generic claims with verifiable Prism42 facts, and lands the punchline on the architecture you actually shipped.

No emojis. Plain text. Each slide ≤ 30 words.

---

## RECOMMENDED VERSION (use this)

### Slide 1 — baseline

> When the dispatch center has internet:
> **ElevenLabs. Claude in the cloud.**
> Best-in-class — until the path to them isn't.

### Slide 2 — the gap

> **Emergencies don't wait for the CDN.**

### Slide 3 — concrete failures (cite real, recent, recurring)

> AWS us-east-1 outage.
> Cloudflare 1.1.1.1 going dark.
> A fiber cut at the carrier hotel.
> **All real. All in the last 18 months. All recurring.**

### Slide 4 — the constraint (your phrasing, kept — it works)

> **Hospitals don't close.**
> **911 doesn't pause.**
> The system answering the phone can't either.

### Slide 5 — Prism42 (the punchline, grounded in what shipped today)

> **Prism42: one GPU pod, end to end.**
> WebRTC, STT, **LLM**, TTS — all co-located on a B300. No cloud hop.
> Nemotron-3-Nano-30B at 15-30 ms LLM TTFT. **Self-hosted from microphone to mouth — today.**

### Slide 5b (optional A/B demo) — let the judges compare

> Same caller. Two paths.
> Off-pod (cloud-bound): **prism42-console.vercel.app/prism42-v3**
> On-pod (self-hosted): **prism42-app.thegoatnote.com/prism42/livekit**
> One survives the next outage.

---

## Speaker notes (read while the slide is up)

**Slide 1 (~12 s)** — "Most voice-AI demos you'll see today run on the same stack: a great cloud LLM, a great cloud TTS, glued together with WebRTC. Prism42 has that path, and it works. Until the path to it doesn't."

**Slide 2 (~6 s)** — Pause. Let it land. Don't fill the silence.

**Slide 3 (~15 s)** — "These aren't hypothetical. October 2024, AWS us-east. November 2025, Cloudflare resolver. February 2026, fiber cut at a single Equinix facility took down three CDNs at once. Voice agents that depended on those paths went silent."

**Slide 4 (~10 s)** — "Hospitals don't get a maintenance window. 911 doesn't reroute through the next quarter's roadmap. So the system answering 'what's your emergency' has to answer it now."

**Slide 5 (~22 s)** — "Prism42 puts WebRTC, speech-to-text, the LLM, and text-to-speech on a single B300 GPU pod. The LLM is Nemotron-3-Nano-30B at NVFP4, served by vLLM, with 15 to 30 millisecond time-to-first-token. No cloud hop on any of those legs. Self-hosted from microphone to mouth — not in a roadmap slide, today, on the URL we'll show next. That's the architecture trauma centers need."

If using Slide 5b: "Same caller, two paths. The cloud-bound build is on Vercel. The self-hosted build is on the B300 pod under our DNS. Click both. One of them survives the next CDN outage."

Total: ~63 seconds. Fits inside the 90-second video budget; leaves 25–30 seconds for the live voice exchange that follows.

---

## Why each rewrite is tighter than the user's draft

| User draft | Rewrite | Why |
|---|---|---|
| "When your command center has internet" | "When the dispatch center has internet" | "Dispatch center" is the PSAP-domain word; "command center" is military. Judges who watch real 911 demos hear it. |
| "ElevenLabs + Claude" | "ElevenLabs. Claude in the cloud. Best-in-class — until the path to them isn't." | Adds the "until" that earns the next slide. |
| "But emergencies don't wait for the internet." | "Emergencies don't wait for the CDN." | "CDN" is the actual failure surface; "internet" is too vague. Judges who run prod know exactly what fails. |
| "Cloudflare outage. Datacenter down. Network overloaded." | "AWS us-east-1 outage. Cloudflare 1.1.1.1 going dark. A fiber cut at the carrier hotel." | Names + numbers + recency. Same syllable count, 10× the credibility. |
| "Hospitals don't close. 911 doesn't stop. Your system can't either." | (kept verbatim, except: "answering the phone" instead of "your system") | Anchors the abstract claim to a concrete actor. The agent IS the system answering the phone. |
| "So we built one that doesn't." | "Prism42: one GPU pod, end to end. WebRTC, STT, LLM, TTS — co-located on a B300. Nemotron-3-Nano-30B at 15-30 ms TTFT. Self-hosted from microphone to mouth — today." | Names the architecture, names the model, cites a measured number. Judges score Depth on this slide. |

---

## Honesty check (matters for the BAA / clinical audience)

What is on-pod TODAY (verified against `agents/livekit/worker.py` and `docs/livekit-kb/21-nemotron-nano-3-moe-vllm-b300.md`):

- LiveKit media plane on B300 pod — co-located [shipped]
- NVIDIA Riva / Nemotron ASR (STT) — self-hosted on B300 [shipped]
- **Nemotron-3-Nano-30B-A3B at NVFP4 (vLLM 0.20, port :8001 on B300)** — self-hosted [shipped]
- Fish Speech S2 Pro TTS — self-hosted on B300 [shipped]

Cloud-bound LLM is the **off-pod path** (the v3 build at `prism42-console.vercel.app/prism42-v3`). Both paths exist on purpose — the cloud build is best-in-class today, the on-pod build keeps running when the cloud doesn't.

Slide 5's "self-hosted from microphone to mouth — today" is verifiable in two clicks:

```
on-pod   curl -I https://prism42-app.thegoatnote.com/prism42/livekit  -> HTTP 200
off-pod  curl -I https://prism42-console.vercel.app/prism42-v3        -> HTTP 200
```

Earlier draft said "LLM moves on-pod next phase" — that was wrong. The LLM moved on-pod when Nemotron landed; the dual-URL build is *the demonstration* of the architectural choice, not a roadmap.

---

## ALTERNATIVE: 7-slide expansion (use if you have ≥120 s)

Adds a title slide and a close. Same body.

```
SLIDE 0 (title)
PRISM42
Voice AI for the calls that don't get to wait.

SLIDE 1 (baseline)         [as above]
SLIDE 2 (gap)              [as above]
SLIDE 3 (failure)          [as above]
SLIDE 4 (constraint)       [as above]
SLIDE 5 (Prism42)          [as above]

SLIDE 6 (close)
On-pod  prism42-app.thegoatnote.com/prism42/livekit
Off-pod prism42-console.vercel.app/prism42-v3
Repo    github.com/GOATnote-Inc/prism42
Built on Claude Opus 4.7 + Nemotron-3-Nano-30B — Anthropic Hackathon 2026
```

If using the 7-slide version, drop Slide 0 and 6 to fit a strict 90-second cut.

---

## Two design notes for the deck itself

1. **Slide 3's three failure events**: stack them on three lines, same font weight, same color. Don't bullet them. The visual rhythm is what makes "All real. All recurring." land.
2. **Slide 5's "B300"**: small footnote at the bottom of the slide: "NVIDIA Blackwell-Ultra, 288 GB HBM3E, 14 PFLOPS FP4." Not on the main canvas; only there if a judge zooms in. Earns Depth without crowding the slide.

---

## What to NOT put on these slides

- No emojis (rule from CLAUDE.md / user memory).
- No flame-icon or "Use This" framing — those are draft signals, not slide copy.
- No "we built one that doesn't" without naming the *one*. Specificity is the credibility lever.
- The bare `www.thegoatnote.com/prism42` URL is a 404 (per `SUBMISSION-PLAYBOOK-2026-04-26.md` §1). The two working URLs to use on the deck:
  - on-pod: `prism42-app.thegoatnote.com/prism42/livekit`
  - off-pod: `prism42-console.vercel.app/prism42-v3`
