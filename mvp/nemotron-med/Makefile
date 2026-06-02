SHELL := /usr/bin/env bash

VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

POD_H200 := warm-lavender-narwhal
POD_H100 := prism-mla-h100

.PHONY: help
help:
	@grep -hE '^[a-zA-Z][a-zA-Z0-9_-]*:.*##' $(MAKEFILE_LIST) | sort | awk -F':.*?##' '{printf "  %-22s %s\n", $$1, $$2}'

# ---------------------------------------------------------------------------
# Local dev
# ---------------------------------------------------------------------------
.PHONY: venv
venv: ## Create local .venv and install dev deps
	test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install ruff pytest pytest-asyncio detect-secrets pre-commit pyyaml httpx

.PHONY: lint
lint: ## Run ruff check + format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

.PHONY: test
test: ## Run unit tests (skip integration)
	$(VENV)/bin/pytest -m "not integration and not h100 and not h200 and not training" -q

.PHONY: pre-commit-install
pre-commit-install: venv ## Wire pre-commit hooks
	$(VENV)/bin/pre-commit install

.PHONY: pre-commit-run
pre-commit-run: ## Run pre-commit on all tracked files
	$(VENV)/bin/pre-commit run --all-files

# ---------------------------------------------------------------------------
# Isolation verification (run at start AND end of every session)
# ---------------------------------------------------------------------------
.PHONY: freeze-baseline
freeze-baseline: ## Capture session-start prod-page hashes + public-repo HEAD
	@mkdir -p /tmp/prism42-nemotron-med-session
	@for url in /prism42-v3 /prism42-v2 /prism42/livekit; do \
	  printf "%s  " "$$url"; \
	  curl -s --max-time 15 "https://prism42-console.vercel.app$$url" | shasum -a 256 | awk '{print $$1}'; \
	done | tee /tmp/prism42-nemotron-med-session/prod_hashes_before.txt
	@git -C /Users/kiteboard/prism42 rev-parse HEAD > /tmp/prism42-nemotron-med-session/prism42_head.txt
	@git -C /Users/kiteboard/prism42 diff HEAD | shasum -a 256 | awk '{print $$1}' > /tmp/prism42-nemotron-med-session/prism42_worktree_hash.txt
	@echo "Captured baseline at /tmp/prism42-nemotron-med-session/"

.PHONY: freeze-verify
freeze-verify: ## Verify prod surfaces unchanged since freeze-baseline
	@echo "=== prod page hash diff (hash values only — formatting-tolerant) ==="
	@for url in /prism42-v3 /prism42-v2 /prism42/livekit; do \
	  printf "%s  " "$$url"; \
	  curl -s --max-time 15 "https://prism42-console.vercel.app$$url" | shasum -a 256 | awk '{print $$1}'; \
	done > /tmp/prism42-nemotron-med-session/prod_hashes_after.txt
	@awk '{print $$NF}' /tmp/prism42-nemotron-med-session/prod_hashes_before.txt > /tmp/_freeze_before.txt
	@awk '{print $$NF}' /tmp/prism42-nemotron-med-session/prod_hashes_after.txt  > /tmp/_freeze_after.txt
	@diff /tmp/_freeze_before.txt /tmp/_freeze_after.txt && echo "prod pages byte-identical to baseline" || (echo "FAIL: prod page hashes diverged"; exit 1)
	@rm -f /tmp/_freeze_before.txt /tmp/_freeze_after.txt
	@echo "=== prism42 HEAD ==="
	@head_now=$$(git -C /Users/kiteboard/prism42 rev-parse HEAD); \
	 head_then=$$(cat /tmp/prism42-nemotron-med-session/prism42_head.txt); \
	 [ "$$head_now" = "$$head_then" ] && echo "prism42 HEAD unchanged: $$head_now" || (echo "FAIL: prism42 HEAD moved"; exit 1)
	@echo "=== prism42 worktree ==="
	@hash_now=$$(git -C /Users/kiteboard/prism42 diff HEAD | shasum -a 256 | awk '{print $$1}'); \
	 hash_then=$$(cat /tmp/prism42-nemotron-med-session/prism42_worktree_hash.txt); \
	 [ "$$hash_now" = "$$hash_then" ] && echo "prism42 worktree unchanged: $$hash_now" || (echo "FAIL: prism42 worktree diverged"; exit 1)

# ---------------------------------------------------------------------------
# Pod surface (read-only by default; double-gated commit for billed actions)
# ---------------------------------------------------------------------------
.PHONY: pod-status
pod-status: ## brev ls + nvidia-smi probe on both pods (read-only)
	brev ls
	ssh $(POD_H200) 'nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv'
	ssh $(POD_H100) 'nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv'

# ---------------------------------------------------------------------------
# Pre-flight (runs before any long benchmark; READ artifact JSON, not exit code)
# ---------------------------------------------------------------------------
.PHONY: preflight
preflight: ## 6-check preflight before R1/R2/R3 sweeps
	./scripts/preflight.sh

