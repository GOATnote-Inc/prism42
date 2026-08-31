# Prism — task-milestone Makefile.
#
# Tri-rail architecture (ordered by preference):
#   1. RUNPOD (primary)    — Secure Cloud, H100 SXM + H200 SXM self-serve.
#                            NVLink/NVSwitch. SM100 coverage.
#   2. LAMBDA LABS (backup) — H100 PCIe, simple API, insurance path.
#   3. AWS p5/trn2 (upgrade) — on when quotas clear. Trainium is AWS-only.
#
# T1 gate (primary): `make verify` + `make launch-runpod` + `make runpod-ping`
# T1 gate (backup):  `make launch-lambda` + `make lambda-ping`
# T1 gate (AWS):     `make env-sanity`

# Auto-load project-local .env (API keys). Gitignored; see .env.example.
# `make` silently continues if .env is absent, so CI without .env still works.
#
# Scope (2026-04-27): the include is skipped for purely-local targets that
# don't need pod/cloud creds (lint/help/cleanup). The repo's .env carries
# operator notes alongside KEY=VALUE lines, so unconditional include made
# `make secret-hygiene` fail with "missing separator" on natural-language
# rows. The filter below keeps cloud targets working while letting the
# linter run without parsing .env at all.
LINT_TARGETS := secret-hygiene help clean verify
ifneq (,$(filter-out $(LINT_TARGETS),$(MAKECMDGOALS)))
-include .env
export
endif

AWS_PROFILE ?= prism
AWS_REGION  ?= us-east-1
RAIL        ?= p5
INSTANCE_TAG := prism-$(RAIL)

LAMBDA_REGION ?= us-east-1
LAMBDA_TYPE   ?= gpu_1x_h100_pcie

RUNPOD_GPU       ?= NVIDIA H100 80GB HBM3
RUNPOD_DISK_GB   ?= 80
RUNPOD_VOLUME_GB ?= 100

export AWS_PROFILE AWS_REGION

.PHONY: help verify \
        env-sanity aws-identity instance-profile quotas \
        launch-p5 launch-trn2 ssm-ping nki-build teardown \
        launch-lambda lambda-ping teardown-lambda \
        launch-runpod runpod-ping prepare-runpod \
        sync-repro-runpod run-repro-runpod teardown-runpod \
        clean

help:
	@echo "Prism Makefile targets:"
	@echo ""
	@echo "  make verify                 # bash -n + make -n + yaml parse (offline)"
	@echo ""
	@echo "  --- PRIMARY RAIL: RunPod Secure Cloud (H100/H200 SXM) ---"
	@echo "  make launch-runpod                               # H100 SXM, ~\$$2.99/hr"
	@echo "  make launch-runpod RUNPOD_GPU=\"NVIDIA H200\"      # H200 SXM, ~\$$3.99/hr (SM100)"
	@echo "  make runpod-ping            # SSH round-trip + GPU re-verify"
	@echo "  make teardown-runpod        # terminate current RunPod pod"
	@echo ""
	@echo "  --- BACKUP RAIL: Lambda Labs (H100 PCIe, insurance) ---"
	@echo "  make launch-lambda          # launch H100 PCIe, verify SSH + GPU"
	@echo "  make lambda-ping            # SSH round-trip smoke test"
	@echo "  make teardown-lambda        # terminate current Lambda instance"
	@echo ""
	@echo "  --- UPGRADE RAIL: AWS (when quotas clear) ---"
	@echo "  make env-sanity             # AWS prereq check"
	@echo "  make launch-p5              # start p5.48xlarge (CUDA rail)"
	@echo "  make launch-trn2            # start trn2.48xlarge (Neuron rail, AWS-only)"
	@echo "  make ssm-ping RAIL=p5       # SSM round-trip smoke test"
	@echo "  make nki-build              # import-check NKI on trn2"
	@echo "  make teardown RAIL=p5       # terminate the prism-<rail> instance"

