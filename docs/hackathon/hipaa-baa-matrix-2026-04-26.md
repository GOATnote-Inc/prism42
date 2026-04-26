---
title: Prism42 — HIPAA / BAA Matrix and Production-Compliance Roadmap
date: 2026-04-26
audience: Hackathon judges (lay) + clinically serious customer CTO (legal-fluent)
status: Demo-day audit. The repo is a public 911/PSAP simulation. No real PHI flows today. This document is the credible path from demo posture to a HIPAA-defensible production deployment.
authors: Brandon Dent, MD (GOATnote Inc.) + GOATnote HIPAA/BAA Auditor agent
license: MIT (this document); product compliance posture is informational, not legal advice.
---

# Prism42 — HIPAA / BAA Matrix and Production-Compliance Roadmap

## How to read this document

Prism42 is a **public demo** of an Opus-4.7-driven 911/PSAP voice console.
It runs against synthetic dispatch dialogue and the GEDP v0.1 protocol (MIT,
not IAED-licensed). It is not currently a HIPAA Covered Entity, and it is
not currently a Business Associate. The voice traffic in the demo is
synthetic.

Two paths exist in the codebase right now:

- **Path A (target production path)** — LiveKit Cloud media plane with a
  LiveKit-agents 1.5.6 Python worker on a self-hosted Brev B300 GPU pod,
  Caddy auto-TLS at `livekit.thegoatnote.com`, Cartesia Sonic-3 TTS,
  Deepgram Nova-3 STT, Claude Opus 4.7 LLM (Phase 3a) graduating to a
  vLLM-served Llama-70B on the same B300 (Phase 3b).
- **Path B (fallback)** — ElevenLabs Conversational AI front end, served
  via Vercel.

This matrix is the audit a hospital CTO would run before letting either
path touch one byte of PHI. It is also the talk-track the demo video
opens with so judges and clinicians know exactly what they are watching.

---

## 1. Demo-day disclaimer (the 30-second statement)

**Read this verbatim at the top of the demo video and pin it in the
hackathon submission description. No edits. No softening.**

> Prism42 is a public demo of a 911/PSAP voice agent. Every call you see
> in this video is synthetic dialogue. No real Protected Health
> Information has touched this stack, and no real patient data has been
> transmitted, stored, or reasoned over by any of the AI components. The
> dispatch protocol is GOATnote Emergency Dispatch Protocol v0.1 — our
> own MIT-licensed protocol, grounded in AHA BLS 2025 and NHTSA EMS
> Scope of Practice, with no IAED-licensed material. Before this stack
> handles real PHI, every vendor in the pipeline — Anthropic, LiveKit,
> Cartesia, Deepgram, the GPU compute provider — must have an executed
> Business Associate Agreement on a HIPAA-eligible tier, the encryption
> and audit-logging controls in our 90-day roadmap must be in place,
> and a board-certified physician must sign off on the deployment. The
> roadmap that gets us there is published in this repo at
> `docs/hackathon/hipaa-baa-matrix-2026-04-26.md`. Today's demo is a
> capability proof, not a production system. We are showing you what
> the agent can do; we are not yet asking you to trust it with patient
> data.

That is 220 words, ~25 seconds at unhurried pace, ~30 seconds with a
deliberate pause before the URL. Pin it.

---

## 2. Vendor-by-vendor BAA matrix

Two tables — Path A first, then Path B — followed by infrastructure and
out-of-band vendors that touch both paths.

### 2a. Path A — LiveKit + B300 self-hosted (target production path)

