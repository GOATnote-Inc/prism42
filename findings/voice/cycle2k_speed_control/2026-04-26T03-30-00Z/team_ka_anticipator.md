# Team K-A — cycle-2k anticipator (read-only)

**Mission:** rank likely failure modes of the three-part cycle-2k composition
(adapter pace-tag wrap + comma-strip + cycle-2f flag OFF) before any code
ships. 15-minute window.

**Mode:** read-only. No code edits. No pod commands. No commits.

**Audit window:** 2026-04-26T03:30Z, ~15 min.

**Inputs verified:** K1 audit (`team_k1_speed_audit.md`), K2 catalog
(`team_k2_preset_catalog.md`), `agents/livekit/fish_speech_tts.py`,
`agents/livekit/orchestrator.py`, `agents/livekit/worker.py`,
`vendor/fish-speech/fish_speech/text/clean.py`,
`vendor/fish-speech/README.md:111-115`,
`findings/b300_bench/cycle2f_prosody/2026-04-25T21-32-45Z/brackets_check.txt`,
`findings/voice/cycle2j_reference_voice/.../audio/{baseline,wav1,wav2}/p{1-5}.wav`.

---

## TL;DR (one paragraph)

Three of the five top failure modes are **already-existing latent bugs** that
the cycle-2k composition will surface (greeting cache divergence,
prompt-template comma-vs-period mismatch, untested-tag audibility). The other
two are **new risks introduced by composition**: tag-vs-comma interaction
in Fish's AR sampler (untested combination), and Nemotron prose-quality
regression from comma deprivation. The single highest-leverage defensive
move is to **A/B the pace-tag in isolation first** (just step 1 of the
three-part change), measure on the existing 5-phrase × 3-condition
baseline, and only layer comma-strip + flag-OFF after the tag is
confirmed silent. Do not ship all three at once.

---

## Top 5 failure modes (ranked by likelihood × blast radius)

### 1. Greeting cache stays at slow pace — turn 1 contradicts turns 2+