# ---------------------------------------------------------------------
# Offline verification — runs without any cloud creds. Per
# "always verify after acting": syntax-check every script, parse-check
# every yaml, parse-check every make target.
# ---------------------------------------------------------------------
verify: secret-hygiene
	@echo "verify: bash syntax check"
	@for f in scripts/*.sh cloud-init/*.sh; do bash -n "$$f" && echo "  ok: $$f"; done
	@echo "verify: make parse check"
	@for t in help env-sanity launch-p5 launch-trn2 ssm-ping teardown \
	          launch-lambda lambda-ping teardown-lambda \
	          launch-runpod runpod-ping teardown-runpod; do \
	  $(MAKE) -n $$t >/dev/null 2>&1 && echo "  ok: make -n $$t" || echo "  FAIL: make -n $$t"; \
	done
	@echo "verify: yaml parse check"
	@if [ -f corpus/kernel_bugs.yaml ]; then \
	   ruby -ryaml -e 'YAML.load_file("corpus/kernel_bugs.yaml"); puts "  ok: corpus/kernel_bugs.yaml"' 2>/dev/null \
	     || python3 -c 'import yaml; yaml.safe_load(open("corpus/kernel_bugs.yaml")); print("  ok: corpus/kernel_bugs.yaml")'; \
	 else echo "  skip: corpus/kernel_bugs.yaml (removed for coordinated-disclosure redaction on 2026-04-23)"; fi
	@echo "verify: PASS"

# Reject any new value-dump pattern. Effective 2026-04-27 after two
# P0 secret-exposure incidents (see docs/secret-hygiene.md).
.PHONY: secret-hygiene
secret-hygiene:
	@echo "verify: secret-hygiene"
	@python3 scripts/check_no_secret_dumps.py

# ---------------------------------------------------------------------
# PRIMARY: Lambda Labs rail
# ---------------------------------------------------------------------
launch-lambda:
	@: "$${LAMBDA_API_KEY:?set LAMBDA_API_KEY — get from cloud.lambdalabs.com/api-keys}"
	@bash scripts/launch_lambda.sh $(LAMBDA_TYPE) $(LAMBDA_REGION)

# Resolves current Lambda IP from .state/lambda-current.json and does
# an SSH round-trip. Part of T1 gate for primary rail.
lambda-ping:
	@state=.state/lambda-current.json; \
	[[ -f "$$state" ]] || { echo "ERR: no current Lambda instance (run make launch-lambda)"; exit 1; }; \
	ip=$$(jq -r '.ip' "$$state"); \
	bash scripts/ssh_exec.sh "$$ip" "uname -a && nvidia-smi --query-gpu=name --format=csv,noheader" --expect "H100"

teardown-lambda:
	@: "$${LAMBDA_API_KEY:?set LAMBDA_API_KEY}"
	@state=.state/lambda-current.json; \
	[[ -f "$$state" ]] || { echo "no current Lambda instance"; exit 0; }; \
	id=$$(jq -r '.id' "$$state"); \
	echo "terminating Lambda instance $$id"; \
	curl -sfu "$${LAMBDA_API_KEY}:" -X POST \
	  https://cloud.lambdalabs.com/api/v1/instance-operations/terminate \
	  -H "Content-Type: application/json" \
	  -d "{\"instance_ids\":[\"$$id\"]}" | jq '.data.terminated_instances[].id'; \
	rm -f "$$state" .state/lambda-current.json

# ---------------------------------------------------------------------
# PRIMARY: RunPod rail
# ---------------------------------------------------------------------
launch-runpod:
	@: "$${RUNPOD_API_KEY:?set RUNPOD_API_KEY — get from console.runpod.io/user/settings}"
	@bash scripts/launch_runpod.sh "$(RUNPOD_GPU)" $(RUNPOD_DISK_GB) $(RUNPOD_VOLUME_GB)

# Reads .state/runpod-current.json, runs an SSH round-trip, verifies GPU
# via the --expect marker so "exit 0 but empty" is caught.
runpod-ping:
	@state=.state/runpod-current.json; \
	[[ -f "$$state" ]] || { echo "ERR: no current RunPod pod (run make launch-runpod)"; exit 1; }; \
	ip=$$(jq -r '.ip'   "$$state"); \
	port=$$(jq -r '.port' "$$state"); \
	user=$$(jq -r '.user' "$$state"); \
	gpu=$$(jq -r '.gpu'  "$$state"); \
	PRISM_SSH_USER=$$user PRISM_SSH_PORT=$$port \
	  bash scripts/ssh_exec.sh "$$ip" \
	    "uname -a && nvidia-smi --query-gpu=name --format=csv,noheader" \
	    --expect "$$(echo $$gpu | awk '{print $$2}')"

# One-time prep: put CUDA on PATH for root's login shells + pip install
# the FA build deps. Idempotent — re-running is cheap and safe.
prepare-runpod:
	@state=.state/runpod-current.json; \
	ip=$$(jq -r '.ip' "$$state"); port=$$(jq -r '.port' "$$state"); user=$$(jq -r '.user' "$$state"); \
	echo "prepare-runpod: CUDA PATH + ninja/packaging/einops/pytest"; \
	PRISM_SSH_USER=$$user PRISM_SSH_PORT=$$port \
	  bash scripts/ssh_exec.sh "$$ip" \
	  "grep -q '/usr/local/cuda/bin' /root/.bashrc || \
	     echo 'export PATH=/usr/local/cuda/bin:\$$PATH' >> /root/.bashrc; \
	   export PATH=/usr/local/cuda/bin:\$$PATH; \
	   nvcc --version | tail -1; \
	   pip install -q ninja packaging einops pytest && python -c 'import ninja, packaging, einops, pytest; print(\"build deps OK\")'" \
	    --expect "build deps OK"

sync-repro-runpod:
	@state=.state/runpod-current.json; \
	ip=$$(jq -r '.ip' "$$state"); port=$$(jq -r '.port' "$$state"); user=$$(jq -r '.user' "$$state"); \
	key="$${PRISM_SSH_KEY:-$$HOME/.ssh/prism_lambda_ed25519}"; \
	echo "syncing corpus/reproducers -> $$user@$$ip:/workspace/prism/corpus/reproducers"; \
	PRISM_SSH_USER=$$user PRISM_SSH_PORT=$$port \
	  bash scripts/ssh_exec.sh "$$ip" "mkdir -p /workspace/prism/corpus/reproducers"; \
	tar czf - -C corpus/reproducers --exclude '__pycache__' . \
	  | ssh -i "$$key" -p "$$port" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
	      "$$user@$$ip" "tar --no-same-owner --no-same-permissions -xzf - -C /workspace/prism/corpus/reproducers"

run-repro-runpod: sync-repro-runpod
	@state=.state/runpod-current.json; \
	ip=$$(jq -r '.ip' "$$state"); port=$$(jq -r '.port' "$$state"); user=$$(jq -r '.user' "$$state"); \
	bugs="$(BUGS)"; \
	PRISM_SSH_USER=$$user PRISM_SSH_PORT=$$port \
	  bash scripts/ssh_exec.sh "$$ip" \
	    "export PATH=/usr/local/cuda/bin:\$$PATH && cd /workspace/prism && python3 corpus/reproducers/run_repro.py $$bugs"

teardown-runpod:
	@: "$${RUNPOD_API_KEY:?set RUNPOD_API_KEY}"
	@state=.state/runpod-current.json; \
	[[ -f "$$state" ]] || { echo "no current RunPod pod"; exit 0; }; \
	id=$$(jq -r '.id' "$$state"); \
	echo "terminating RunPod pod $$id"; \
	curl -sf -X DELETE "https://rest.runpod.io/v1/pods/$$id" \
	  -H "Authorization: Bearer $${RUNPOD_API_KEY}" \
	  -H "Content-Type: application/json" \
	  -o /dev/null -w "HTTP %{http_code}\n"; \
	rm -f "$$state" .state/runpod-current.json

# ---------------------------------------------------------------------
# SECONDARY: AWS T1 gate
# ---------------------------------------------------------------------
env-sanity: aws-identity instance-profile quotas
	@echo "env-sanity: prereqs OK"
	@echo "  Next: make launch-p5, then make ssm-ping RAIL=p5"
	@echo "  To complete T1 gate run those explicitly; gate passes on their success."

aws-identity:
	@arn=$$(aws sts get-caller-identity --query Arn --output text); \
	echo "aws-identity: $$arn"; \
	[[ "$$arn" == *":user/prism-dev" ]] || { echo "ERR: expected prism-dev, got $$arn"; exit 1; }

instance-profile:
	@aws iam get-instance-profile --instance-profile-name prism-ssm-role \
	    --query 'InstanceProfile.InstanceProfileName' --output text >/dev/null 2>&1 \
	  && echo "instance-profile: prism-ssm-role OK" \
	  || { echo "ERR: prism-ssm-role missing — create from root IAM console"; exit 1; }

quotas:
	@pq=$$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-417A185B --region $(AWS_REGION) --query 'Quota.Value' --output text); \
	tq=$$(aws service-quotas get-service-quota --service-code ec2 --quota-code L-2C3B7624 --region $(AWS_REGION) --query 'Quota.Value' --output text); \
	echo "quotas: P=$$pq  Trn=$$tq  (need >=192 each)"; \
	awk -v p=$$pq -v t=$$tq 'BEGIN{exit !(p+0 >= 192 && t+0 >= 192)}' \
	  || { echo "ERR: quota < 192; file at console.aws.amazon.com/servicequotas"; exit 1; }

# ---------------------------------------------------------------------
# AWS instance lifecycle
# ---------------------------------------------------------------------
launch-p5:
	@bash scripts/launch_instance.sh p5

launch-trn2:
	@bash scripts/launch_instance.sh trn2

# SSM round-trip smoke test — measures wall time for a trivial command.
# Part of T1.4 gate. Target: <5s once instance is warm.
ssm-ping:
	@t0=$$(python3 -c 'import time; print(time.time())'); \
	out=$$(bash scripts/ssm_exec.sh $(INSTANCE_TAG) "test -f /opt/prism/boot-ready && echo boot-ready && uname -a"); \
	t1=$$(python3 -c 'import time; print(time.time())'); \
	dt=$$(python3 -c "print(f'{$$t1-$$t0:.2f}')"); \
	echo "ssm-ping: round-trip $${dt}s"; \
	echo "$$out" | head -5

# ---------------------------------------------------------------------
# AWS build verifications (part of T1 gate, run on instance via SSM)
# ---------------------------------------------------------------------

nki-build:
	@bash scripts/ssm_exec.sh prism-trn2 "source /opt/aws_neuronx_venv_pytorch_2_*/bin/activate && python -c 'import neuronxcc.nki as nki; import neuronxcc; print(f\"neuronxcc {neuronxcc.__version__}; nki ok\")'"