| Vendor | BAA available? | Required tier / cost | BAA-request URL or contact | PHI it would touch in production | Demo-day mitigation |
|---|---|---|---|---|---|
| Anthropic (Claude API + Managed Agents) | Yes — HIPAA-ready offering | Sales-assisted Enterprise plan only (NOT Self-serve, NOT Pro / Max / Team / Free; Console / Workbench excluded) | `https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers` and `https://support.claude.com/en/articles/13296973-hipaa-ready-enterprise-plans` — both routes lead to Anthropic sales | LLM input: full STT transcript (verbatim caller utterances incl. names, address, complaint) + agent system prompt. LLM output: dispatcher script + structured determinant code. | Synthetic dialogue only. Opus 4.7 is called via the existing developer-tier API key in `.env`. No real-PHI ingress. |
| LiveKit (Cloud media plane + WebRTC SFU) | Yes — explicit "HIPAA Eligible Products and Services" page | Contact LiveKit; "HIPAA Eligible Services" must be enabled on the workspace; contractual uplift but no published list price (sales-quoted) | `https://livekit.io/legal/hipaa` (HIPAA eligible products page) and `https://livekit.io/security` (security overview) | Real-time audio packets routed through LiveKit Cloud SFU; signaling metadata; turn-detection inference if cloud-hosted. | Demo runs through LiveKit Cloud against a synthetic-caller test endpoint. End-to-end encryption available via `livekit-server-sdk` E2EE primitives even in non-PHI mode. |
| Cartesia (Sonic-3 TTS) | Yes — Sonic is enterprise-grade with SOC 2 Type II + HIPAA + PCI; signs BAAs with a healthcare-targeted offering | Enterprise tier (sales-quoted); on-prem / on-device deploy option available for stricter PHI residency | `https://cartesia.ai/industries/healthcare` (healthcare positioning + BAA contact) | TTS input: dispatcher script text (already redacted relative to caller PII, but may contain caller name + address + complaint). TTS output: audio bytes streamed back to caller. | Demo uses Cartesia Sonic-3 against synthetic dispatcher scripts. No PHI text reaches Cartesia in the hackathon build. |
| Deepgram (Nova-3 STT) | Yes — explicit BAA for Enterprise customers handling ePHI | Enterprise tier (sales-quoted); self-hosted / VPC deploy option available | `https://deepgram.com/data-security` and the BAA-request flow at `https://developers.deepgram.com/trust-security/data-privacy-compliance` (sales contact) | STT input: caller audio (raw PHI). STT output: transcript text (PHI). PHI redaction primitives available API-side (phone, DOB, account creds). | Demo uses Deepgram Nova-3 against synthetic-caller TTS audio. Transcript content is GEDP-fixture, not PHI. |
| Brev / NVIDIA (B300 self-hosted GPU compute) | **Unclear — verify before production.** Brev is an NVIDIA-owned AI / ML compute platform; NVIDIA's published HIPAA posture covers "confidential computing on H100" patterns, but no Brev-specific BAA URL is published as of 2026-04-26. The B300 pod is "self-hosted" only in the sense that Prism42 controls the OS and weights; the underlying hardware is rented from Brev. | Sales/legal route through `enterprise@nvidia.com` or the Brev contact form; assume Enterprise contract pricing at minimum | Brev contact: `https://developer.nvidia.com/brev`. NVIDIA enterprise / privacy: `https://www.nvidia.com/en-us/about-nvidia/privacy-policy/`. **Verify BAA availability with NVIDIA legal before any PHI workload.** | At the OS / VRAM layer: STT transcripts (PHI), Opus reasoning traces (PHI), TTS scripts (PHI), and (Phase 3b) vLLM model activations over PHI. | Pod runs the demo against synthetic dialogue only. No PHI reaches the pod. SSH access controlled via `~/.brev/ssh_config` with key-based auth. |

### 2b. Path B — ElevenLabs + Vercel fallback

