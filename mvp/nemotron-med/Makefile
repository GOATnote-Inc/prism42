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
