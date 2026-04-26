# Cycle-2P2 Fix candidates — ranked, not applied

Author: Team P · Date: 2026-04-26 · Status: research-only, no code changes

The integrator should pick from this menu. Each fix lists file:line, risk
level, verification, and rollback. **None has been applied.**

---

## A. FSM intent-classification fixes (top 3)

### A1. Cardiac short-circuit gate — require third-party AND breathing-quality cue

**Risk: low** · **Highest leverage** · ~6-line change

**File:line**: `agents/livekit/dispatcher_fsm.py:356-372` (`transition` method,
the `if f.not_breathing` block).

**Today**:
```python
if f.not_breathing and self.state not in (State.CRITICAL_VERIFY,
                                           State.CRITICAL_CPR):
    self.is_cardiac_arrest = True
    self.state = State.CRITICAL_VERIFY
```

**Proposed change** (defense-in-depth, not regex tightening — keeps the wide
match but gates the state transition):
```python
# Require third-party AND a *positive* not-breathing signal (not just
# "not responding" / "won't respond" social-context hits).
positive_arrest_cue = bool(
    re.search(r"\b(?:stopped breathing|not breathing|"
              r"isn't breathing|no pulse|no heartbeat|"
              r"unresponsive|won'?t wake up|just gasping)\b",
              utterance, re.IGNORECASE)
)
ambiguous_arrest_cue = bool(
    re.search(r"\b(?:not responding|won'?t respond|no(?:t)? breath)\b",
              utterance, re.IGNORECASE)
)
should_jump_to_verify = positive_arrest_cue or (
    ambiguous_arrest_cue and self.is_third_party
)
if should_jump_to_verify and self.state not in (State.CRITICAL_VERIFY,
                                                  State.CRITICAL_CPR):
    self.is_cardiac_arrest = True
    self.state = State.CRITICAL_VERIFY
    ...
```

**Why this is safe**: Positive cues ("stopped breathing", "no pulse",
"unresponsive") still always trigger. Ambiguous cues ("not responding")
require third-party context. First-person "I'm not breathing well" no
longer mis-routes to CPR-verify (which the caller cannot perform on
themselves).

