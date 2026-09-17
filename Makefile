# Root Makefile -- thin wrappers over the backend (FastAPI/uvicorn) and
# frontend (Vite) dev tooling, so contributors don't need to remember each
# service's own run command. Deliberately not a build system: every target
# just shells out to the same commands documented in README.md.

.DEFAULT_GOAL := help

# `dev`'s fail-fast cleanup (below) uses bash's `wait -n <pids...>`, which needs
# an actual bash, not just any POSIX /bin/sh (e.g. dash, this container's default
# SHELL). The dev container guarantees bash; other repo scripts already assume it
# too (see .devcontainer/*.sh shebangs).
SHELL := bash

.PHONY: help backend frontend dev install test

help: ## Show this help
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

backend: ## Run the backend dev server (FastAPI/uvicorn, --reload) on http://localhost:8000 (bound to 0.0.0.0 so the dev container's forwarded port reaches it)
	@if [ ! -x backend/.venv/bin/uvicorn ]; then \
		echo "error: backend/.venv not found (or missing uvicorn)."; \
		echo "  Inside the dev container it's created automatically by .devcontainer/post-create.sh."; \
		echo "  Elsewhere, set it up with:"; \
		echo "    cd backend && python3 -m venv .venv && .venv/bin/pip install -e \".[dev]\""; \
		exit 1; \
	fi
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0

frontend: ## Run the frontend dev server (Vite) on http://localhost:5173 (bound to 0.0.0.0 so the dev container's forwarded port reaches it)
	cd frontend && npm run dev -- --host 0.0.0.0

dev: ## Run backend and frontend dev servers together; Ctrl-C/kill stops both, including uvicorn's reloader and vite's node process
	@# Known limitation: a bare SIGINT sent to only this recipe's top-level `make dev`
	@# PID (not via a real terminal, and not SIGTERM) does nothing -- GNU Make ignores
	@# SIGINT while a recipe's child is running (it defers to the terminal to deliver
	@# interactive Ctrl-C to the whole foreground process group directly), so the trap
	@# below never gets a chance to forward it in that specific case. Interactive
	@# Ctrl-C and `kill -TERM <top-pid>` from another shell both work correctly (each
	@# reaches the trap, which cleans up both process groups); only a standalone
	@# `kill -INT <top-pid>` does not. This is inherent GNU Make behavior, not fixable
	@# from within the recipe's own trap/signal handling -- if `make dev` is ever run
	@# under a supervisor that specifically sends bare SIGINT to just the top PID
	@# (most default to SIGTERM, which already works), it won't stop that way.
	@setsid $(MAKE) backend </dev/null & bpid=$$!; \
	setsid $(MAKE) frontend </dev/null & fpid=$$!; \
	trap 'kill -TERM -$$bpid -$$fpid 2>/dev/null' EXIT INT TERM; \
	wait -n $$bpid $$fpid; status=$$?; \
	kill -TERM -$$bpid -$$fpid 2>/dev/null; \
	wait $$bpid $$fpid 2>/dev/null; \
	exit $$status

install: ## Install backend (venv + pip) and frontend (npm) dependencies
	cd backend && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e ".[dev]"
	cd frontend && npm install

test: ## Run backend (pytest) and frontend (vitest) test suites
	cd backend && .venv/bin/pytest
	cd frontend && npm test
