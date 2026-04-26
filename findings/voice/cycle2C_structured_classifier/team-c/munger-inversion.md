# Munger Inversion — what could go wrong, ranked by severity × probability

**Author:** Team C-Architect, prism42 cycle-2C.
**Method:** invert the design — assume the classifier WILL fail in each of these ways. For each, document a concrete scenario, the detection signal, and the mitigation. Ranked by `severity × probability`. The top three are mitigation-mandatory; bottom two are watch-list.

The single overarching defense: **regex `classify()` is the floor. The LLM is supplemental. When the LLM fails, the FSM falls back to today's behavior.** Every failure mode below ends with the system in a known-good state — never wedged.

---

## Failure mode 1 — Nemotron emits invalid JSON despite `guided_json` (severity HIGH × probability LOW = WATCH)

### Scenario
Caller utterance: `"my husband is having chest pain at four hundred twenty one Maple"` (Example 1). Nemotron, mid-decode, exits the JSON FSM at the `address_candidate.raw_text` field because xgrammar's grammar compilation has an edge case on long quoted strings. The model emits an unclosed brace and a 500-character string; vLLM's response is `{"intent": "intake", "address_candidate": {"raw_text": "four hundred twenty one Maple at the corner of...` truncated at `max_tokens=192`.

### Why probability is LOW
xgrammar's "near-zero overhead" claim ([xgrammar README](https://github.com/mlc-ai/xgrammar) fetched 2026-04-26) implies the FSM is correct on Draft-07 schemas of our shape. Empirical reports across the vLLM ecosystem show ≥99 % JSON-validity rate for schema-constrained generation on simple flat schemas. We deliberately keep our schema flat (knowledge-base.md §4) for exactly this reason.

### Detection
- `json.loads(raw)` raises `JSONDecodeError` in `structured_classifier.classify_async`.
- Result: `ClassifierResult(schema_valid=False, fallback_reason="json_parse_error", ...)`.
- Structured log: `structured_classifier.result schema_valid=False fallback_reason="json_parse_error" raw_json=<truncated 500 chars>`.

### Mitigation
Already designed-in. The orchestrator inspects `schema_valid`; when False, the FSM transitions on regex Features only. Voice path identical to today. The structured log captures the bad raw JSON so the integrator can submit it to vLLM upstream.

If the rate exceeds 1 % (one in 100 turns), trigger a deeper investigation:
- Tighten `max_tokens` (currently 192). If we're hitting truncation, the value is too low for our schema.
- Switch backend explicitly to `outlines` via `--structured-outputs-config.backend outlines` if xgrammar is the culprit.
- File a vLLM issue with a minimum repro.

### Verification
`tests/voice/test_structured_classifier_offline.py::test_classify_async_handles_invalid_json` mocks this exact failure and asserts the fallback path. Live: monitor `structured_classifier.result` log for `json_parse_error` rate; alert if > 0.5 %/hour.

---

## Failure mode 2 — JSON valid but field values nonsensical (severity HIGH × probability MEDIUM = MITIGATE)

### Scenario
Caller utterance: `"yeah, I mean they're in a chair"` (Example 3, Bug 3). Nemotron emits VALID JSON that schema-validates:

```json
{"intent": "verify", "acuity": "P1", "address_candidate": {...},
 "awake": null, "breathing": null,
 "surface": "floor",   /* WRONG — caller said "chair" */
 "caller_question": false, "caller_role": "third_party",
 "complaint_category": "medical",
 "negation_signal": false,   /* WRONG — should be true */
 ...}
```

The model misclassifies. Schema is fine; semantics are wrong. The FSM uses `f.llm_negation_signal=False` and `f.llm_surface="floor"` (and the regex's `floor_negation` pattern doesn't match "they're in a chair"). The FSM stays in `VERIFY_SURFACE` and re-asks. Bug 3 NOT FIXED by cycle-2C.

### Why probability is MEDIUM
This is the "model gets it wrong" case. Nemotron's IFBench is 71.5; on a constrained-classifier task with five examples in the prompt, we estimate the per-field correctness in the high 80s. **`negation_signal` is the highest-error field** because it requires linguistic inference (matching "in a chair" to a CONTRADICTION of the dispatcher's previous "are they on the floor?" question, given the model has access only to the current utterance plus a thin caller_role hint).

