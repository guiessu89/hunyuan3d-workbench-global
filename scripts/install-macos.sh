#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
host="${1:-both}"
if [[ "$(uname)" != Darwin ]]; then
  printf '%s\n' 'Run this installer on macOS.' >&2
  exit 1
fi
command -v python3 >/dev/null || { printf '%s\n' 'Install Python 3.11 or later from python.org.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' || { printf '%s\n' 'Python 3.11 or later is required.' >&2; exit 1; }
if [[ ! -x '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' ]]; then
  printf '%s\n' 'Install Google Chrome in /Applications before using the browser worker.'
fi
case "$host" in
  both|codex) command -v codex >/dev/null || { printf '%s\n' 'Install Codex CLI or select the claude/none host.' >&2; exit 1; };;
  claude|none) ;;
  *) printf '%s\n' 'Choose both, codex, claude, or none.' >&2; exit 1;;
esac
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -I -m hunyuan_workbench --help >/dev/null
.venv/bin/python smoke_mcp.py --installed
.venv/bin/python -I -m mcp_config --host "$host"