| Vendor | BAA available? | Required tier / cost | BAA-request URL or contact | PHI it would touch in production | Demo-day mitigation |
|---|---|---|---|---|---|
| ElevenLabs (Conversational AI: full STT + TTS + LLM-routing path) | Yes — only on Enterprise tier, only with Zero Retention Mode engaged | Enterprise tier (sales-quoted); pricing not published; required to enable PII redaction + storage prevention as part of the HIPAA-eligible config | `https://elevenlabs.io/enterprise` (enterprise sales) and `https://elevenlabs.io/docs/conversational-ai/legal/hipaa` (HIPAA documentation page) | Caller audio stream (PHI) + STT transcript (PHI) + LLM routing input/output (PHI) + TTS output stream. ElevenLabs's HIPAA mode also restricts which downstream LLM providers can be invoked to those with whom EL has its own BAA in place. | Demo uses ElevenLabs Conversational AI against synthetic dialogue. Free / developer tier is in use; this tier is **not** HIPAA-eligible regardless of Zero Retention Mode. |
| Vercel (serverless front-end host for `/prism42` ElevenLabs path) | Yes — both Pro (self-serve via dashboard) and Enterprise tiers can sign BAAs | Pro tier (self-serve BAA) or Enterprise (sales-quoted); BAA covers Vercel's global infrastructure | `https://vercel.com/legal/baa` (BAA self-serve / contact) and `https://vercel.com/blog/vercel-supports-hipaa-compliance` | Static + serverless function logs, request/response payloads, edge cache contents — could include PHI in URL params or POST bodies if not scrubbed at the application layer. | Demo serves only the ElevenLabs front-end shell on Vercel; no PHI passes through the Vercel edge in synthetic-call mode. Move to Pro+BAA before any pilot traffic. |

### 2c. Infrastructure / out-of-band vendors (touch both paths or neither)

| Vendor | BAA available? | Required tier / cost | BAA-request URL or contact | PHI it would touch in production | Demo-day mitigation |
|---|---|---|---|---|---|
| GoDaddy (DNS registrar for `thegoatnote.com`) | Yes — domain-services BAA available; **not** for hosting (GoDaddy explicitly will not sign a BAA covering web hosting) | Standard registrar pricing; BAA signed under GoDaddy's published HIPAA Business Associate Agreement template | `https://www.godaddy.com/legal/agreements/hipaa-business-associate-agreement` | DNS does not transmit PHI in a HIPAA-cognizable way (it carries hostnames, not call content). Including for completeness; no PHI flow expected. | Use GoDaddy only as registrar / DNS authority. Do not move email or hosting to GoDaddy. |
| Cloudflare (TURN / network edge — referenced in `docs/livekit-architecture.md` for relay scenarios) | Yes — Enterprise-only, with a non-negotiable BAA template; **not all Cloudflare products are in scope** (Workers and D1 not listed; CDN, WAF, Access, Zero Trust, Magic Transit are typically covered) | Enterprise tier with a minimum-spend threshold; sales-quoted | `https://www.cloudflare.com/trust-hub/us-privacy-compliance/` and `enterprise@cloudflare.com` | If used as TURN relay: encrypted real-time media (PHI) transits Cloudflare's edge; if used as application proxy: HTTP request/response (PHI). | Cloudflare is currently only referenced as a potential TURN fallback. Default LiveKit Cloud TURN is preferred until Cloudflare-Enterprise + scoped BAA is signed. |
| GitHub (public source repo `GOATnote-Inc/prism42`) | Yes — GitHub Enterprise Cloud signs BAAs for Enterprise customers; public repos are **not** appropriate for any PHI regardless of BAA | Enterprise Cloud tier (sales-quoted); BAA covers Enterprise Cloud and Enterprise Server. **Does NOT cover public repositories.** | Search `GitHub Enterprise Cloud BAA` and contact `https://github.com/contact` enterprise sales. | Source code only. PHI must NEVER appear in this repo (or any GitHub repo) — code, fixtures, logs, screenshots, recordings included. | The repo is intentionally public. Synthetic fixtures only under `corpus/`. `.gitignore` excludes `.env` + `findings/private/`. CI's `scripts/check_pipeline_invariants.py` enforces no-secret patterns. |

### 2d. Summary of "is there even a BAA path?"

| Vendor | Will sign a BAA on a tier we can plausibly afford in 90 days? |
|---|---|
| Anthropic | Yes — sales-Enterprise; budget unknown but feasible for a clinical pilot |
| LiveKit | Yes |
| Cartesia | Yes |
| Deepgram | Yes |
| Brev / NVIDIA | **Unclear, must verify before any production claim** |
| ElevenLabs | Yes — Enterprise + Zero Retention Mode |
| Vercel | Yes — Pro tier self-serve |
| GoDaddy | Yes (DNS-only, irrelevant for PHI mechanically) |
| Cloudflare | Yes — Enterprise minimum-spend |
| GitHub | Yes for Enterprise Cloud — but repo stays public; no PHI ever |