**Likelihood:** HIGH (almost certain if no cache invalidation).
**Blast radius:** WIDE (every call's first impression).

**Symptom.** Caller hears the cycle-2i greeting "Nine one one. Where is
your emergency?" rendered at the current 0.5x slow audiobook cadence
(matches K1's P1 measurement: 3.0 sps voiced rate). On turn 2 the
adapter wraps with `[urgent dispatcher pace]` and the LLM reply lands
at a brisker rate. The pace transition between turn 1 and turn 2 is
audible and feels like a different voice — degrading the very NENA-
identity benefit cycle-2i was meant to deliver.

**Root cause.** `worker.py:222-237` synthesizes the greeting in a
**parallel code path** — its own httpx client, its own hard-coded body
dict — that bypasses `fish_speech_tts.py:184-205` entirely. It reads
the same Fish endpoint but never touches the adapter's `_run()`. Adding
a tag wrap at `fish_speech_tts.py:185` therefore has zero effect on the
greeting. Worse, the cached PCM bytes (`_GREETING_PCM_BYTES`,
`worker.py:183`) are warmed at process start (`worker.py:1031`) and
NEVER re-warmed within a process — `_ensure_greeting_cache` returns
True on first non-None check (`worker.py:304`).

**Surgical workaround.** Three options ranked by ship-cost:
(a) cheapest — also wrap `worker.py:222`'s `body["text"]` with the same
prefix the adapter uses, gated on the same env var. Two-line change.
(b) durable — refactor `_warm_greeting_cache_blocking()` to call
`FishSpeechTTS().synthesize()` instead of building its own httpx body.
But that changes `_strip_wav_header()` flow and risks regressing the
cycle-2i `add_to_chat_ctx=False` semantics.
(c) lazy — delete the cached `/tmp/prism42-greeting.wav` on systemd
restart and bump a `GREETING_CACHE_VERSION` env so a stale PCM file is
not re-read across worker restarts (currently `GREETING_AUDIO_PATH`
write at `worker.py:269-270` is archival-only — the cache lives in
process memory, so a worker restart will re-warm with the new tag).

**Source.** `agents/livekit/worker.py:164,210-296,1026-1035,1051-1057`;
`agents/livekit/fish_speech_tts.py:184-205`.

---

### 2. `[urgent dispatcher pace]` renders audibly — phonemes leak into reply

**Likelihood:** MEDIUM-HIGH (untested phrase; outside README short list).
**Blast radius:** WIDE (every turn 2+ reply).

**Symptom.** Caller hears something like "urgent dispatcher pace nine
one one what is your location and emergency" — Fish's AR samples the
opening tokens phonetically because the trained model's tag conditioning
does not recognize the free-form description, treats it as ordinary
text, and the tokenizer maps `[`, `urgent`, ... to phoneme-bearing
tokens. The dispatcher voice opens with literal "urgent dispatcher
pace" before pivoting to the actual reply.

**Root cause.** Fish's only documented text-cleaner is
`vendor/fish-speech/fish_speech/text/clean.py` — verified-by-source: it
does whitespace strip, unicode-quote swap, emoji removal, and
collapse-repeated-commas. **No bracket/tag stripping regex.** Brackets
are passed verbatim to the AR. The model's tag-interpreting behavior is
**emergent from training**, not from a parser. The README short list
(`vendor/fish-speech/README.md:114`) catalogs ~30 *confirmed-by-vendor*
tags: `[pause]`, `[emphasis]`, `[laughing]`, `[short pause]`,
`[whisper]`, `[loud]`, `[low volume]`, `[volume up]`, `[volume down]`,
etc. **`[urgent dispatcher pace]` is not in that list.** The README's
explicit examples of free-form descriptions are
`[whisper in small voice]`, `[professional broadcast tone]`, and
`[pitch up]` — note all three describe acoustic properties, not domain
roles. The cycle-2f bench (`brackets_check.txt`) confirmed `[soft]` and
`[calm soft]` are silent — but `[soft]` IS in the canonical short list,
so that empirical proof does NOT extend to `[urgent dispatcher pace]`.

**Surgical workaround.** Use `[professional broadcast tone]` (verbatim
from README §3.1, line 112) as the first-pass pace tag instead of
`[urgent dispatcher pace]`. README explicitly attests this phrase as a
working example, so the tag-audibility risk drops from MEDIUM-HIGH to
LOW. Run a 5-phrase pilot with this tag against the existing baseline
audio set BEFORE attempting the more aggressive `[urgent dispatcher
pace]` or `[fast]` variants. If `[professional broadcast tone]` works
silently AND moves cadence at all, lock it in; only then sweep
alternates.

**Source.** `vendor/fish-speech/fish_speech/text/clean.py:24-37`;
`vendor/fish-speech/README.md:111-115`;
`findings/b300_bench/cycle2f_prosody/2026-04-25T21-32-45Z/brackets_check.txt:1-21`.

---

### 3. Comma-strip breaks Nemotron Nano-3 dispatcher prose quality

**Likelihood:** MEDIUM.
**Blast radius:** ALL turns (LLM-emitted text quality regresses).

**Symptom.** Dispatcher replies lose natural sentence structure: "Help
is on the way Stay on the line with me" instead of "Help is on the way.
Stay on the line with me." The Nemotron Nano-3 30B-A3B-NVFP4 model
(`worker.py:601`) was trained on standard prose where commas separate
clauses; if the system prompt instructs it to avoid commas, output
quality degrades on multi-clause utterances. Specific failure: the
APCO-protocol verbatim first turn "Nine one one, what is your location
and emergency?" (`orchestrator.py:259,291`) — the model may produce
"Nine one one what is your location and emergency" or split into two
separate replies, neither of which is the verbatim NENA opening.

**Root cause.** Two compounding factors:
(a) The orchestrator system prompt currently states the verbatim opener
WITH a comma at line 259 + line 291. If the comma-fix lives at the
prompt layer, those two lines must be hand-edited to use a period —
but the comma-after-911 is the documented APCO standard ("Nine one
one,"). Splitting into "Nine one one. What is your location and
emergency?" changes prosody from a single rising contour to two
declaratives — perceptually different (the cycle-2i greeting already
uses the period form, see worker.py:164, but the orchestrator prompt
still uses the comma form, which means the prompt-template and the
greeting are already inconsistent — see Failure 5 below).
(b) If the comma-strip lives at the **adapter post-process** layer
(`fish_speech_tts.py` line 185 strips commas from `self._text` before
sending), it works for any LLM but creates a divergence between
`agent_message_received` event payloads (still has commas) and the
audio (has periods). Transcript bus (`worker.py:356-368`) POSTs the
text-with-commas to Vercel; Fish renders the text-without-commas. The
two are out of sync, and audit-log inspection becomes harder.

**Surgical workaround.** Adapter-side regex `re.sub(r",\s*", ". ",
text)` rather than `re.sub(r",", "", text)`. Replacing comma+space
with period+space preserves clause structure for Fish's AR (matches
the empirical finding from K1 §"Hypothesis": Fish pauses on commas
AND on periods, but the period-pause is structurally what we want at
clause boundaries — short declaratives stay at 4.5-5.1 sps per K1
data). This loses zero prose quality from Nemotron's perspective
(still sees commas in its emitted text), and introduces only one
behavioral change: clauses Fish will treat as harder sentence breaks.
Skip the prompt-layer change entirely.

**Source.** `agents/livekit/worker.py:597-605` (Nemotron model id);
`agents/livekit/orchestrator.py:259,291` (verbatim-comma opener);
`agents/livekit/worker.py:164` (greeting period form);
K1 §"Hypothesis" + cadence table.

---

### 4. cycle-2f flag-OFF removes filler tags but LLM may still emit `[soft]` from prompt-context bleed

**Likelihood:** LOW-MEDIUM (depends on whether stage-direction tags ever entered the LLM context).
**Blast radius:** Fillers + occasional dispatcher reply.

**Symptom.** Even with `PRISM42_ENABLE_TTS_PROSODY_TAGS=0`, the
dispatcher LLM occasionally emits `[soft]` or other bracket tags
mid-reply. Cause: if any prior session's filler tagged-text was
ever logged into the chat context (`add_to_chat_ctx=True` on a
filler) OR if the system prompt retained a reference to bracket
syntax, Nemotron Nano-3 may pattern-match and emit them.

**Root cause assessment for prism42 specifically.** Verified-by-source:
the orchestrator system prompt (`orchestrator.py:227-387`) explicitly
prohibits stage directions: line 385 reads `- No stage directions like
"[speaks calmly]". Just the words.` So the system-prompt-pattern path
is ruled out. The fillers (`worker.py:87-93,94-99`) live in
`session.say()` calls (not LLM-generated), which means they don't
enter the LLM ChatContext UNLESS the call site sets
`add_to_chat_ctx=True` — needs verification in worker.py filler-call
sites. The greeting itself sets `add_to_chat_ctx=False`
(`worker.py:1074`), which is the right pattern. **So the bleed-risk
is LOW for the PSAP path as currently architected** — the named
hazard is only that future code or a debug `add_to_chat_ctx=True`
flip would resurrect it.

**Surgical workaround.** No code change required at cycle-2k ship.
Add a watchlist log: K-E should grep
`agent_message_received.content` for `\[[a-z][a-z ]+\]` (any
lowercase-bracket tag). If it appears in any LLM output post-flag-OFF,
fail closed and audit the chat context wiring before continuing.

**Source.** `agents/livekit/orchestrator.py:385`;
`agents/livekit/worker.py:87-99,1067-1075`.

---

### 5. Adapter-level wrap double-stacks if cycle-2f flag accidentally stays ON

**Likelihood:** LOW (requires misconfiguration), but LARGE if it happens during demo.
**Blast radius:** Filler text only — but those are the most common utterances during a demo.

**Symptom.** Filler "Stay with me" already prefixed with `[soft]` from
`_FILLERS_TAGGED` (worker.py:95). If cycle-2f flag stays at `=1` AND
adapter wraps with `[urgent dispatcher pace]`, the wire-text for that
filler becomes `[urgent dispatcher pace] [soft] Stay with me.` — two
brackets in series. Fish's AR has not been tested with stacked tags;
the second bracket may render audibly even though each individually is
silent (interaction effect — empirical priors do not cover this case).

**Root cause.** No mutual-exclusion guard between the two flags.
`worker.py:101` reads `PRISM42_ENABLE_TTS_PROSODY_TAGS`;
`fish_speech_tts.py:185` (proposed cycle-2k wrap) would be unrelated.
A 50-cycle2f-prosody.conf systemd drop-in that sets the env var
would silently coexist with the cycle-2k drop-in.

**Surgical workaround.** At adapter level, BEFORE the wrap, detect
existing leading bracket via `re.match(r'^\s*\[', self._text)`. If
present, skip the wrap (assume LLM/filler already specified prosody).
Three-line guard in `fish_speech_tts.py:_run()`. Alternative: in the
cycle-2k systemd drop-in, explicitly set
`PRISM42_ENABLE_TTS_PROSODY_TAGS=0` so the two flags are forced into
mutual-exclusion at deploy-config layer — single point of policy.

**Source.** `agents/livekit/worker.py:78-105` (cycle-2f wiring);
`agents/livekit/fish_speech_tts.py:184-205` (proposed wrap site).

---

## Bonus risk (not in top 5 but flagged for awareness)

**6. Prompt-template comma vs greeting-text period inconsistency.** The
orchestrator prompt's verbatim first turn (`orchestrator.py:259,291`)
says `Nine one one, what is your location and emergency?` (comma form).
The cycle-2i cached greeting (`worker.py:164`) says `Nine one one.
Where is your emergency?` (period form, different question phrasing).
These are pre-existing — they're not introduced by cycle-2k — but
cycle-2k's comma-strip step will accidentally surface this divergence
as a behavioral question: does cycle-2k apply to the dispatcher LLM's
verbatim opener (which the system prompt's "FIRST TURN — VERBATIM"
clause requires)? If yes, the LLM will produce `Nine one one. what is
your location and emergency?` for turn 1 — but the cached greeting
already plays first (cycle-2i flag), so what the caller actually hears
is greeting + then-LLM-reply for turn 2. Net effect: minor; flag for
K-E to verify the order on a real call. **Source:**
`orchestrator.py:255-264`; `worker.py:152-164,1067-1080`.

---

## Defensive watchlist (for K-E monitoring)

| Failure | Log line / metric K-E watches | Threshold for fail-fast |
|---|---|---|
| 1 (greeting cache stale) | `greeting.911.cache_warmed` body field `text=` | If text contains `[` → wrap reached greeting OK. If absent across worker restarts → cache stale, raise alert |
| 1 | `fishspeech.t0` `text_len=` for first turn vs subsequent turns | First-turn audio duration ratio (turn 1 / turn 2) > 1.5x → pace divergence between greeting and live replies |
| 2 (tag audible) | `fishspeech.t_first_byte` `ms_since_post=` | Spike >50ms over baseline → AR took longer (extra phoneme tokens) — audible-tag suspect |
| 2 | first 200 ms peak amplitude in emitted PCM (instrumented at adapter `output_emitter.push`) | Peak amplitude in first 200ms exceeds baseline range [22473, 26068] from cycle-2f bench → phonemes from tag rendering |
| 2 | `fishspeech.done` `audio_duration_ms` divided by word count of `self._text` (post-wrap) | Words-per-second voiced < 4.0 OR > 7.0 → off baseline range, audit |
| 3 (comma-strip prose) | `agent_message_received.content` regex `[a-z]\s+[A-Z]` | Adjacent lowercase-then-capital with no period → comma-strip stripped a sentence boundary; LLM compensating poorly |
| 3 | Nemotron output token count (`fishspeech.t0` text_len) per turn | Length distribution shift from baseline by >20% → prompt-or-strip-induced regression |
| 4 (LLM emits stage tag) | `agent_message_received.content` regex `\[[a-z][a-z ]+\]` | ANY match → fail; cycle-2f flag-OFF leaked through |
| 5 (double-wrap) | adapter log new field `text_pre_wrap` vs `text_post_wrap` | If `text_pre_wrap.startswith("[")` AND `text_post_wrap` has TWO `[` → double-wrap; revert |
| 5 | `worker.cycle2f_prosody_init` field `cycle2f_prosody=` at startup | If `enabled` while cycle-2k drop-in active → mutual-exclusion violation, fail closed |
| 6 (comma/period inconsistency) | `greeting.911.played` `text=` vs `agent_message_received.content` for turn 1 | Both present in same session → expected (greeting plays first); if greeting absent + LLM speaks `Nine one one. what...` → period leaked into LLM verbatim opener |

---

## Recommended de-risking sequence (for the integrator)

Do NOT ship all three steps as one change. Sequence:

1. **Step 1 alone (adapter wrap with `[professional broadcast tone]`,
   not `[urgent dispatcher pace]`).** Ship to the existing 5-phrase
   bench (re-run K1's measurement script). If pace shifts AND tag is
   silent (peak amplitude in baseline range) → continue. If tag
   audibly renders → fail back, try `[fast]`, then `[brisk]`, then
   `[broadcast pace]`. Apply the greeting-cache fix (Failure #1
   workaround a) at the same time so turn 1 and turn 2 are consistent.
2. **Step 2 (comma-to-period).** Adapter-side regex
   `re.sub(r",\s*", ". ", text)` (NOT comma-strip). Re-run bench.
   Compare per-phrase wpm/sps to step-1 baseline. Expect cumulative
   gain on P1-style multi-clause utterances; null on others.
3. **Step 3 (cycle-2f flag-OFF).** Only if step 1+2 land cleanly AND
   the LLM does not show stage-tag bleed in step 2 audit. The flag is
   already OFF by default (`worker.py:101`), so this step is a no-op
   in the default config — only relevant if a 50-cycle2f-prosody.conf
   drop-in was installed in production.

Each step is independently revertible; collapsing them into one
change loses the empirical signal about which lever did what.

---

## Sources

- `~/prism42/agents/livekit/fish_speech_tts.py:184-205`
  — adapter request body construction site (proposed cycle-2k wrap target).
- `~/prism42/agents/livekit/worker.py:78-111` — cycle-2f
  flag wiring + FILLERS variant selector.
- `~/prism42/agents/livekit/worker.py:152-296` — cycle-2i
  greeting-cache parallel synthesis path.
- `~/prism42/agents/livekit/worker.py:1026-1095` —
  greeting dispatch order vs session.start.
- `~/prism42/agents/livekit/orchestrator.py:227-387` —
  FAST_DISPATCHER_SYSTEM_PROMPT (no `[calm soft]` direction; stage
  directions explicitly prohibited at line 385).
- `~/prism42/vendor/fish-speech/fish_speech/text/clean.py:24-37`
  — only documented text-cleaner; no tag-stripping logic.
- `~/prism42/vendor/fish-speech/README.md:111-115` —
  S2-Pro tag system documentation; canonical 30-tag short list +
  three named free-form examples (`[whisper in small voice]`,
  `[professional broadcast tone]`, `[pitch up]`).
- `~/prism42/findings/b300_bench/cycle2f_prosody/2026-04-25T21-32-45Z/brackets_check.txt`
  — empirical proof that `[soft]` and `[calm soft]` render silently
  on the live pod; does NOT extend to `[urgent dispatcher pace]` or
  any out-of-canonical-list tag.
- `~/prism42/findings/voice/cycle2k_speed_control/2026-04-26T031403Z/team_k1_speed_audit.md`
  — K1 audit; cadence table per-phrase.
- `~/prism42/findings/voice/cycle2k_speed_control/2026-04-26T03-15-00Z/team_k2_preset_catalog.md`
  — K2 catalog; current `psap` preset is the only on-disk reference.

---

Co-Authored-By: Claude Opus 4.7 (do not commit; integrator commits.)
