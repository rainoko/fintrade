#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/fintrade

echo "==> Setting up backend virtualenv (persistent — do not delete inside the devcontainer)"
if [ -d backend ]; then
  (cd backend && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e ".[dev]")
fi

echo "==> Enabling Corepack (provisions the Yarn version pinned in frontend/package.json's packageManager field / frontend/.yarnrc.yml)"
corepack enable

echo "==> Fixing ownership on persistent Claude Code config volume"
mkdir -p ~/.claude
sudo chown -R "$(id -u):$(id -g)" ~/.claude

echo "==> Preparing persistent SSH volume (container-scoped, not your host's ~/.ssh)"
mkdir -p ~/.ssh
sudo chown -R "$(id -u):$(id -g)" ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null || true
sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts

echo "==> Fetching the optional IBKR Client Portal Gateway (docs/architecture/Backend.md §8)"
echo "    Not started automatically -- FINTRADE_IBKR_ENABLED stays false until you run it"
echo "    yourself (bin/run.sh root/conf.yaml from the directory below) and log in interactively."
IBKR_GATEWAY_DIR="$HOME/ibkr/clientportal.gw"
if [ ! -d "$IBKR_GATEWAY_DIR" ]; then
  mkdir -p "$IBKR_GATEWAY_DIR"
  TMP_ZIP="$(mktemp)"
  # The zip extracts flat (bin/, dist/, doc/, build/ at its own root -- no
  # top-level clientportal.gw/ folder inside it), so unzip straight into the
  # target directory rather than into a parent and moving a subfolder.
  if curl -fsSL -o "$TMP_ZIP" "https://download2.interactivebrokers.com/portal/clientportal.gw.zip"; then
    unzip -q "$TMP_ZIP" -d "$IBKR_GATEWAY_DIR"
    chmod +x "$IBKR_GATEWAY_DIR"/bin/*.sh 2>/dev/null || true
  else
    echo "    Download failed (offline / IBKR host unreachable) -- skipping, not fatal."
    rmdir "$IBKR_GATEWAY_DIR" 2>/dev/null || true
  fi
  rm -f "$TMP_ZIP"
fi

echo "==> Adding fintrade-help shortcut"
ALIAS_LINE='alias fintrade-help="bash /workspaces/fintrade/.devcontainer/setup-help.sh"'
REMINDER_LINE='echo "fintrade: first time in this container? run: fintrade-help   (GitHub MCP, SSH auth key, SSH commit signing)"'
for rc in ~/.bashrc ~/.zshrc; do
  if [ -f "$rc" ]; then
    grep -Fq "$ALIAS_LINE" "$rc" || echo "$ALIAS_LINE" >> "$rc"
    grep -Fq "$REMINDER_LINE" "$rc" || echo "$REMINDER_LINE" >> "$rc"
  fi
done

echo ""
echo "############################################################"
bash /workspaces/fintrade/.devcontainer/setup-help.sh
echo "############################################################"