The Brev / NVIDIA row is the hard one. Path A's HIPAA story is **only as
good as that BAA**, and that BAA's existence is currently unverified. The
roadmap below names this as the Day-Zero blocker.

---

## 3. HIPAA Security Rule mapping

The HIPAA Security Rule organizes safeguards in three buckets. Below is
where Prism42 currently lives, what production needs, and the gap.

| Safeguard category | Demo posture (today) | Production needs | Gap delta |
|---|---|---|---|
| **Administrative — workforce policies** | Solo-founder repo. No formal HIPAA training for "the workforce" because the workforce is one person handling synthetic data. Brandon Dent, MD has clinical training; no formal Security Officer designation. | Designated HIPAA Security Officer (named role, even if same person), workforce HIPAA training documented (annual), sanction policy for violations, BAAs with all sub-contractors enumerated above. | Need formal Security Officer designation, training log, sanction policy doc. ~1 week with templates. |
| **Administrative — risk analysis** | `docs/threat-model.md` exists and names dual-use risk; `docs/clinical-handling.md` defines disclosure routing for clinical findings. No formal HIPAA risk analysis. | NIST 800-30-style risk analysis covering each PHI flow: caller audio → LiveKit → Deepgram → Anthropic → Cartesia → caller. Documented review of administrative, physical, technical safeguards per 164.308. | Convert `docs/threat-model.md` into a HIPAA-aligned risk analysis with §164.308(a)(1)(ii)(A) structure. ~2 weeks. |
| **Administrative — incident response** | No formal incident response plan. The repo's `docs/threat-model.md` §incident response names a single email address (`b@thegoatnote.com`) with a 48-hour SLA. | Documented breach-notification procedure per §164.410: identification, containment, eradication, recovery, lessons learned. 60-day breach-notification timeline to affected individuals + HHS. Retention of incident logs ≥6 years. | Stand up a one-page `docs/incident-response.md` keyed to §164.410 + retention bucket. ~3 days. |
| **Physical** | Brev B300 pod runs in NVIDIA / Brev's data center; physical safeguards inherited from that data center's compliance posture (which itself depends on the Brev / NVIDIA BAA). Local development laptop is solo-physician's MacBook. | Physical safeguards documented at every tier where PHI lives at rest or in transit: data center (BAA inherits), workstation (FileVault required, screen-lock, no PHI to laptop), removable media (none). Facility access logs. | Document inheritance from each vendor's SOC 2 Type II; lock down dev workstation policy. ~1 week. |
| **Technical — access control** | Repo is public. Vault is in `.env` (gitignored, never read). SSH access to Brev pod is key-based. Application-layer access control is "demo can be hit by anyone." | RBAC at the agent layer: only authorized PSAP operators can initiate sessions; per-session audit identifier; auto-logoff; emergency-access procedure. | Major build. Authentication + session management + RBAC layer. ~3-4 weeks. |
| **Technical — audit controls** | LiveKit-agents emits structured logs to stdout / file. Anthropic Managed Agents emits session events. No unified audit trail. No redaction layer. | Tamper-evident audit log per §164.312(b): every PHI access (transcript read, LLM input, LLM output, TTS render) logged with user-id + timestamp + action + accessed-record. Logs encrypted at rest, retained ≥6 years, queryable. | New subsystem: structured audit emission from LiveKit worker + agent boundary. ~2-3 weeks. |
| **Technical — integrity** | Schema-validated artifacts (`scripts/validate_artifacts.py`); SHA-pinned simple-evals vendoring. No content-integrity check on real-time audio. | Cryptographic integrity for stored transcripts + reasoning traces (HMAC or signed manifest). Detect any post-hoc modification to a call record. | Add an HMAC-signed audit-record format. ~1 week with `cryptography` lib. |
| **Technical — transmission security** | LiveKit Cloud signaling is TLS 1.3 by default. Deepgram + Cartesia + Anthropic are HTTPS by default. Caddy auto-TLS at `livekit.thegoatnote.com`. WebRTC media is SRTP/DTLS. No end-to-end encryption above the SFU layer. | TLS 1.3 everywhere (verified, not assumed). LiveKit E2EE for the media plane (already supported by `livekit-server-sdk`). PHI-bearing API calls over the agent-to-LLM hop must use ZDR (Anthropic) or in-VPC Deepgram self-hosted. | Enable LiveKit E2EE. Verify Anthropic ZDR is on after BAA. Verify Caddy TLS config in production. ~1 week. |
| **Technical — encryption at rest** | None of the components currently persist PHI at rest. Local repo holds synthetic fixtures only. No database. | Encrypt: (a) recordings if any are kept, (b) STT transcript persistence, (c) Opus reasoning traces, (d) vLLM model weights in Phase 3b (Llama 70B), (e) audit logs. AES-256 at minimum. KMS-backed keys. | Architect persistence layer with encryption-by-default before first PHI ingestion. ~2 weeks. |

