# fintrade

Stock/portfolio analysis app that signals BUY/SELL/HOLD with a confidence percentage, using Dr. Alexander Elder's Triple Screen methodology.

- Methodology: [docs/Analyse.md](docs/Analyse.md)
- System design: [docs/Architecture.md](docs/Architecture.md) and [docs/architecture/](docs/architecture/)
- Feature task board: [docs/tasks/](docs/tasks/) (`index.json` for the summary, one JSON file per task)
- Claude Code project instructions: [CLAUDE.md](CLAUDE.md)

## Dev container

Development happens inside the dev container in `.devcontainer/` — it has everything preinstalled: Python 3.12, Node 22, git, the GitHub CLI, and Claude Code itself. Open the repo in VS Code (or any [Dev Containers spec](https://containers.dev/) tool) and choose **Reopen in Container**.

On first creation it prints setup instructions for the GitHub MCP server and generating an SSH key, and it **automatically configures git commit signing** (`gpg.format`, `user.signingkey`, `commit.gpgsign`, `allowed_signers`) as soon as a key exists — it can't generate the key or register it on GitHub for you (both need a human decision), but the local git config itself is done for you, not just printed. Re-run any time with `fintrade-help`; see `.devcontainer/setup-help.sh` for the exact logic.

## Quick start (Makefile)

A root-level `Makefile` wraps the backend and frontend dev commands below so you don't
need to remember each service's own invocation:

```bash
make backend   # run the backend dev server (FastAPI/uvicorn --reload) on :8000
make frontend  # run the frontend dev server (Vite) on :5173
make dev       # run both together; Ctrl-C stops both cleanly
make install   # set up backend/.venv and frontend/node_modules
make test      # run backend (pytest) and frontend (vitest) test suites
make e2e       # run the frontend's Playwright end-to-end suite (see "End-to-end tests" below)
make help      # list all targets
```

It's a thin wrapper, not a new build system — every target just shells out to the same
commands documented below and in `docs/architecture/{Backend,Frontend}.md`. `make
backend` prints a clear error pointing at `.devcontainer/post-create.sh` / `pip install
-e ".[dev]"` if `backend/.venv` doesn't exist yet, instead of a raw path-not-found
failure; `make dev` invokes `make backend` as a subprocess of its own recipe (not a
formal Make prerequisite), so that same error surfaces through `make dev` too.

## Backend

Python 3.12+, FastAPI. From `backend/`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest --cov=app --cov-report=term-missing
```

Inside the dev container, this venv is created once by `.devcontainer/post-create.sh` and is meant to persist for the life of the container — don't delete it there. Outside the dev container (e.g. an ad hoc verification pass), treat `.venv/` as ephemeral: recreate it rather than committing it (it's gitignored either way).

To regenerate the committed OpenAPI contract snapshot (`backend/openapi.json`) after changing `app/api/schemas.py` or a route signature:

```bash
python scripts/export_openapi.py
```

### Database migrations

Schema changes go through Alembic (`backend/app/db/migrations/`), wired to `app.db.models.Base.metadata` (autogenerate) and `app.config.get_settings().database_url` (target database — same setting the app itself uses, via the `FINTRADE_DATABASE_URL` env var; see `app/db/migrations/env.py`). Run these from `backend/` with the venv active:

```bash
# Apply all migrations up to the latest (fresh database, or one already tracked by Alembic)
alembic upgrade head

# After changing app/db/models.py: generate a new migration from the model diff, then
# review the generated file in app/db/migrations/versions/ before committing it --
# autogenerate doesn't reliably catch every kind of change (e.g. column renames)
alembic revision --autogenerate -m "describe the change"

# Point a command at a different database for one invocation (e.g. a throwaway file)
FINTRADE_DATABASE_URL="sqlite:///./scratch.db" alembic upgrade head
```

`alembic upgrade head` fails with `table ... already exists` against a database whose tables were created by `app/main.py`'s `Base.metadata.create_all` bootstrap rather than by Alembic (see `docs/architecture/Backend.md` §7) — run `alembic stamp head` instead to mark it as already migrated without re-running the `CREATE TABLE`s.

`alembic stamp head` only produces a *correct* schema if the pre-existing tables already match what the initial migration would create. The one currently-known way they might not: a `positions` table created before `unique=True` was added to `PositionORM.ticker` has the column's index but not as unique. Run `python scripts/fix_schema_drift.py` (idempotent, safe before or after `stamp head`) to fix that specific case — it corrects the index if it's missing or non-unique, does nothing if it's already correct, and fails loudly (non-zero exit) instead of silently succeeding if duplicate ticker rows already exist under the old non-unique index:

```bash
python scripts/fix_schema_drift.py
alembic stamp head
```

## End-to-end tests

`frontend/tests/e2e/` (Playwright Test, config at `frontend/playwright.config.ts`) is a
separate, real-browser test category from the vitest/pytest suites `make test` runs: it
drives an actual running backend + frontend through a real Chromium browser, rather than
mocking the API boundary (vitest+MSW) or calling routers in-process (pytest+`TestClient`).
It is **not** part of the 90% coverage gate (see [Testing.md](docs/architecture/Testing.md))
and is never run by `make test`/`npm test`.

```bash
make e2e                       # from the repo root
# or, equivalent:
cd frontend && npm run test:e2e
cd frontend && npm run test:e2e:ui   # Playwright's interactive UI mode, for debugging
```

Both commands start their own backend and frontend processes (Playwright's `webServer`
config) rather than reusing an already-running `make dev` — always on `:8000`/`:5173`, so
stop any manually-started `make dev`/`make backend`/`make frontend` first. The backend
process is started with `FINTRADE_DATA_PROVIDER_MODE=fixture` (selects
`app.data.fixture_provider.FixtureDataProvider`, a deterministic, no-network market-data
provider serving a handful of synthetic tickers — see that module's docstring) and a
dedicated `backend/e2e.db` SQLite database that's wiped before every run, so the suite never
depends on live yfinance/Stooq calls or leftover portfolio state from a previous run.

The first run downloads a Chromium browser build via `npx playwright install chromium`
(already done in the dev container's `node_modules` cache once installed) and, outside the
dev container's prebuilt image, its system-level dependencies via
`sudo npx playwright install-deps chromium`.

## MCP servers

MCP server configuration lives in `.mcp.json` (project-scoped, shared via git) and in each contributor's local Claude Code config (personal, not shared — used for anything involving a secret).

### GitHub

(Also covered interactively by `fintrade-help` inside the dev container.)

The GitHub MCP server's official remote endpoint currently has a known incompatibility with Claude Code's OAuth flow (dynamic client registration isn't supported by GitHub's auth server, and Claude Code doesn't yet fall back gracefully — see [anthropics/claude-code#38102](https://github.com/anthropics/claude-code/issues/38102)). Use a Personal Access Token instead, added at **local** scope so it never ends up in the shared `.mcp.json`:

1. Create a token at https://github.com/settings/tokens — a fine-grained token scoped to just this repo, or a classic token with the `repo` scope.
2. In a terminal (not through a Claude Code `!` shell passthrough, so the token never lands in a session transcript):
   ```bash
   cd /path/to/fintrade
   claude mcp add --transport http github https://api.githubcopilot.com/mcp/ -s local \
     --header "Authorization: Bearer YOUR_TOKEN_HERE"
   ```
3. Restart Claude Code (or start a fresh session in this directory) to pick up the new server.
4. Verify with `claude mcp get github`.

Do not add the GitHub server at `-s project` with a bearer token — that would commit the token to `.mcp.json`. Project scope is only for servers with no embedded secret.