### Detection
- The Claude critic (Team B-Critic) flags turns where the FSM emitted `VERIFY_SURFACE` ≥ 2 turns in a row AND the most recent utterance contained any of the regex `_RE_FLOOR_NEGATION` patterns. Cross-reference: did the LLM also miss it?
- The dispatcher UI's transcript pane shows the same dispatcher line repeating; humans notice.
- A live monitor: count `verify_cpr_surface` repeats per call. > 2 → page a human.

### Mitigation
Three-layer defense:

1. **Regex `classify()` keeps the existing positive-only floor_flat AND the cycle-2R3 `_RE_FLOOR_NEGATION` regex.** If regex catches "in a chair", the FSM routes to INSTRUCT_CPR_REPOSITIONING regardless of what the LLM said. This is the existing fix landed via R3-B3-A.
2. **Cycle-2C OR's the regex with the LLM signal** in `_intent_in_verify` (integration-plan.md §2.2). LLM-only failure is ABSORBED by regex; both-fail is the actual hole.
3. **Force-advance after N repeats** (Team R3 R3-B3-C, currently labeled C-tier). For cycle-2C we ESCALATE this to mandatory-belt-and-suspenders: after 3 consecutive `VERIFY_SURFACE` emits with NO progression on `surface_confirmed`, the FSM force-routes to `INSTRUCT_CPR_REPOSITIONING` regardless of any signal. This is a clinical-safety override.

### Verification
`tests/voice/test_structured_classifier.py::test_live_classifier_example_3_in_a_chair` asserts the LLM gets surface="chair" + negation_signal=True. If it fails on the live pod, the prompt needs more examples in the "negation" class. Live: monitor `verify_cpr_surface` repeat counts; alert > 1 in 1000 calls.

---

## Failure mode 3 — Latency regression: classifier 2x slower than budget (severity HIGH × probability MEDIUM = MITIGATE)

### Scenario
Cycle-2C deploys with `PRISM42_ENABLE_STRUCTURED_CLASSIFIER=1`. Initial median classifier latency is 250 ms (within budget). After 48 hours of mixed traffic + xgrammar FSM cache pressure, median creeps to 500 ms; p95 hits 1.2 s. The user perceives a clear "the dispatcher is taking forever to reply" regression; total TTFT to first speakable byte goes from < 1 s to ~1.5 s.

### Why probability is MEDIUM
- xgrammar caches schema FSMs per-vLLM-session. If the worker process restarts, the first classifier call after restart pays the compile cost (~5-10 ms). Cumulative cache GC could surface as latency creep.
- Nemotron NVFP4 + FlashInfer MoE backend (Team N3 §7) has known sensitivity to context length; longer system prompts push first-token latency. Our system prompt is ~250 tokens — well under the threshold, but the example block adds ~150 tokens of structured-text the model has to attend to.
- Concurrent traffic on the same vLLM instance (e.g. another Prism rail using the same B300 pod) would queue our classifier behind other work.

### Detection
- `structured_classifier.result latency_ms` field on every turn. Histogram by `local_log` aggregator.
- Alarm at p95 > 600 ms (timeout ceiling) sustained over 5 minutes.
- Per-turn comparison: `gate_template_ms` (cycle-2T) end-to-end vs `structured_classifier.latency_ms` — if classifier is > 80 % of total turn time, that's the regression.

### Mitigation
Three actions, in order of preference:

1. **Reduce `max_tokens` from 192 to 128.** If the model is hitting truncation, this is wrong; if the model is finishing early, this is a no-op latency-wise. Test offline first.
2. **Drop one or two examples from the system prompt.** Each example costs ~30-50 prompt-tokens; dropping the longest two saves ~80 tokens prefill. Pair with offline regression set to confirm no quality regression.
3. **Disable the classifier (`PRISM42_ENABLE_STRUCTURED_CLASSIFIER=0`)** — voice path returns to today's regex+R3 behavior. Voice quality regresses to today; latency restored. This is the rollback.

