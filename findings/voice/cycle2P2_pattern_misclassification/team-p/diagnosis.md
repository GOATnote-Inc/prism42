# Cycle-2P2 Diagnosis — FSM intent mis-classification + Parakeet address mis-hear

Author: Team P · Date: 2026-04-26 · Status: research-only, no code changes

## TL;DR

1. **The "verify_cpr_surface fires when there was no cardiac signal" symptom is real
   but it does NOT come from the address utterance.** It comes from
   `_RE_NOT_BREATHING` which matches a much wider surface than its name implies —
   `unresponsive`, `won't respond`, `not responding` are all in the same alternation,
   so any of those literals (or the STT's transcription of them) flip
   `is_cardiac_arrest=True` AND immediately jump the FSM to `CRITICAL_VERIFY`
   regardless of what was said before.

2. **The "100 Ocean Avenue" -> "One hundred ocean of new" mis-hear is a Parakeet
   accuracy bug, not an FSM bug.** When STT loses the digits AND the suffix the
   FSM has nothing to latch on (no digit, no street word), so `address_known`
   stays False and the dispatcher loops `request_location_and_emergency` /
   `request_emergency`. There is also a hand-off failure: if Parakeet gets the
   digits or the suffix on a later turn, the FSM does latch (verified live in
   worker.log session b4880122 turn 2 -- "One hundred Ocean Avenue." latched).

3. **The smoking-gun "Are they on the floor, flat on their back?" 4 turns into
   the call** that the user reported is the `verify_cpr_surface` template, fired
   because `_RE_NOT_BREATHING` matched the caller's *trauma* utterance. In
   Test 4 ("shooting and friend shot in chest and he's not breathing good"),
   the latch is correct (caller really did say "not breathing"), but the FSM
   throws away `complaint=trauma` (latched on `_RE_TRAUMA`) and routes to the
   cardiac-arrest sub-FSM by default. The trauma key-question
   (`KQ_BLEEDING_LOCATION`) never gets a chance.

## Empirical evidence — pod worker.log, 2026-04-26

Direct grep of `/tmp/prism42-logs/worker.log`. Every transcript below is
real Parakeet output; every FSM line below is from `fsm.transition` info logs.

### Session b4880122 (17:08:50 - 17:09:19) — TEST 3 reproducer

| Turn | Caller utterance (Parakeet final) | FSM intent emitted | Cardiac latch |
|---:|---|---|---|
| 1 | `"One hundred ocean of new."` | `request_location_and_emergency` | False |
| 2 | `"One hundred Ocean Avenue."` | `request_emergency` (address now latched via `Avenue`) | False |
| 3 | `"Uh my"` | `request_emergency` (no signal, repeat) | False |
| 4 | `"My husband is my husband's down. My husband's not breathing."` | `verify_cpr_surface` | **True** |

The "Are they on the floor, flat on their back?" the user reported in Test 3
appears at turn 4, AFTER the caller actually said "not breathing." That is
the `_RE_NOT_BREATHING` literal `\bnot breathing\b` matching correctly. The
problem isn't the `verify_cpr_surface` itself — it's that the caller never
got to a clean intake step before it fired. Turn 1 wasted a turn because
the address regex couldn't see the digits or the suffix in the STT output.

### Session 9d71b1e4 (17:04:49 - 17:06:26) — TEST 4 cardiac scenario

| Turn | Caller utterance | FSM intent | Cardiac | Complaint |
|---:|---|---|---|---|
| 1 | `"Uh one hundred Ocean Avenue."` | `request_emergency` | False | unknown |
| 2 | `"There has been a shooting and uh there are um some people dead and uh my friend was shot in the chest and he's not breathing good."` | `verify_cpr_surface` | **True** | trauma |
| 3 | `"Okay. Uh I can apply some pressure..."` | `verify_cpr_surface` (still in critical_verify) | True | trauma |
| 4 | `"What did you hear me say?"` | `verify_cpr_surface` (caller question is NOT routed in CRITICAL_VERIFY) | True | trauma |
| 5 | `"I think they stopped breathing."` | `verify_cpr_surface` | True | medical (overwritten) |

The cardiac latch IS correct for this scenario — the caller did say "not
breathing." But two design problems show:

- **`complaint='trauma'` is silently overwritten on turn 5** by the same logic
  in `transition()`: `if f.fire: complaint='fire'; elif f.trauma: complaint='trauma';
  else: complaint='medical'`. The latch is not sticky -- whichever signal
  fires last wins. Verified at `dispatcher_fsm.py:344-349`.
- **`_intent_in_verify` does not call `_direct_question_intent`.** So when the
  caller asked "What did you hear me say?" mid-CPR-verify (turn 4), the FSM
  ignored the question and re-emitted `verify_cpr_surface`. Compare with
  `_intent_in_cpr` (line 481-487) which *does* route direct questions.

## FSM intent-classification audit table

One row per Intent value, the regex(es) that trigger it, and at least one
real or plausible mis-match. All regexes sourced verbatim from
`~/prism42/agents/livekit/dispatcher_fsm.py:153-208`.

| Intent | Trigger pathway | Matches correctly | Mis-matches / over-fire |
|---|---|---|---|
| `request_location_and_emergency` | INTAKE state, neither `address_known` nor `emergency_known` | First turn after greeting | Fires every turn until BOTH features latch — if STT loses both, FSM loops forever |
| `request_location` | INTAKE, `emergency_known=True`, `address_known=False` | Caller starts with the emergency | — |
| `request_emergency` | INTAKE, `address_known=True`, `emergency_known=False` | Caller starts with address | Fires repeatedly when caller stalls (Test 3 turns 2 & 3) |
| `confirm_address` | INTAKE -> ADDRESS_CONFIRMED when both latched | Both signals on same turn | — |
| `deliver_reassurance` | ADDRESS_CONFIRMED, no question | After confirm | Caller question must use `_RE_DO_NOT_MOVE_Q` / `_RE_HOW_LONG_Q` / `_RE_OUTCOME_Q` literals to bypass — most caller asks DON'T match |
| `kq_responsive_breathing` | KEY_QUESTIONS, third_party, complaint=medical | Third-party medical | — |
| `kq_severity` | KEY_QUESTIONS, first_person, complaint=medical | First-person medical | Caller saying "I have chest pain" matches `_RE_CHEST_PAIN` so complaint=medical, but if they also say "I fell" trauma overwrites medical (line 344-349) |
| `kq_bleeding_location` | KEY_QUESTIONS, complaint=trauma | After trauma report | Never fires when `_RE_NOT_BREATHING` matches first because cardiac short-circuit pre-empts (line 356-372) |
| `kq_fire_evacuation` | KEY_QUESTIONS, complaint=fire | After fire report | — |
| `kq_safe_location` | NEVER REACHED in current FSM. The `complaint='crime'` branch is undefined; `_intent_in_key_questions` does not handle it. | — | This intent is unreachable code. |
| **`verify_cpr_surface`** | CRITICAL_VERIFY sub-FSM, `surface_confirmed=False` | "He stopped breathing" | **`unresponsive`, `not responding`, `won't respond`, `won't wake up` ALL trigger this branch via `_RE_NOT_BREATHING`. False positives below.** |
| `verify_cpr_breathing` | CRITICAL_VERIFY, `surface_confirmed=True`, `breathing_assessed=False` | After surface confirmed | — |
| `instruct_cpr_compressions` | CRITICAL_CPR | After both verify steps green | Gate's `cpr_safe()` requires `is_cardiac_arrest AND surface_confirmed AND breathing_assessed` (response_gate.py:227-244) — defense in depth holds |
| `instruct_choking_back_blows` | PRE_ARRIVAL, `f.choking` | "He's choking" | `_RE_CHOKING = \bchok(?:ing\|ed)\b\|\bcan'?t breathe\b` — "I can't breathe" (first-person) ALSO matches, then PRE_ARRIVAL would route choking instruction AT THE CALLER. Mitigated only because cardiac short-circuit usually pre-empts |
| `instruct_pressure_bleed` | PRE_ARRIVAL, `f.bleeding` | "He's bleeding" | "blood pressure" matches `\bblood\b` (line 179) — ANY mention of blood routes here |
| `instruct_seizure` | PRE_ARRIVAL, `f.seizure` | "He's having a seizure" | — |
| `answer_do_not_move` | Any state, `_RE_DO_NOT_MOVE_Q` | "Should I move him?" | Narrow regex — misses "Is it OK to move him?", "Do you want me to move him?", "Should I roll him over?" |
| `answer_how_long` | `_RE_HOW_LONG_Q` | "How long?" "When are they coming?" | Misses "Where are they?", "Are they nearby?", "Did you dispatch?" |
| `answer_outcome_uncertain` | `_RE_OUTCOME_Q` | "Will he be OK?" | Misses "Is it bad?", "Will he live through this?" (uses "live" not in regex), "Is he going to die" matches but only a narrow set |
| `reprompt_caller` | Currently unreachable from `transition()` — not in any `_intent_in_*` path | — | Dead intent (REPROMPT enum exists but no code path emits it) |
| `closeout` | HANDOFF state, OR PRE_ARRIVAL with no instruction match | — | Fires from PRE_ARRIVAL when caller answer doesn't match choking/bleeding/seizure — caller's actual answer to KQ gets answered with "Stay on the line until they get there" |

## Specific finding: `verify_cpr_surface` over-fires

### Where: `dispatcher_fsm.py:159-164`, `:356-372`

```python
_RE_NOT_BREATHING = re.compile(
    r"\b(?:stopped breathing|not breathing|no(?:t)? breath(?:ing)?|"
    r"isn't breathing|can'?t breathe|no pulse|no heartbeat|"
    r"unresponsive|won'?t wake up|won'?t respond|not responding)\b",
    re.IGNORECASE,
)
```

```python
if f.not_breathing and self.state not in (State.CRITICAL_VERIFY,
                                           State.CRITICAL_CPR):
    self.is_cardiac_arrest = True
    self.state = State.CRITICAL_VERIFY
    ...
    return self._intent_in_verify(f, t0)
```

### Verified false-positive cases (live regex test, this session)

| Caller utterance | `not_breathing` match? | What FSM does | Why it's wrong |
|---|---:|---|---|
| `"He is not responding to my messages"` | True | Jumps to CRITICAL_VERIFY, emits `verify_cpr_surface` | "Not responding" alternation hits — but caller is talking about texts, not consciousness. False alarm. |
| `"My neighbor isn't responding to my texts"` | False | Stays in current state | Word-boundary on `\b...\b` saves us only because the literal is `not responding` not `isn't responding to ... texts`. Verified by test. |
| `"I'm not breathing fast enough"` | True | CRITICAL_VERIFY (first-person caller) | Caller is the one with shortness of breath -- this is `kq_severity`, not CPR-verify. |
| `"can't breathe"` (first-person) | True | CRITICAL_VERIFY | First-person choking -- caller can't perform CPR on themself. |
| `"unresponsive"` (any context) | True | CRITICAL_VERIFY | Single-word literal match. "She was unresponsive when she signed up" would trigger (admittedly absurd but illustrates the over-fire surface). |
| `"won't wake up"` (any context) | True | CRITICAL_VERIFY | Caller could be saying "my phone won't wake up." |

### The catalog of false-positive risks

The user's request: "Cardiac-arrest latch over-eager risk catalog (false-positive scenarios)." Here it is, ranked by likelihood beta-tester encounter:

1. **First-person reporters of distress** — "I can't breathe" / "I'm not breathing well" trigger CPR verification AT the caller. Real CPR cannot be self-administered. Mitigation should require `is_third_party=True` before engaging CRITICAL_VERIFY, OR route to `kq_severity` for first-person.
2. **"Not responding" in social context** — "She's not responding to my texts/calls/emails" all trigger. This is the most likely beta-tester mis-fire — wellness-check calls.
3. **Trauma collapses to medical** — Caller says "shot in chest and not breathing." Both trauma AND not-breathing latch; cardiac short-circuit wins. The bleeding KQ is never asked. For penetrating trauma the *first* dispatcher question by NAEMT/IAED is "where is the wound, can you put pressure on it?" -- that gets skipped here.
4. **Address phrases that contain trigger words** — "5012 No-Harbor Road" contains "no" + "har..."; "Won't Way" doesn't fire (apostrophe absent), but "Wont way" doesn't either. No live false positive on addresses.
5. **CRITICAL_VERIFY swallows direct questions** — `_intent_in_verify` does not check `_direct_question_intent` (compare line 461 with line 484). Caller asking "Is help coming?" mid-CPR-verify gets ignored.

## Specific finding: address-detection failure for "One hundred ocean of new"

### Where: `dispatcher_fsm.py:153-158`, `:241-242`

```python
_RE_HAS_DIGIT = re.compile(r"\d")
_RE_STREET = re.compile(
    r"\b\d+\s+\w+|\b\w+\s+(?:st|street|ave|avenue|rd|road|blvd|boulevard|ln|lane|"
    r"dr|drive|ct|court|way|hwy|highway|pkwy|parkway)\b",
    re.IGNORECASE,
)
...
has_address=bool(_RE_STREET.search(t)) or bool(_RE_HAS_DIGIT.search(t)),
```

`has_address` requires EITHER a literal ASCII digit `\d` OR a numeric-prefix-word
pair OR a word-suffix pair where the suffix is in a closed list (st/street/ave/
avenue/rd/road/blvd/boulevard/ln/lane/dr/drive/ct/court/way/hwy/highway/pkwy/parkway).

### The Parakeet output `"One hundred ocean of new."` contains:

- No `\d` digit. (Parakeet emits the spelled-out form for "100".)
- No street suffix from the closed list. ("New" is not in the suffix set; "of"
  is not either.)

So `has_address=False`. The FSM stays in INTAKE and re-emits
`request_location_and_emergency`. **Verified live**: worker.log session
b4880122 turn 1 at 17:08:50 logs `address_known=False intent=request_location_and_emergency`.

### Why this matters for beta testers (per Brandon Dent, MD)

Real callers WILL have addresses Parakeet can mis-hear. From `worker.log`
in the last 24h alone, the same Parakeet model produced these address
transcripts that the FSM correctly latched on:

- `"Twenty Lake Park Drive."` (latches via `Drive`)
- `"Twelve Riverside"` (does NOT latch — no digit, no suffix)
- `"Twenty Riverside"` (does NOT latch)
- `"Two hundred"` (does NOT latch)
- `"One hundred Ocean Avenue."` (latches via `Avenue`)
- `"One hundred ocean of new."` (does NOT latch — STT mis-heard suffix)

Two-thirds of these spelled-out-number addresses do NOT latch on a clean
Parakeet output. The FSM's address regex is brittle to:

1. **Spelled-out cardinal numbers.** Parakeet 0.6b-v3 emits "one hundred",
   "twenty", "twelve" not "100", "20", "12". The `\d` clause never fires.
2. **Missing/mangled street suffix.** If STT drops or mangles the suffix
   ("ocean of new" instead of "Ocean Avenue"), the closed-list match misses.
3. **Cardinal directions.** "East 23rd Street" — `\d+\s+\w+` requires digit,
   passes; "Twenty-third Street" — only matches if "third" + "Street" are
   adjacent, which the regex requires (and the regex DOES match `\w+\s+street`).
4. **Apartment numbers without street.** "Apartment 2B at the back" — `\d`
   from "2B" makes `has_address=True` (false positive — caller hasn't given
   street).

## How the address path SHOULD work (vs how it does)

Current path:
```
caller -> Parakeet -> string -> _RE_STREET / _RE_HAS_DIGIT -> has_address
```

What's missing:
- Spelled-out-number normalization (one->1, twenty->20, hundred->mul-100, etc.).
- Lookup against a permissive street-suffix vocabulary that handles
  STT-typical confusions (Ave/of, Drive/dry, Lane/lain).
- A fallback "looks-like-an-address" classifier that fires on patterns like
  `<spelled-number-word> <capitalized-noun> <street-suffix-or-confusable>`.
- Keyterm boost on the STT side so "Avenue", "Boulevard", "Drive" etc. are
  unlikely to be mis-heard in the first place.

The FSM is doing what its regex says. The regex was written for clean STT
output. Live STT output is not clean.

## Other FSM observations (priority ranked)

1. **`_RE_THIRD_PARTY` will commit pronouns to `they` on a first-person
   utterance that contains "she's" anywhere** — verified by line 188
   `_RE_SHE = re.compile(r"\b(?:my wife|...|she is|she's|she was|her\b)\b", ...)`.
   Caller says "I'm fine but she's bleeding" → pronouns commit to `she/her`
   (correct), but "I'm checking on her" → `her\b` -> `she/her` even though
   the caller is the patient.
2. **`_RE_FIRST_PERSON` is narrow** — only matches `i (?:have|am|feel|can'?t|got)`
   or `my chest|my arm`. Caller saying "I'm bleeding" does NOT match (no `have/am/feel/can't/got`),
   so the FSM does NOT mark it first-person. "I'm bleeding" -> third-party
   default kicks in -> `kq_responsive_breathing` ("Is the patient awake and
   breathing?") asked of the patient herself.
3. **`_RE_TRAUMA` matches `\bfall\b` on plain word "fall"** — caller saying
   "the caller fall back here" or "fall colors" or "fall plans" all trigger
   complaint=trauma. Risk for general-conversation onset.
4. **`_RE_TRAUMA` matches `\bhit\b`** — "we got hit by a virus" / "the kid hit
   me yesterday" / "hit a deer" trigger complaint=trauma. Verbose triggering.
5. **`_intent_in_pre_arrival` returns CLOSEOUT when no instruction matches**
   (line 459). On a caller's "yes I can apply pressure" answer to bleeding
   KQ, no choking/bleeding/seizure word fires, and FSM closes out instead
   of advancing the protocol.

## Sources

- `~/prism42/agents/livekit/dispatcher_fsm.py` (regexes lines 153-208,
   transition lines 318-400, sub-FSM lines 461-487)
- `~/prism42/agents/livekit/templates.py` (lines 106-235)
- `~/prism42/agents/livekit/response_gate.py` (`cpr_safe` lines 227-244,
   `_SAFETY_TEMPLATE_ONLY` lines 193-204)
- pod `/tmp/prism42-logs/worker.log` lines @ 2026-04-26 17:04 - 17:18 (sessions
   `9d71b1e4`, `b4880122`, `f2c54453`)
- Empirical regex test (this session) reproduced in section above
