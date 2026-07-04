# Pocket CFO — task runner.
#
# This Makefile is the compatibility shim between the README's documented commands
# (`make generate-traces`, `make grade`) and the ACTUAL Agents CLI subcommands.
# The installed google-agents-cli v1.0.0 has NO `generate-traces` subcommand — the
# real flow is `agents-cli eval generate` (run inference, write traces) then
# `agents-cli eval grade` (LLM-as-judge scorecard). We wrap them here so the
# documented developer experience keeps working.

.PHONY: install playground test unit eval generate-traces grade lint security-scan hooks clean

install:            ## Install project + dev dependencies into .venv (Python 3.11)
	uv sync --python 3.11

playground:         ## Launch the local ADK playground (interactive testing)
	uv run agents-cli playground

test:               ## Run all pytest suites (unit + integration)
	uv run pytest tests/unit tests/integration -v

unit:               ## Run only the fast, deterministic unit tests
	uv run pytest tests/unit -v

# ── LLM-as-judge evaluation (course pattern) ────────────────────────────────
generate-traces:    ## (README alias) Run the agent over the eval dataset -> traces
	uv run agents-cli eval generate

grade:              ## (README alias) Grade the generated traces (1-5 LLM-as-judge)
	uv run agents-cli eval grade

eval: generate-traces grade  ## Full eval loop: generate traces, then grade them

# ── Quality & security ──────────────────────────────────────────────────────
lint:               ## Ruff lint + format check
	uv run ruff check app tests
	uv run ruff format --check app tests

security-scan:      ## Run the full pre-commit security suite on all files
	uv run pre-commit run --all-files

hooks:              ## Install the git pre-commit hook (run once after cloning)
	uv run pre-commit install

clean:              ## Remove caches and eval artifacts
	rm -rf .pytest_cache .ruff_cache artifacts
