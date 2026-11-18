#!/usr/bin/env bash
# Dev launcher: the guide persona with no workspace. Replaced by `deepdive init` (V0-09); delete then.
set -euo pipefail
repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
home="${DEEPDIVE_HOME:-$HOME/.deepdive}"
scratch="$home/guide-dev"
mkdir -p "$scratch"
# strip the leading front matter block (first --- to the next ---)
body() { awk 'NR==1 && $0=="---" {f=1; next} f && $0=="---" {f=0; next} !f' "$1"; }
prompt="$(body "$repo/src/deepdive/personas/_shared.md")

$(body "$repo/src/deepdive/personas/guide.md")"
mcp="{\"mcpServers\":{\"deepdive\":{\"command\":\"uv\",\"args\":[\"run\",\"--project\",\"$repo\",\"deepdive\",\"mcp\",\"serve\"]}}}"
cd "$scratch"
exec claude --strict-mcp-config --mcp-config "$mcp" --tools "" \
  --allowedTools "mcp__deepdive__*" --append-system-prompt "$prompt" "$@"
