#!/usr/bin/env bash
set -euo pipefail

cd /workspaces/fintrade

echo "==> Setting up backend virtualenv (persistent — do not delete inside the devcontainer)"
if [ -d backend ]; then
  (cd backend && python3 -m venv .venv && .venv/bin/pip install --upgrade pip && .venv/bin/pip install -e ".[dev]")
fi

echo "==> Preparing persistent SSH volume (container-scoped, not your host's ~/.ssh)"
mkdir -p ~/.ssh
sudo chown -R "$(id -u):$(id -g)" ~/.ssh
chmod 700 ~/.ssh
touch ~/.ssh/known_hosts
chmod 644 ~/.ssh/known_hosts
ssh-keyscan -t ed25519 github.com >> ~/.ssh/known_hosts 2>/dev/null || true
sort -u ~/.ssh/known_hosts -o ~/.ssh/known_hosts

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
