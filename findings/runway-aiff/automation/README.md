# Runway Phase 2 Automation

Playwright harness that drives `app.runwayml.com` in an isolated Chrome profile
to batch-generate the 19 non-Act-Two shots from `../shot-list.json`.

## Why isolated profile

Runs in `~/.runway-automation-profile/` so it does not collide with your live
Chrome session. You log in once; auth state persists.

## Out of scope (still manual)

- **Phase 1** — character upload (`@ken`, `@fizzlepuff`). OS file picker.
- **Phase 3** — 6 Act-Two close-ups. Need driving videos + per-shot judgment.

The `chrome-claude-playbook.md` covers those.

## Setup (once)

The venv + Playwright + Chromium were installed by the parent terminal-Claude.
If you ever recreate from scratch:

```bash
cd /Users/kiteboard/prism42/findings/runway-aiff/automation
python3 -m venv .venv
source .venv/bin/activate
pip install playwright
playwright install chromium
```

## Three-step workflow

### 1. Login (one-time, interactive)

```bash
source .venv/bin/activate
python runway_automation.py --login
```

A visible Chrome opens. Log in to Runway. You should land on the Apps page
with the `∞ Unlimited` badge top-right. Press Enter in the terminal.

### 2. Probe (verify selectors against today's UI)

```bash
python runway_automation.py --probe
```

Walks the UI and reports which selectors match. Writes `selectors.json`. Any
"miss" lines need hand-editing — open Runway, right-click the missing element,
Inspect, copy the ARIA role + name into `selectors.json`. Probe is fast (~30s);
re-run after each edit.

### 3. Run

Test on one shot first:

```bash
python runway_automation.py --run --shot S01
```

If it generates and downloads cleanly to `../clips/S01.mp4`, batch the rest:

```bash
python runway_automation.py --run --limit 5    # next 5 shots
python runway_automation.py --run               # remaining
```

`--dry-run` prints actions without touching the browser.

## What "good" looks like

- `../clips/S01.mp4` ... `../clips/S25.mp4` (minus Act-Two ids)
- `results.json` with `{id, status, path|error}` per shot
- `run.log` with timestamped trace

## Failure handling

- Selector miss → script logs `miss <category>.<key>`. Run `--probe`, edit
  `selectors.json`, retry.
- Generation timeout (>10 min) → shot logged `fail`, others continue. Investigate
  manually then re-run with `--shot <id>`.
- Character drift on first cat appearance (S07) is expected; the script does
  not auto-detect drift. Run `--shot S07` first, eyeball the result, regen by
  hand if needed before letting the rest of the batch run.

## What is NOT automated

- Character creation in the Characters sidebar (Phase 1)
- Act-Two performance capture (Phase 3)
- Drift detection / aesthetic QC (human review per shot)
- DaVinci assembly + ElevenLabs VO + grading (terminal-Claude handles after clips land)