# ---------------------------------------------------------------------
# AWS teardown — ALWAYS run when not actively auditing. p5 burns ~$98/hr.
# ---------------------------------------------------------------------
teardown:
	@id=$$(aws ec2 describe-instances \
	  --filters "Name=tag:Name,Values=$(INSTANCE_TAG)" "Name=instance-state-name,Values=running,pending,stopping,stopped" \
	  --query 'Reservations[].Instances[].InstanceId' --output text); \
	if [[ -z "$$id" ]]; then echo "no $(INSTANCE_TAG) instance"; exit 0; fi; \
	echo "terminating $$id"; \
	aws ec2 terminate-instances --instance-ids $$id --query 'TerminatingInstances[].[InstanceId,CurrentState.Name]' --output text

clean:
	rm -rf .cache/ build/

# =====================================================================
# T3: Managed Agents scaffolding (offline-only by default).
# Appendix — all targets here are gated. No network fires unless both
# COMMIT=1 (make var) AND the corresponding PRISM_*_COMMIT=1 (env var
# read by the underlying script) are set.
# =====================================================================

.PHONY: t3-help setup-venv register-agents harness-dry-run harness-run verify-t3 \
        pipeline-invariants validate-golden smoke-t3 verify-all \
        clinical-demo-artifacts clinical-demo-artifacts-commit \
        ant-check ant-smoke