The classifier is **gated by a 600 ms timeout** in `classify_async` (integration-plan.md §1.2). Breaching that timeout returns `fallback_reason="vllm_timeout"` and the FSM proceeds with regex-only. So the worst case for a single turn is +600 ms latency; the user does not get stuck.

### Verification
`tests/voice/test_structured_classifier.py::test_live_classifier_latency_p95` asserts p95 < 600 ms over 20 calls. CI cannot run this; the integrator runs it on the pod before each rollout.

---

## Failure mode 4 — Hidden Blackwell sm_103 bug in `guided_json` (severity HIGH × probability LOW = WATCH)

### Scenario
We deploy cycle-2C on the B300 pod. The vLLM build (`0.20.1.dev0+g101584af0.d20260425` per Team N3 §9) has a Blackwell-specific issue where xgrammar's logit-mask kernel uses an instruction not available in `sm_103` (only in `sm_100` proper). Output: every classifier call returns garbage tokens that happen to JSON-validate but with all default values. The system runs but every turn gets `intent="intake", confidence=0.0` regardless of the utterance. FSM dispatches the LLM features as low-confidence (rejected by merge rule), and behavior is identical to flag-OFF — but we paid the latency cost for nothing.

### Why probability is LOW
- xgrammar's logit-mask kernel is pure CPU (vLLM applies the mask in the sampler's CPU-tail). No Blackwell SM dependency.
- The mask itself is computed CPU-side from the precompiled FSM. GPU just sees a sampled-token-id.
- Team M's `cycle2S_b300_memory/team-m/profile.md` already exercises the Nemotron NVFP4 path on B300 with 313 tok/s decode and 50 ms median TTFT — no structured-output regression observed.

### Detection
- Per-field correctness on the live probe (`probe-spec.md` §4): if 100 % of classifications return `intent="intake"` regardless of input, the model is producing degenerate output even though JSON is valid.
- `confidence` distribution check: if 100 % of classifications return `confidence=0.0`, that's a smoking gun.
- A/B comparison: run Examples 1-5 on a non-B300 host (e.g. Modal H100) with the same prompt and schema; compare outputs.

### Mitigation
1. **Default-OFF flag is the immediate rollback.** Single env-var change.
2. **Switch to a non-Blackwell vLLM endpoint** if one exists. (Currently we have only the B300 pod for Nemotron-NVFP4. FP8 / BF16 variants run on H100 but require a separate deploy.)
3. **File a vLLM issue with the exact build hash and reproduction steps.**

### Verification
The probe spec (probe-spec.md §3) explicitly tests Examples 1-5 — no two of which return identical structured output. If the live probe shows identical outputs, this failure mode has fired; halt rollout.

---

## Failure mode 5 — Schema drift: FSM expects new field; old JSON missing it (severity MEDIUM × probability LOW = WATCH)

### Scenario
Cycle-2D adds a new schema field — say `secondary_complaint`. We update `psap_classification.schema.json` and the system prompt. We deploy schema v2 to the worker; the vLLM service is unchanged. But xgrammar's FSM cache holds the v1 schema (per-session compile). For ~the first 100 calls after deploy, vLLM emits v1 JSON missing `secondary_complaint`. The integration-plan.md §1.1 `ClassifierResult` dataclass tries to read the field from the parsed JSON, raises KeyError, and `classify_async` returns `fallback_reason="schema_invalid"`.

### Why probability is LOW
We control both producer (schema sent in `response_format`) and consumer (`ClassifierResult` deserializer). Schema bumps are coordinated. xgrammar compiles per-session, not globally; restarting the worker forces a fresh compile.

### Detection
- `structured_classifier.result fallback_reason="schema_invalid"` rate spike post-deploy.
- The `KeyError` is caught and logged; the integrator notices.
- `tests/voice/test_structured_classifier.py::test_live_classifier_example_*` should fail in pre-prod CI before rollout.