---

## 4. The B300 self-hosted advantage (one-page argument)

**Why Path A is the more HIPAA-tractable production path than Path B.**

A HIPAA program's hardest job is bounding the surface area where PHI
lives. Every additional Business Associate is one more contract to
maintain, one more breach-notification chain to monitor, and one more
vendor whose internal controls you have to take on faith. The prudent
default is fewer vendors, fewer hops, and physical control of the inference layer.

Path B (ElevenLabs Conversational AI) routes the full audio + transcript
+ LLM-reasoning + TTS-synthesis loop through a single SaaS vendor whose
HIPAA mode (Zero Retention Mode + Enterprise tier + BAA) is a real product
but introduces three structural problems for a clinically serious customer:

1. **Vendor concentration risk on PHI.** A single SaaS provider sees the
   entire call. Even with Zero Retention Mode, the encrypted-in-flight
   data still flows through ElevenLabs's infrastructure, and the LLM
   provider list is constrained to those with whom EL has its own BAA.
   The customer cannot independently verify "this audio was never
   logged" — they have to trust the vendor's attestation.
2. **No air-gap option for the LLM reasoning step.** ElevenLabs's HIPAA
   mode picks the LLM for you (from EL's BAA-covered set). If the
   customer's compliance posture requires an on-prem LLM, Path B cannot
   honor that.
3. **No physical-control option for the audio path.** The audio enters
   ElevenLabs's media plane the moment the caller connects. A clinical
   customer cannot put this audio in a VPC they own.

Path A (LiveKit + B300 self-hosted) inverts each of those:

1. **Each component has a scoped BAA.** Cartesia for TTS, Deepgram for
   STT, Anthropic for LLM (Phase 3a) or **no third-party LLM at all** in
   Phase 3b when vLLM serves Llama-70B locally on the B300. The vendor
   set is small and named.
2. **Phase 3b removes the cloud LLM entirely.** Once vLLM-served
   Llama-70B is the production LLM, the reasoning step never leaves the
   B300 pod the customer (or GOATnote on the customer's behalf) controls.
   Anthropic's BAA is no longer load-bearing for the reasoning hop. This
   is a structural advantage that a SaaS-bundled path cannot replicate.
3. **The audio path is brokered, not owned, by LiveKit.** LiveKit's
   media plane carries SRTP/DTLS-encrypted audio between caller and
   pod; with E2EE enabled, even LiveKit cannot decrypt the stream. The
   pod is in the customer's compliance boundary (or in NVIDIA's, with
   a verified BAA).

For a clinically serious customer — a regional EMS authority or a
hospital that runs its own dispatch — Path A reads as "you can put a
boundary around this and we will document where the boundary is." Path
B reads as "you trust ElevenLabs end-to-end, and that is the BAA you
sign." Path A is harder to build (and we are honest about the Brev
verification gap), but it is the one that survives a security review
from a clinical CIO whose first question is "where does the audio
physically live?"

That answer is the single most important durable lift Prism42 can offer
over a SaaS-bundled competitor.

---

## 5. Production HIPAA-compliance roadmap (90-day)

Start: 2026-04-29 (Wednesday after hackathon). End: 2026-07-28
(Monday). Each row is a concrete deliverable. Owner is "B" for
Brandon Dent, MD or "B+counsel" where outside legal review is required.