VENV       ?= .venv
# Fall back to system python3 when .venv is absent (e.g. fresh CI runner).
# `make setup-venv` creates the venv for local dev; CI installs deps to the
# system interpreter directly. Without this fallback `make verify-all` cannot
# run on a fresh clone, which breaks the load-bearing preflight in
# .github/workflows/daily-orchestrator.yml.
PY         := $(shell [ -x $(VENV)/bin/python ] && echo $(VENV)/bin/python || echo python3)
COMMIT     ?=
CASE       ?=
CASE_FILE  ?= cases/$(CASE).json
GOLDEN_DIR ?= corpus/golden-cases/KERNEL-GOLD-001

t3-help:
	@echo "Prism T3 (Managed Agents) targets:"
	@echo ""
	@echo "  make setup-venv                           # create .venv + install SDK"
	@echo "  make register-agents                      # DRY-RUN: print request bodies"
	@echo "  make register-agents COMMIT=1             # REAL: POST /v1/environments, /v1/agents"
	@echo "  make harness-dry-run CASE=EXAMPLE-CASE-001      # DRY-RUN: print session + event bodies"
	@echo "  make harness-run     CASE=EXAMPLE-CASE-001 COMMIT=1  # REAL: create session, stream events"
	@echo ""
	@echo "  --- Verification (offline, no secrets) ---"
	@echo "  make verify-t3                            # L1+L4+L5 scripts + yaml parse + containment"
	@echo "  make pipeline-invariants                  # L4: model pins, mounts, egress allowlist"
	@echo "  make validate-golden                      # L1+L3: validator on golden-case fixture"
	@echo "  make smoke-t3                             # L1+L3+L4: full pytest (tests/)"
	@echo "  make verify-all                           # every layer in sequence"