### Mitigation
1. **Forwards-compat in the deserializer**: every new field comes with a default. The `ClassifierResult` factory uses `payload.get("secondary_complaint", "unknown")` not `payload["secondary_complaint"]`. KeyError never raised.
2. **Schema-version pinning in the request**: the `name` field of `response_format.json_schema` includes a version (`"name": "psap_classification_v2"`). Bumping the name invalidates the per-session FSM cache.
3. **Rolling deploy**: when bumping schemas, restart workers one at a time and wait for fresh-compile latency to settle.

### Verification
Code review on every schema bump: confirm the deserializer uses `.get()` with defaults. Add `tests/voice/test_structured_classifier_offline.py::test_classifier_handles_missing_optional_fields` as a regression guard.

---

## Cross-cutting interaction with cycle-2T, cycle-2I, cycle-2R3

| Cycle | Cycle-2C interaction | Mitigation |
|---|---|---|
| **cycle-2T** (response gate) | Gate is downstream of FSM transition. Whatever Intent the FSM picks, the gate renders deterministically. Failure mode 2 (model misclassifies surface) reaches the gate as `Intent.VERIFY_SURFACE` repeated, and the gate renders the same template. The gate's anti-repetition validators do NOT catch this because the FSM picks the intent independently. | Force-advance after N repeats (mitigation 2.3) is the safety net. |
| **cycle-2I** (interruption fix) | Interruption fix is at LiveKit `TurnHandlingOptions` (worker.py:759-). Classifier latency is ADDITIVE to the on_user_turn_completed budget. If classifier blows the timeout (failure mode 3), `StopResponse` still cancels the LLM-prose stream and the gate's template is what the user hears — but with +600 ms delay. | The 600 ms classifier timeout is a HARD ceiling. p95 above 600 ms = rollback. |
| **cycle-2R3** (R3 fixes) | R3-B1-A, R3-B2-A, R3-B3-A regexes already landed. Classifier supplements them. | Failure mode 2 is the conjoint case (regex AND LLM both miss). Force-advance is the third defense. |
| **cycle-2BC** (Claude critic) | Critic consumes the structured payload from dispatch_publisher. Failure mode 5 (schema drift) would surface as critic ingestion errors. | Critic side: same `.get()` defaults. Schema-bump checklist covers both producers and consumers. |

---

## Top three mitigation priorities

1. **Force-advance after 3 consecutive VERIFY_SURFACE repeats** (failure mode 2). Promote from R3-C-tier to R3-B-tier-mandatory inside cycle-2C scope.
2. **Hard 600 ms classifier timeout with regex fallback** (failure mode 3). Already in design (integration-plan.md §1.1); make it non-negotiable.
3. **Per-field correctness check on live probe** (failure modes 1, 2, 4). Probe-spec.md §3 — at least 5 distinct example outputs; if 2+ are identical, halt rollout.

---

## What would make Munger smile

- The classifier CANNOT make voice quality worse — templates render the same regardless. Failure modes only affect WHICH template fires.
- The classifier CANNOT wedge the system — every failure mode terminates in `schema_valid=False` and the FSM proceeds on regex.
- The classifier CANNOT regress the existing R3 bug fixes — regex is the floor; LLM is OR'd on top.
- The classifier CAN regress latency — that's the one knob the integrator must watch. Hard timeout + flag-OFF rollback is a 30-second recovery.

The system is asymmetric in our favor: upside is "most turns get richer features"; downside is "some turns get the same regex-only features, possibly 250 ms later."

---

## References

- knowledge-base.md (this directory) §3 (vLLM gotchas)
- integration-plan.md (this directory) §1, §11
- schema.json
- Team N3 nemotron-knowledge-base.md §3, §8
- Team R3 fix-candidates.md (R3-B3-C force-advance escalation)
- agents/livekit/dispatcher_fsm.py:165-218 (regex floor patterns + R3 negation patch)
- agents/livekit/orchestrator.py:478-492 (StopResponse defense)
- vLLM issue #37362: <https://github.com/vllm-project/vllm/issues/37362>
- vLLM issue #30904: <https://github.com/vllm-project/vllm/issues/30904>
- xgrammar README: <https://github.com/mlc-ai/xgrammar>