**Verification** (proposed unit test, no code applied):
- Add `tests/voice/test_dispatcher_fsm.py` with cases:
  - `"My friend stopped breathing"` -> `verify_cpr_surface` (still works)
  - `"My neighbor isn't responding to my texts"` (no third-party feature
    fires either, since "neighbor" isn't in `_RE_THIRD_PARTY`) -> stays in
    INTAKE
  - `"He is not responding"` + prior third-party utterance -> `verify_cpr_surface`
  - `"I can't breathe"` (first-person) -> stays in INTAKE / KEY_QUESTIONS
- Run: `pytest tests/voice/test_dispatcher_fsm.py -v`

**Rollback**: revert lines 356-372 to the original literal block.

---

### A2. Sticky `complaint` latch + trauma-prefers-bleeding KQ

**Risk: low** · **Medium leverage** · ~4-line change

**File:line**: `agents/livekit/dispatcher_fsm.py:343-349`.

**Today**:
```python
if f.has_emergency:
    self.emergency_known = True
    if f.fire:
        self.complaint = "fire"
    elif f.trauma:
        self.complaint = "trauma"
    else:
        self.complaint = "medical"
```

This overwrites `complaint` every turn. So a caller who said "shooting" on
turn 1 (complaint=trauma) and "stopped breathing" on turn 2 ends up with
complaint=medical.

**Proposed change**:
```python
if f.has_emergency:
    self.emergency_known = True
    # Sticky: trauma + fire latches stay, medical fills only when nothing
    # higher-priority has latched.
    if f.fire and self.complaint != "trauma":
        self.complaint = "fire"
    elif f.trauma:
        self.complaint = "trauma"
    elif self.complaint == "unknown":
        self.complaint = "medical"
```

**Why this matters**: Penetrating-trauma callers ("shot in chest", "stab
wound") need bleeding-control instructions BEFORE CPR verification. The
current flow drops the `kq_bleeding_location` ask entirely because cardiac
short-circuit pre-empts.

**Verification**:
- Test: `"shot in chest and not breathing"` -> `complaint=trauma`, then
  in CRITICAL_VERIFY ask the bleeding location *as part of* the verify
  flow. (This requires a small companion change in `_intent_in_verify`
  to interleave one trauma question before V1 -- see A3.)

**Rollback**: revert to original elif-chain.

---

### A3. `_intent_in_verify` must respect direct-question router

**Risk: low** · **Quality-of-life leverage** · ~3-line change

**File:line**: `agents/livekit/dispatcher_fsm.py:461-479`.

**Today**: `_intent_in_verify` only emits `verify_cpr_surface` /
`verify_cpr_breathing` / `instruct_cpr_compressions`. It does not
check `_direct_question_intent`.

**Proposed change**:
```python
def _intent_in_verify(self, f: Features, t0: float) -> Intent:
    # Caller asked a direct question — answer it first (mirrors
    # _intent_in_cpr, line 484).
    q = self._direct_question_intent(f)
    if q is not None:
        return self._record(q, t0)
    if not self.surface_confirmed:
        ...  # unchanged
```

**Why**: When the caller mid-CPR-verify asks "What did you hear me say?"
or "Should I move him?", the FSM currently re-emits the verify question
verbatim. Adds caller-frustration loops.

**Verification**: Test `"Should I move him?"` mid-CRITICAL_VERIFY -> emit
`answer_do_not_move`.

**Rollback**: drop the `q = ...` guard.

---

## B. STT accuracy fixes (top 2)

### B1. Server-side ITN (inverse text normalization) for digits

**Risk: medium** · **Highest STT leverage** · ~30-line addition to server.py

**File:line**: `infra/b300/services/parakeet/server.py` — add to
`/transcribe` and `/ws` handlers' final emit step.

**What it does**: Convert spelled-out cardinals to digits BEFORE the FSM
sees the transcript. "One hundred Ocean Avenue." -> "100 Ocean Avenue."
-> FSM `_RE_HAS_DIGIT` fires -> `address_known=True` on turn 1 instead of
turn 2 (or never, if the suffix mis-hears).

**Implementation sketch** (NOT applied):
```python
# At top of server.py, lazy-init.
_ITN = None
def _get_itn():
    global _ITN
    if _ITN is None:
        from nemo_text_processing.inverse_text_normalization.inverse_normalize \
            import InverseNormalizer
        _ITN = InverseNormalizer(lang="en", cache_dir="/models/itn-en")
    return _ITN

# In _extract_text_score (after text is computed):
itn = _get_itn()
try:
    text = itn.normalize(text, verbose=False, n_tagged=1)
except Exception:
    pass  # fall back to un-normalized text
```

**Risks**:
- Adds ~5-20 ms per utterance.
- ITN can over-normalize ("for one" -> "for 1" -- usually harmless in
  dispatch context, but verify).
- Requires `nemo_text_processing` data files. Already in NeMo 25.09
  container per release notes; verify with `python -c
  "import nemo_text_processing"` on pod before commit.

**Verification**:
- pod-side smoke: `curl -X POST http://127.0.0.1:9100/transcribe -H
  "Content-Type: audio/wav" --data-binary @one_hundred_ocean.wav | jq .text`
- Expect: `"100 Ocean Avenue"` (or close).
- p95 latency check: `agents/livekit/bench_b300.py` should not regress
  past +25 ms.

**Rollback**: remove the `_get_itn()` call; un-normalized text returns.

---

### B2. NeMo GPU-PB phrase boost for address suffixes + dispatch jargon

**Risk: medium-high** · **Medium STT leverage** · ~50-line change to server.py
+ phrases file

**File:line**: `infra/b300/services/parakeet/server.py:163,211,305` — change
`model.transcribe([...])` to use a config that engages
`rnnt_decoding.greedy.boosting_tree`.

**What it does**: At decode time, bias the RNN-T/TDT search toward known
phrases — street suffixes (Avenue, Boulevard, Drive, etc.), cardinal
directions (North, South), 911-domain terms (ambulance, paramedics, not
breathing, unresponsive). Reduces "Ocean Avenue" -> "ocean of new" type
mis-hears.

**Implementation sketch** (NOT applied):
```python
# Phrases file at /opt/prism42/parakeet/phrases.txt — capitalized.
# (Per NVIDIA docs: capitalization-supporting models need capitalized phrases.)
PHRASES_FILE = os.environ.get(
    "PARAKEET_PHRASES_FILE",
    "/opt/prism42/parakeet/phrases.txt",
)

def _configure_decoding(model):
    # NeMo 2.5+ API.
    from omegaconf import OmegaConf
    decoding_cfg = model.cfg.decoding
    decoding_cfg.strategy = "greedy_batch"
    decoding_cfg.greedy.boosting_tree = OmegaConf.create({
        "key_phrases_file": PHRASES_FILE,
        "context_score": 1.0,
        "depth_scaling": 2.0,
    })
    decoding_cfg.boosting_tree_alpha = 0.5
    model.change_decoding_strategy(decoding_cfg)
```

**Risks**:
- Adds ~5-15 ms decode latency per phrase set. Tunable.
- Over-boosting can pull model toward false-positive "Avenue" on any
  /-vee-noo/ ending. Requires `boosting_tree_alpha` tuning.
- Capitalization rule: "ocean" wouldn't match — must be "Ocean". Real-life
  Parakeet output capitalizes nouns reliably for the v3 model, so this is
  mostly fine.
- **Not a fix for "of new" -> "Avenue".** Phrase boost biases the search but
  cannot override a confidently-mis-heard phoneme cluster. Needs B1 + correction
  layer for full mitigation.
- NeMo version verification needed: NeMo 25.09 container -> NeMo >=2.5;
  verify `pip show nemo_toolkit` on pod before commit.

**Verification**:
- Bench delta: same audio, same caller -> Parakeet output before/after
  GPU-PB. Expect "Ocean Avenue" stable instead of "ocean of new" 50% of
  the time. (Real number depends on tuning.)
- No regression on non-address utterances: `bench_b300.py` 10-run mean
  delta should not exceed +20 ms.

**Rollback**: drop `_configure_decoding(model)` call; default decoding restores.

---

## C. Bonus low-risk picks

### C1. Tighten `_RE_TRAUMA` — remove `\bfall\b` ambiguity

**Risk: trivially low** · `dispatcher_fsm.py:183`.

`r"\b(?:hit|stabbed|shot|fell|fall|crash|accident)\b"` matches `fall colors`,
`hit me up`, `crashed his computer`. Tightening:

```python
_RE_TRAUMA = re.compile(
    r"\b(?:stabbed|shot|car (?:crash|accident)|"
    r"(?:was|got|been) (?:hit|stabbed|shot)|"
    r"(?:he|she|they|i)\s+fell|"
    r"fell (?:down|off|on)|"
    r"crashed (?:his|her|their|the) (?:car|bike|truck))\b",
    re.IGNORECASE,
)
```

Verification: re-run FSM regex test fixtures. Trade-off: more verbose,
fewer false positives. May need to keep a permissive shadow regex for
soft signals.

### C2. Confidence-gated reprompt in INTAKE

**Risk: low-medium** · `agents/livekit/orchestrator.py:`~338-343`.

When `intent == request_location_and_emergency` AND `confidence < 0.5`
on the prior STT final, use `reprompt_caller` template ("Sorry, could
you repeat that for me?") instead of asking the canonical opener again.
Avoids parrot-loop on noisy STT.

Requires plumbing confidence from `SpeechEvent.alternatives[0].confidence`
into the FSM's `transition()` -- currently dropped.

### C3. Add a "spelled-cardinal -> digit" pre-FSM normalizer (Python-side)

**Risk: low** · `agents/livekit/dispatcher_fsm.py:236` (`classify` function).

If we don't ship server-side ITN (B1), do a 20-line Python pass that
maps "one"-"twenty" + "thirty"-"ninety" + "hundred"/"thousand" to digits
in the utterance before regex matching. Use `word2number` package or
inline. Cheap, simple, doesn't require NeMo changes.

```python
def _normalize_spelled_numbers(text: str) -> str:
    # Map common spelled cardinals 1-1000 to digits.
    # (Implementation omitted; ~30 lines.)
    return text

def classify(utterance: str) -> Features:
    if not utterance:
        return Features()
    t = _normalize_spelled_numbers(utterance.strip())
    # ... rest unchanged.
```

**Caveat**: B1 (server-side ITN) is cleaner because it normalizes the
*final transcript* the caller sees in the dispatch UI. C3 only normalizes
for FSM purposes — UI keeps "one hundred". Pick one.

---

## What to apply first (Team P recommendation)

For the hackathon ship-by:

1. **A1** (cardiac short-circuit gate) — biggest mis-classification leverage,
   tiny risk.
2. **C3** (spelled-cardinal normalizer) — fastest STT fix, no pod changes.
3. **A3** (verify-step direct-question router) — quality-of-life polish.
4. **C1** (trauma regex tighten) — prevents false trauma latches in casual
   conversation.

Defer to a follow-up cycle:

- **B1** (server-side ITN) — better-engineered version of C3 but needs pod
  smoke. Worth doing once C3 has shipped.
- **B2** (GPU-PB phrase boost) — real audio gain, but needs benchmarking
  first; risk of regression on non-address utterances.
- **A2** (sticky complaint) — depends on a re-routed `_intent_in_verify`
  that interleaves bleeding KQ; that's a bigger surgery.

---

## DO NOT do (out of charter / scope)

- Do not propose framework swap (Pipecat, Vocode). User directive.
- Do not propose vLLM env changes. Frozen.
- Do not restart Parakeet service. Read-only directive.
- Do not edit `dispatcher_fsm.py` / `templates.py` / `response_gate.py`.
  These belong to the integrator.