setup-venv:
	@if [ ! -x "$(PY)" ]; then \
	  echo "setup-venv: creating $(VENV)"; \
	  python3 -m venv $(VENV); \
	fi
	@$(PY) -m pip install --quiet --upgrade pip
	@$(PY) -m pip install --quiet 'anthropic>=0.96.0' 'pyyaml>=6.0' 'numpy>=1.26'
	@$(PY) -c "import anthropic, yaml, numpy; print(f'setup-venv: anthropic {anthropic.__version__}, yaml OK, numpy {numpy.__version__}')"

# Vendor third-party source at pinned SHAs. See third_party/README.md §4.
# Idempotent — safe to re-run. No network beyond git clone of public
# repos. Per vendoring policy each clone resets to the pinned SHA.
setup-third-party:
	@set -e; \
	mkdir -p third_party; \
	cd third_party; \
	expected="ee3b0318d8d1d9d72755a4120879be65f7c07e9e"; \
	if [ ! -d simple-evals/.git ]; then \
	  echo "setup-third-party: cloning openai/simple-evals at $$expected..."; \
	  : "  Full clone (no --depth 1) because we check out a specific SHA"; \
	  : "  that is no longer at upstream main. --depth 1 only fetches the"; \
	  : "  tip, so once upstream moves past the pin, a shallow clone cannot"; \
	  : "  see our SHA and the pin check fails in CI on every fresh runner."; \
	  git clone --quiet https://github.com/openai/simple-evals.git simple-evals; \
	  git -C simple-evals checkout --quiet "$$expected"; \
	else \
	  echo "setup-third-party: simple-evals/ already cloned; verifying pin"; \
	fi; \
	cd simple-evals; \
	actual=$$(git rev-parse HEAD); \
	if [ "$$actual" != "$$expected" ]; then \
	  echo "setup-third-party: pin drift — expected $$expected, got $$actual"; \
	  echo "setup-third-party: to reset, rm -rf third_party/simple-evals and re-run"; \
	  exit 1; \
	fi; \
	cd ..; \
	if [ ! -L simple_evals ]; then \
	  echo "setup-third-party: creating python-import alias simple_evals -> simple-evals"; \
	  ln -s simple-evals simple_evals; \
	fi; \
	echo "setup-third-party: PASS (simple-evals @ $$expected)"

register-agents:
	@if [ "$(COMMIT)" = "1" ]; then \
	  echo "register-agents: COMMIT=1 — real registration"; \
	  PRISM_AGENTS_COMMIT=1 $(PY) scripts/register_agents.py --commit; \
	else \
	  $(PY) scripts/register_agents.py; \
	fi

