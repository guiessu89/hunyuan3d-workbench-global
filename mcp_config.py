"""Install or remove this project's MCP registrations in the local hosts."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

NAME = 'hunyuan3d-global'


def backup(path):
    if path.is_file():
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        shutil.copy2(path, path.with_name(path.name + '.' + stamp + '.bak'))


def update_claude(path, python, remove=False):
    data = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    if not isinstance(data, dict):
        raise ValueError('Claude configuration must be a JSON object')
    servers = data.setdefault('mcpServers', {})
    if not isinstance(servers, dict):
        raise ValueError('Claude mcpServers must be a JSON object')
    if remove:
        if NAME not in servers:
            return
        del servers[NAME]
    else:
        servers[NAME] = {'command': str(python), 'args': ['-I', '-m', 'hunyuan_workbench', '--site', 'global', 'mcp']}
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    try:
        if path.exists():
            shutil.copymode(path, temp)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def codex_config(python, remove):
    codex = shutil.which('codex')
    if not codex:
        raise ValueError('Codex CLI is missing. Install it and place codex on PATH.')
    address = Path(os.getenv('CODEX_HOME') or Path.home() / '.codex').expanduser() / 'config.toml'
    backup(address)
    args = ['remove', NAME] if remove else [
        'add', NAME, '--', str(python), '-I', '-m', 'hunyuan_workbench', '--site', 'global', 'mcp']
    if sys.platform == 'win32' and codex.lower().endswith(('.cmd', '.bat')):
        # Invoke an npm-generated command shim without passing a shell command line.
        node = Path(codex).parent / 'node_modules/@openai/codex/bin/codex.js'
        if not node.is_file():
            raise ValueError('Use the standalone Codex executable or a standard npm installation.')
        command = ['node', str(node)]
    else:
        command = [codex]
    if remove and subprocess.run(command + ['mcp', 'get', NAME], capture_output=True).returncode:
        return
    subprocess.run(command + ['mcp'] + args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', choices=('both', 'codex', 'claude', 'none'), default='both')
    parser.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    python = Path(sys.executable).absolute()
    if args.host in {'both', 'codex'}:
        codex_config(python, args.remove)
    if args.host in {'both', 'claude'}:
        if sys.platform == 'win32':
            if not os.getenv('APPDATA'):
                raise ValueError('APPDATA is required for the Claude Desktop configuration')
            directory = Path(os.environ['APPDATA']) / 'Claude'
        elif sys.platform == 'darwin':
            directory = Path.home() / 'Library/Application Support/Claude'
        else:
            raise ValueError('Claude Desktop registration is available on Windows and macOS')
        update_claude(directory / 'claude_desktop_config.json', python, args.remove)


if __name__ == '__main__':
    main()
