# Workbench architecture

`command_api.py` exposes the SQLite ledger and queued browser actions through both CLI and stdio MCP. `hunyuan_workbench.py` validates, copies and hashes inputs, deduplicates jobs, enforces state transitions and archives downloads. `features.py` validates JSON specifications and reports site capabilities.

`site_adapters.py` selects an official origin, route and page guard. Jobs without a site tag belong to China. The two sites use separate default state roots and profiles. The worker serializes commands via its local file queue. Global requests are tied to the active worker so they cannot replay after a restart.

`studio_adapter.py` dispatches by site. The Global geometry implementation in `global_adapter.py` targets an English form contract which still needs signed-in observation. It verifies upload previews and form selection and saves a browser form signature. A separate submission request checks the signature, form route, positive visible quota, enabled button and observable asset panel before reserving exactly one click in SQLite. An inconclusive submission stays blocked from retry. `lifecycle.py` tracks the actual new card, persists a matching completed thumbnail and verifies asset selection before exporting. The archived copy is validated and hashed.

`mcp_config.py` uses the host's command for Codex configuration and updates only the named Claude Desktop entry, backing up the config. GitHub holds source and development history. Profiles, ledgers, references and exports stay in local user data. The browser worker requires a running machine and desktop. The Cloud Browser used for inspection and the worker have separate sign-in sessions.