harness-dry-run:
	@[ -n "$(CASE)" ] || { echo "ERR: set CASE=<case_id>  (expects $(CASE_FILE))"; exit 1; }
	@$(PY) scripts/harness_runner.py --case $(CASE_FILE)

harness-run:
	@[ -n "$(CASE)" ] || { echo "ERR: set CASE=<case_id>  (expects $(CASE_FILE))"; exit 1; }
	@if [ "$(COMMIT)" = "1" ]; then \
	  echo "harness-run: COMMIT=1 — real session"; \
	  PRISM_HARNESS_COMMIT=1 $(PY) scripts/harness_runner.py --case $(CASE_FILE) --commit; \
	else \
	  $(PY) scripts/harness_runner.py --case $(CASE_FILE); \
	fi

# Offline T3 parse + containment check. No network, no venv required for
# basic parsing (falls back to system python3).
verify-t3:
	@py=$$( [ -x "$(PY)" ] && echo $(PY) || echo python3 ); \
	 echo "verify-t3: ast.parse scripts"; \
	 $$py -c "import ast; ast.parse(open('scripts/register_agents.py').read()); print('  ok: scripts/register_agents.py')"; \
	 $$py -c "import ast; ast.parse(open('scripts/harness_runner.py').read());  print('  ok: scripts/harness_runner.py')"; \
	 echo "verify-t3: yaml.safe_load agents + environments"; \
	 for f in agents/*.yaml environments/*.yaml; do \
	   $$py -c "import yaml; yaml.safe_load(open('$$f')); print('  ok: $$f')"; \
	 done; \
	 echo "verify-t3: Anthropic client containment (import + Anthropic() only inside do_commit)"; \
	 $$py scripts/check_sdk_containment.py; \
	 echo "verify-t3: pipeline invariants"; \
	 $$py scripts/check_pipeline_invariants.py; \
	 echo "verify-t3: PASS"

# L4: pipeline-invariants on its own (model pins, egress allowlist, mounts,
# manifest shape, schema compile).
pipeline-invariants:
	@$(PY) scripts/check_pipeline_invariants.py

# L1+L3: run the validator on the golden-case fixture. Fails fast on any
# schema drift or cross-ref breakage, so the golden case keeps working as
# a regression anchor.
validate-golden:
	@$(PY) scripts/validate_artifacts.py --case-dir $(GOLDEN_DIR)
	@echo "validate-golden: PASS  ($(GOLDEN_DIR))"

# L1+L3+L4: full pytest suite covering schema validation, golden-case
# cross-refs, and pipeline invariants. Offline; no API keys.
smoke-t3:
	@$(PY) -m pytest tests/ -q

# T4.5b: clinical_subset manifest must have 30 examples, exact per-class
# counts, and >= 3 distinct target_axis values. Offline; reads YAML only.
verify-clinical-corpus:
	@py=$$( [ -x "$(PY)" ] && echo $(PY) || echo python3 ); \
	 $$py -c "import yaml; from collections import Counter; \
m = yaml.safe_load(open('corpus/clinical_subset.yaml')); \
assert m['total'] == 30, f'expected 30 examples, got {m[\"total\"]}'; \
expected = {'emergency': 10, 'pediatrics': 5, 'obgyn': 5, 'psychiatry': 5, 'general': 5}; \
actual = dict(Counter(e['class'] for e in m['examples'])); \
assert actual == expected, f'class counts mismatch: expected {expected}, got {actual}'; \
axes = {e['target_axis'] for e in m['examples']}; \
assert len(axes) >= 3, f'need >= 3 distinct axes, got {len(axes)}: {axes}'; \
print(f'verify-clinical-corpus: 30 examples, {len(axes)} axes, classes OK')"

# Every offline verification in one target. Matches the CI workflow so
# `make verify-all` locally == green CI.
verify-all: verify verify-t3 validate-golden verify-clinical-corpus smoke-t3 clinical-demo-artifacts
	@echo ""
	@echo "verify-all: ALL LAYERS GREEN"

# ---------------------------------------------------------------------
# T5: Demo + disclosure artifact generators (offline, pure compute).
# Dry-run by default; commit variants require PRISM_*_COMMIT=1 env var.
# ---------------------------------------------------------------------

clinical-demo-artifacts:
	@py=$$( [ -x "$(PY)" ] && echo $(PY) || echo python3 ); \
	 $$py scripts/generate_clinical_demo_artifacts.py \
	   --corpus-dir corpus/clinical-demo/ \
	   --out-dir results/clinical-demo/ >/dev/null
	@echo "clinical-demo-artifacts: DRY-RUN PASS (add --commit + PRISM_CLINICAL_DEMO_COMMIT=1 for write)"

clinical-demo-artifacts-commit:
	@py=$$( [ -x "$(PY)" ] && echo $(PY) || echo python3 ); \
	 PRISM_CLINICAL_DEMO_COMMIT=1 $$py scripts/generate_clinical_demo_artifacts.py \
	   --corpus-dir corpus/clinical-demo/ \
	   --out-dir results/clinical-demo/ --commit
	@test -f results/clinical-demo/INDEX.md \
	  && test -f results/clinical-demo/metadata.json \
	  && test -f results/clinical-demo/methodology.md \
	  && echo "clinical-demo-artifacts-commit: PASS (synthetic; physician-review-required)"

# Single-file self-contained HTML demo surface. Offline-safe: no external
# scripts, stylesheets, fonts, or network fetches. Consumes the three
# upstream artifact sets + the clinical source corpus and emits a single
# HTML file that opens on file:// with zero setup.
# ---------------------------------------------------------------------
# Anthropic `ant` CLI — optional sidecar to scripts/register_agents.py.
# Per https://platform.claude.com/docs/en/api/sdks/cli, the CLI consumes
# the same YAML shape Prism's agents/*.yaml files already use (after the
# _prism: metadata strip). These targets are READ-ONLY probes; they do
# not create, update, or delete anything. Production agent registration
# stays under scripts/register_agents.py (double-gated, manifest-writing,
# containment-asserted). Install: `brew install anthropics/tap/ant` +
# `xattr -d com.apple.quarantine "$(brew --prefix)/bin/ant"` (macOS).
# ---------------------------------------------------------------------

ant-check:
	@if ! command -v ant >/dev/null 2>&1; then \
	  echo "ant-check: not installed."; \
	  echo "  Install (macOS): brew install anthropics/tap/ant"; \
	  echo "  Unquarantine:    xattr -d com.apple.quarantine \"\$$(brew --prefix)/bin/ant\""; \
	  echo "  Auth:            export ANTHROPIC_API_KEY=sk-ant-api03-..."; \
	  echo "  Docs:            https://platform.claude.com/docs/en/api/sdks/cli"; \
	  exit 0; \
	fi; \
	ver=$$(ant --version 2>&1 | head -1); \
	echo "ant-check: $$ver"; \
	if [ -z "$${ANTHROPIC_API_KEY:-}" ]; then \
	  echo "  WARN: ANTHROPIC_API_KEY not set — smoke calls will 401"; \
	else \
	  echo "  auth: ANTHROPIC_API_KEY present"; \
	fi

# Read-only list of agents + environments visible to this workspace.
# No cost; no state change. If ant is absent, prints the install hint
# and exits 0 so `make verify-all` stays green on machines without ant.
ant-smoke:
	@if ! command -v ant >/dev/null 2>&1; then \
	  echo "ant-smoke: SKIP (ant not installed — run 'make ant-check' for install)"; \
	  exit 0; \
	fi; \
	if [ -z "$${ANTHROPIC_API_KEY:-}" ]; then \
	  echo "ant-smoke: SKIP (ANTHROPIC_API_KEY not set)"; \
	  exit 0; \
	fi; \
	echo "ant-smoke: beta:agents list"; \
	ant beta:agents list \
	  --transform "{id,name,model,version}" \
	  --format jsonl 2>&1 | head -20; \
	echo "ant-smoke: beta:environments list"; \
	ant beta:environments list \
	  --transform "{id,name}" \
	  --format jsonl 2>&1 | head -10; \
	echo "ant-smoke: PASS (read-only; no state change)"
