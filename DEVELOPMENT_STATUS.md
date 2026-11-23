# Development status

Branch: `feature/hunyuan3d-global`. The latest milestone is the commit containing this file. Run `git log -1 --oneline` for the exact revision. Baseline fork main was `0659359`.

This milestone connects experimental Global geometry to the CLI, persistent browser worker and MCP server. The original China paths remain available with explicit site selection. The Windows and macOS installers register Codex and Claude Desktop with configuration backups. See [architecture](ARCHITECTURE.md) and [compatibility](COMPATIBILITY.md).

Cloud Chrome opened the international geometry URL on 2026-11-23 and redirected to `/login`. It showed **Start Using** and a feature consolidation notice naming Geometry Generation, Texture Painting and Retopology. The signed-in controls, account quota, and existing asset exports are unverified. No generation was submitted and no credits were spent.

Cloud Linux passed 35 offline tests, including existing China fixtures and Global fixture upload, quota, submission and GLB export. The wheel and source distribution built successfully, and the installed wheel passed the CLI help and stdio smoke tests. The stdio smoke test verified 20 tools, preserving the original 19 and adding asset inspection. The production worker keeps Chromium sandboxed. Only intercepted offline fixtures used the override needed by the managed Linux command runner. Native client registration and authenticated workflows on Windows and macOS are pending.

The cloud GitHub integration returned HTTP 403 for both push and branch creation. The milestone is committed locally. Publish this branch with GitHub write access, then open a draft PR against main.

## Resume here

1. Sign in manually in the Cloud Browser to inspect the UI, or in the worker's separate persistent profile to validate the integration. Keep profiles, account data and signed asset URLs outside Git.
2. Record semantic controls for single-image and multiview modes, models, face count, quota and asset identity at desktop and narrow viewports. Update the adapter and fixtures. Verify both forms and export an existing asset if available without pressing Generate.
3. Show a prepared prop and the observed remaining quota. Request explicit approval for one generation, then submit once. Record job creation, monitoring and validated export. Inspect an ambiguous result without submitting again.
4. Inventory additional workflows and implement adapters where supported. Test Windows 11 and macOS client registration, browser persistence and native Blender and Unity imports.
5. Push verified milestones and update this document. Keep the PR unmerged. A later Work session can resume from GitHub after the active execution ends.