### Week 1 (2026-04-29 → 2026-05-05) — Verify the unverified, sign the easy wins

| Date | Owner | Deliverable |
|---|---|---|
| 2026-04-29 | B+counsel | **Day-Zero unblocker:** Email NVIDIA / Brev legal asking explicitly: "Is the Brev GPU-compute service available under a HIPAA Business Associate Agreement, on what tier, and does that BAA cover the customer-controlled VRAM-resident workload model?" Capture answer in `docs/hackathon/baa-status-tracker.md`. If "no", begin parallel outreach to AWS-HIPAA / Azure-HIPAA / GCP-HIPAA GPU offerings as fallback compute hosts. |
| 2026-04-30 | B | Sign Vercel Pro BAA (self-serve via dashboard) — covers the ElevenLabs `/prism42` path until decommissioned. |
| 2026-05-01 | B | Open BAA-request tickets with: Anthropic (HIPAA-ready Enterprise inquiry), LiveKit (HIPAA Eligible Services activation), Cartesia (healthcare BAA), Deepgram (Enterprise BAA + ePHI route). Each request links to this matrix as the customer-side context document. |
| 2026-05-02 | B | Designate HIPAA Security Officer (Brandon Dent, MD interim) and HIPAA Privacy Officer (same, until org adds counsel). Document in `docs/hackathon/hipaa-officers.md`. |
| 2026-05-04 | B | Stand up `docs/incident-response.md` keyed to §164.410. 60-day breach-notification window, retention 6 years, single email intake `b@thegoatnote.com` until org expands. |
| 2026-05-05 | B | Convert `docs/threat-model.md` into `docs/hipaa-risk-analysis.md` with NIST 800-30 + §164.308(a)(1)(ii)(A) structure. |

### Weeks 2-4 (2026-05-06 → 2026-05-26) — Encryption, audit logging, minimum-necessary scoping

| Window | Owner | Deliverable |
|---|---|---|
| 2026-05-06 → 2026-05-12 | B | **Encryption-at-rest configuration.** Decide which artifacts persist. Today the answer is "none beyond `findings/`"; production must explicitly choose: (a) keep recordings or not, (b) keep STT transcripts or not, (c) keep Opus reasoning traces or not, (d) audit log retention 6+ years. Each yes triggers AES-256 at rest, KMS-backed keys, documented key-rotation cadence (90 days). Inventory in `docs/hipaa-encryption-inventory.md`. |
| 2026-05-13 → 2026-05-19 | B | **Encryption in transit verification.** Document TLS 1.3 on every leg: caller→LiveKit (DTLS-SRTP), LiveKit→agent worker (TLS), worker→Deepgram (HTTPS), worker→Anthropic (HTTPS, ZDR-on once BAA signed), worker→Cartesia (HTTPS), Cartesia→caller (TLS), Caddy at `livekit.thegoatnote.com` (LE-issued, auto-rotated). Enable LiveKit E2EE in the worker config. |
| 2026-05-20 → 2026-05-26 | B | **Audit logging subsystem v1.** New module `prism42/audit/`: structured log emission per PHI access — STT transcript ingest, LLM input, LLM output, TTS render — fields {session_id, timestamp_utc, actor, action, record_hash}. HMAC-signed. Retention bucket: encrypted append-only store. Smoke test: a synthetic call generates exactly N audit records where N = |STT segments| + 2 |LLM turns| + |TTS turns|. |

### Weeks 5-7 (2026-05-27 → 2026-06-16) — Minimum-necessary scoping + access control

| Window | Owner | Deliverable |
|---|---|---|
| 2026-05-27 → 2026-06-02 | B | **PHI minimum-necessary scoping.** Document which fields each component sees: (a) Deepgram sees raw audio + transcript out; (b) Anthropic Opus sees the redacted transcript only — caller name, full address, DOB, SSN, account numbers stripped or tokenized **before** the LLM hop; (c) Cartesia sees only the dispatcher script, never the raw caller transcript; (d) LiveKit sees SRTP-encrypted media and signaling, not transcript text. Enforce in `prism42/redactor/`. |
| 2026-06-03 → 2026-06-09 | B | **Reasoning-trace boundary.** Opus 4.7's adaptive-thinking traces (when present) may contain reconstructed PHI. Default `display: omitted` for production (already the 4.7 default). Audit any `display: summarized` config flag. Document in `docs/hipaa-reasoning-trace-policy.md`. |
| 2026-06-10 → 2026-06-16 | B | **Application-layer authentication + RBAC.** No anonymous demo traffic in production. Operator login + per-session user-id propagated into the audit log. Auto-logoff after 15 minutes idle. Emergency-access procedure (break-glass) with mandatory post-hoc justification logged. |

