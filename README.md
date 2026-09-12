# fintrade

Stock/portfolio analysis app that signals BUY/SELL/HOLD with a confidence percentage, using Dr. Alexander Elder's Triple Screen methodology.

- Methodology: [docs/Analyse.md](docs/Analyse.md)
- System design: [docs/Architecture.md](docs/Architecture.md) and [docs/architecture/](docs/architecture/)
- Feature task board: [docs/tasks/](docs/tasks/) (`index.json` for the summary, one JSON file per task)
- Claude Code project instructions: [CLAUDE.md](CLAUDE.md)

## Dev container

Development happens inside the dev container in `.devcontainer/` — it has everything preinstalled: Python 3.12, Node 22, git, the GitHub CLI, and Claude Code itself. Open the repo in VS Code (or any [Dev Containers spec](https://containers.dev/) tool) and choose **Reopen in Container**.

On first creation it prints setup instructions for the GitHub MCP server and generating an SSH key, and it **automatically configures git commit signing** (`gpg.format`, `user.signingkey`, `commit.gpgsign`, `allowed_signers`) as soon as a key exists — it can't generate the key or register it on GitHub for you (both need a human decision), but the local git config itself is done for you, not just printed. Re-run any time with `fintrade-help`; see `.devcontainer/setup-help.sh` for the exact logic.

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