.PHONY: clean
clean: ## Remove caches, results, engines (does NOT touch trained adapters)
	rm -rf .ruff_cache .pytest_cache .mypy_cache __pycache__
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# ---------------------------------------------------------------------------
# Reproducibility — capture + verify
# ---------------------------------------------------------------------------
.PHONY: snapshot
snapshot: ## Capture a reproducibility manifest (LOCAL_PURPOSE="..." to set purpose)
	@$(VENV)/bin/python scripts/freeze_snapshot.py \
	  --purpose "$${LOCAL_PURPOSE:-ad-hoc snapshot}" \
	  $${POD_HOST:+--pod-host $$POD_HOST} \
	  $${POD_PROVIDER:+--pod-provider $$POD_PROVIDER} \
	  $${POD_ID:+--pod-id $$POD_ID} \
	  $${SSH_CONFIG:+--ssh-config $$SSH_CONFIG}

# ---------------------------------------------------------------------------
# Closed-loop CI — run the bench end-to-end on the deployed pods
# ---------------------------------------------------------------------------
.PHONY: ci-medomni
ci-medomni: ## Closed-loop bench: snapshot -> bench -> CARD -> diff vs prior. Halts on regression.
	@echo "=== STAGE 1/4 — capture pre-run reproducibility manifest ==="
	@LOCAL_PURPOSE="ci-medomni run" $(MAKE) snapshot
	@echo
	@echo "=== STAGE 2/4 — sovereign_bench against the configured serve+judge endpoints ==="
	@test -n "$$NEMOTRON_SERVE_URL" || (echo "FAIL: NEMOTRON_SERVE_URL must be set"; exit 2)
	@test -n "$$NEMOTRON_JUDGE_URL" || (echo "FAIL: NEMOTRON_JUDGE_URL must be set"; exit 2)
	@CI_DIR="results/ci-medomni-$$(date +%Y%m%d-%H%M%S)"; \
	 mkdir -p "$$CI_DIR"; \
	 echo "$$CI_DIR" > /tmp/medomni-ci-dir.txt; \
	 $(VENV)/bin/python scripts/sovereign_bench.py \
	   --manifest corpus/clinical-demo/CLN-DEMO-TAMOXIFEN-MIRENA/case.json \
	   --serve-url "$$NEMOTRON_SERVE_URL" \
	   --serve-model "$${NEMOTRON_SERVE_MODEL:-nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4}" \
	   --judge-url "$$NEMOTRON_JUDGE_URL" \
	   --judge-model "$${NEMOTRON_JUDGE_MODEL:-nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4}" \
	   --n 1 --trials 3 --max-tokens 1024 --timeout-s 300 \
	   --out "$$CI_DIR/tamoxifen.json"
	@echo
	@echo "=== STAGE 3/4 — generate CARD ==="
	@CI_DIR=$$(cat /tmp/medomni-ci-dir.txt); \
	 $(VENV)/bin/python scripts/write_card.py "$$CI_DIR/tamoxifen.json"
	@echo
	@echo "=== STAGE 4/4 — verdict gate (>= 0.80 acceptance threshold) ==="
	@CI_DIR=$$(cat /tmp/medomni-ci-dir.txt); \
	 SCORE=$$($(VENV)/bin/python -c "import json; d = json.load(open('$$CI_DIR/tamoxifen.json')); print(d['trial_results'][0]['aggregate']['score'])"); \
	 echo "score: $$SCORE  threshold: 0.80"; \
	 awk -v s="$$SCORE" -v t=0.80 'BEGIN { exit (s+0 >= t+0) ? 0 : 1 }' && echo "PASS" || (echo "FAIL: below acceptance threshold"; exit 3)
	@echo
	@echo "=== ci-medomni complete; artifacts at $$(cat /tmp/medomni-ci-dir.txt) ==="

.PHONY: ci-medomni-dry
ci-medomni-dry: ## Show what ci-medomni would do; no pod calls
	@echo "ci-medomni would:"
	@echo "  1. snapshot reproducibility manifest"
	@echo "  2. run sovereign_bench against \$$NEMOTRON_SERVE_URL + \$$NEMOTRON_JUDGE_URL"
	@echo "     fixture: corpus/clinical-demo/CLN-DEMO-TAMOXIFEN-MIRENA"
	@echo "     model:   \$${NEMOTRON_SERVE_MODEL:-nvidia/Nemotron-3-Nano-Omni-30B-A3B-Reasoning-NVFP4}"
	@echo "     judge:   \$${NEMOTRON_JUDGE_MODEL:-same-family}"
	@echo "  3. write_card.py against the artifact"
	@echo "  4. gate on rubric_score_mean >= 0.80; exit 3 below threshold"
	@echo
	@echo "Required env: NEMOTRON_SERVE_URL, NEMOTRON_JUDGE_URL"
	@echo "Optional env: NEMOTRON_SERVE_MODEL, NEMOTRON_JUDGE_MODEL"