### Weeks 8-10 (2026-06-17 → 2026-07-07) — HIPAA training + workforce policies

| Window | Owner | Deliverable |
|---|---|---|
| 2026-06-17 → 2026-06-23 | B | **HIPAA workforce training v1.** Single-page training deck covering: PHI definition, minimum-necessary, breach-reporting obligation, sanctions, role-specific procedures (dispatcher, on-call physician, on-call engineer). Annual refresh cadence. Logged completions in `docs/hipaa-training-log.md` (gitignored — names + dates only). |
| 2026-06-24 → 2026-06-30 | B | **Sanction policy** for HIPAA violations. Even at solo-founder stage, document graduated response (verbal warning → written → termination) per §164.308(a)(1)(ii)(C). |
| 2026-07-01 → 2026-07-07 | B | **BAA portfolio review.** Confirm executed copies of: Anthropic (Enterprise), LiveKit, Cartesia, Deepgram, Brev/NVIDIA (or fallback compute provider), Vercel Pro. File checklist in `docs/hackathon/baa-portfolio.md`. Any "not yet" item triggers production-launch hold. |

### Weeks 11-13 (2026-07-08 → 2026-07-28) — Penetration test + go/no-go

| Window | Owner | Deliverable |
|---|---|---|
| 2026-07-08 → 2026-07-14 | B+vendor | **Third-party penetration test** scoped to: (a) WebRTC media plane (DTLS-SRTP integrity, TURN abuse), (b) agent-worker boundary on B300 (SSH hardening, container escape, vLLM RPC if applicable), (c) Caddy / TLS configuration at `livekit.thegoatnote.com`, (d) audit-log tamper resistance, (e) PHI-redactor bypass attempts. Vendor short-list: Bishop Fox, NCC Group, Trail of Bits. |
| 2026-07-15 → 2026-07-21 | B | **Pen-test remediation pass.** All criticals + highs closed before any PHI-bearing pilot. Mediums tracked with deadlines; lows accepted with justification. |
| 2026-07-22 → 2026-07-28 | B+counsel | **Production go/no-go review.** Checklist: every BAA executed; every encryption row verified; audit logging emits and persists; redactor passes adversarial test set; pen-test criticals closed; physician sign-off (Brandon Dent, MD) on the go-live posture. If any item fails, no PHI ingestion. |

### Out-of-window (post-2026-07-28) — Phase 3b vLLM transition

The 90-day plan ends at "production-go for cloud-LLM Phase 3a posture." The
vLLM-served Llama-70B Phase 3b transition is its own follow-on workstream
because removing Anthropic from the live PHI path materially changes the
BAA portfolio and triggers a re-issued risk analysis. Target window:
2026-07-29 → 2026-09-30.

### Ongoing — security incident response procedure

Independent of the dated rows above, the steady-state IR procedure is:

| Role | Procedure | Retention |
|---|---|---|
| Detection | Audit-log monitor + caller / customer report → email `b@thegoatnote.com` | Indefinite |
| Triage | HIPAA Security Officer (Brandon Dent, MD) within 24h; classify suspected breach severity | 6 years |
| Notification | If breach confirmed: affected individuals within 60 days per §164.404; HHS via OCR portal within 60 days (or annually if <500 individuals) per §164.408; covered-entity customer notified within their contracted SLA (typically 24-48h) | 6 years |
| Containment + eradication | Disable affected sessions / rotate keys / quarantine compromised pod | Logged 6 years |
| Lessons learned | Post-incident review within 30 days; risk-analysis update | 6 years |

---

