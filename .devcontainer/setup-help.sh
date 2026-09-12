#!/usr/bin/env bash
set -uo pipefail

SSH_KEY="$HOME/.ssh/id_ed25519"

# Applies the git-signing half of step 3 automatically once a key exists —
# nothing here can create the key or register it on GitHub, both of which
# need a human decision/action, but the local git config itself doesn't.
configure_git_signing() {
  if [ ! -f "${SSH_KEY}.pub" ]; then
    return 1
  fi
  git config --global gpg.format ssh
  git config --global user.signingkey "${SSH_KEY}.pub"
  git config --global commit.gpgsign true

  local email
  email="$(git config --global user.email 2>/dev/null || true)"
  if [ -n "$email" ]; then
    local allowed_signers="$HOME/.ssh/allowed_signers"
    touch "$allowed_signers"
    local line="$email $(cat "${SSH_KEY}.pub")"
    grep -Fq "$line" "$allowed_signers" || echo "$line" >> "$allowed_signers"
    git config --global gpg.ssh.allowedSignersFile "$allowed_signers"
  fi
  return 0
}

cat <<'EOF'

fintrade dev container — one-time setup
========================================

This container generates and keeps its OWN SSH key in an isolated volume
(fintrade-ssh-<container id>), NOT your host's real ~/.ssh. That's
deliberate: Claude Code runs with substantial autonomy in this container,
and Claude Code's own dev container guidance specifically warns against
mounting host secrets like ~/.ssh into a container it operates in. If this
container is ever compromised, only this one container-scoped key is at
risk — and it's trivial to revoke on GitHub without touching your main key.

Prerequisite — set your git identity if you haven't already:
    git config --global user.name "Your Name"
    git config --global user.email "you@example.com"

1) GitHub MCP server (lets Claude Code use GitHub tools directly)
   - Create a token at: https://github.com/settings/tokens
     (a fine-grained token scoped to just this repo, or a classic token
     with the `repo` scope)
   - Run (local scope keeps the token out of the shared, committed .mcp.json):
       claude mcp add --transport http github https://api.githubcopilot.com/mcp/ \
         -s local --header "Authorization: Bearer YOUR_TOKEN_HERE"
   - Verify: claude mcp get github
   - Background on why OAuth doesn't work here: README.md, "MCP servers"

2) SSH authentication key (for git push/pull over SSH)
   - Skip this step if ~/.ssh/id_ed25519 already exists — it persists across
     container rebuilds via the volume mount.
   - Otherwise generate one:
       ssh-keygen -t ed25519 -C "you@example.com (fintrade devcontainer)"
   - Print the public key to copy:
       cat ~/.ssh/id_ed25519.pub
   - Add it at https://github.com/settings/keys -> "New SSH key"
     -> Key type: Authentication Key

3) SSH commit signing (sign commits with the same key)
   - The local git config below is applied AUTOMATICALLY by this script once
     your key exists (see status at the bottom) — shown here for reference,
     you don't need to run these yourself:
       git config --global gpg.format ssh
       git config --global user.signingkey ~/.ssh/id_ed25519.pub
       git config --global commit.gpgsign true
   - What this script CANNOT do for you: add the SAME public key again at
     https://github.com/settings/keys -> "New SSH key" -> Key type: Signing
     Key. GitHub records authentication and signing as two separate
     registrations, even for identical key material — you must do this on
     GitHub's website yourself.

Re-run this any time with: fintrade-help
EOF

echo ""
if configure_git_signing; then
  echo "==> git is configured to sign commits with ${SSH_KEY}.pub"
  echo "    (gpg.format=ssh, commit.gpgsign=true$( [ -n "$(git config --global user.email 2>/dev/null || true)" ] && echo ", allowed_signers set" ))"
  echo "    Still needed, if you haven't: register this public key on GitHub as a Signing Key (step 3 above)."
else
  echo "==> No SSH key found yet at ${SSH_KEY} — generate one (step 2 above)."
  echo "    Once it exists, re-run 'fintrade-help' and this script will configure git signing for you automatically."
fi