## 6. What to say to a hospital CTO in 90 seconds

> Today, no — Prism42 is not HIPAA-compliant. It is a public demo with
> synthetic 911 dialogue. We have not signed a single BAA yet because no
> real PHI has touched any component.
>
> We do, however, have a credible path. Each vendor in our pipeline —
> Anthropic for the LLM, LiveKit for the WebRTC media plane, Cartesia
> for TTS, Deepgram for STT, NVIDIA / Brev for the GPU compute — has a
> documented HIPAA-eligible tier and a known BAA-request URL, with the
> Brev row flagged for legal verification before any PHI workload. We
> have a 90-day roadmap that opens BAA negotiations on day one,
> stands up encryption-at-rest, audit logging, and PHI minimum-necessary
> scoping in weeks 2-4, builds workforce training and sanctions policies
> in weeks 8-10, and ends with a third-party penetration test and a
> physician-signed go/no-go review on day 90.
>
> The architectural bet that matters for you specifically is that
> Path A is the production path: LiveKit media plane plus a
> self-hosted GPU pod we control. Phase 3b moves the LLM onto that same
> pod, so the reasoning step never leaves the boundary you can audit.
> Phase 3a uses Anthropic Claude Opus 4.7 under their HIPAA-ready
> Enterprise BAA as a transitional step. That is a structurally
> stronger compliance story than any all-SaaS competitor can offer
> because the audio, transcript, and reasoning all live inside one
> defensible boundary, not three vendors' boundaries.
>
> What we want from you today is twenty minutes to walk through this
> matrix line by line and tell us where your security team's red lines
> are. We will not push code into your environment until every one of
> those lines is honored.

That is 280 words, ~110 seconds at the deliberate pace a CTO meeting
deserves. It is honest about today, specific about tomorrow, and asks
for the input we actually need. Use it verbatim or adapted for the
opening 90 seconds of any clinically serious customer call.

---

## Sources

Primary BAA documentation per vendor (all retrieved 2026-04-26):

- Anthropic — `https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers`
- Anthropic HIPAA-ready Enterprise — `https://support.claude.com/en/articles/13296973-hipaa-ready-enterprise-plans`
- Anthropic Trust Center — `https://trust.anthropic.com`
- ElevenLabs HIPAA — `https://elevenlabs.io/docs/conversational-ai/legal/hipaa`
- ElevenLabs Enterprise — `https://elevenlabs.io/enterprise`
- Cartesia Healthcare — `https://cartesia.ai/industries/healthcare`
- Deepgram Compliance — `https://developers.deepgram.com/trust-security/data-privacy-compliance`
- Deepgram Data Security — `https://deepgram.com/data-security`
- LiveKit HIPAA — `https://livekit.io/legal/hipaa`
- LiveKit Security — `https://livekit.io/security`
- Brev / NVIDIA Developer — `https://developer.nvidia.com/brev` (BAA status unverified, verify with NVIDIA legal)
- NVIDIA Privacy — `https://www.nvidia.com/en-us/about-nvidia/privacy-policy/`
- Vercel HIPAA — `https://vercel.com/legal/baa`
- Vercel HIPAA blog — `https://vercel.com/blog/vercel-supports-hipaa-compliance`
- GoDaddy BAA — `https://www.godaddy.com/legal/agreements/hipaa-business-associate-agreement`
- Cloudflare US Privacy — `https://www.cloudflare.com/trust-hub/us-privacy-compliance/`
- Cloudflare Enterprise contact — `enterprise@cloudflare.com`
- GitHub Enterprise BAA — `https://github.com/contact` (Enterprise sales)

Regulatory references:
- HHS Office for Civil Rights — HIPAA Security Rule (45 CFR §164.302–§164.318)
- HHS OCR — HIPAA Breach Notification Rule (45 CFR §164.400–§164.414)
- NIST SP 800-30 Rev. 1 — Risk Management Guide for Information Technology Systems
- AHA BLS 2025 — referenced via GEDP v0.1 (clinical content, not compliance)

This document is informational. It is not legal advice. Engage HIPAA
counsel before signing any BAA or claiming HIPAA compliance to a
clinical customer.
