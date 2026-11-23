# Development status

Branch: `feature/hunyuan3d-global`. Run `git log -1 --oneline` in the checkout for the exact revision. Fork main baseline: `0659359`. The first local milestone was `602fac4`.

The CLI and stdio MCP share a SQLite ledger, persistent Chrome worker and site adapters. Global defaults to separate preparation and submission for single-image and multiview geometry. It verifies the prepared form and requires positive recognized quota before it reserves a click. China remains available with explicit site selection. Windows and macOS installers support scoped Codex and Claude Desktop registration with backups. See [architecture](ARCHITECTURE.md) and the [compatibility matrix](COMPATIBILITY.md).

Global queue requests now bind to one worker launch rather than an operating system process ID. Polling reports stopped and stale workers, rejects requests from an earlier launch, and preserves completed results. The worker stops handling requests after a stop command and records interrupted reservations as uncertain. Browser inspection reports the detected geometry controls, visible options, prepared job and recognized quota without submitting.

Cloud Linux passed 38 offline tests. They cover existing China fixtures, Global single-image upload, multiview form preparation, quota gating, one-click submission, uncertain outcomes, GLB export, and queue behavior during shutdown and restart. The wheel and source distribution built, and the installed wheel initialized over stdio MCP and reported 20 tools, including the original 19 and asset inspection. The production worker uses the Chromium sandbox. Only intercepted offline fixtures used the override needed by the managed Linux runner.

Cloud Chrome reached Tencent's sign-in page, but takeover was unavailable in this chat. Development does not depend on cloud sign-in. The signed-in Studio controls, actual quota, authenticated generation and exports still need testing. Native installer and client registration checks on Windows and macOS are pending. No generation jobs were submitted and no credits were spent.

## Resume here

1. Use the [macOS or Windows local procedure](LOCAL_TESTING.md) with your own account. Report the geometry controls, model and face-count options, quota label, and upload result from the no-credit phase. Keep account data, browser profiles, private images and signed asset URLs outside Git.
2. Adjust the Global selectors and fixtures from that evidence. Verify both image modes and an existing asset export where available. When the form is verified, use the separate local confirmation step to approve one job. Record its identity, monitoring and validated output. Never repeat an uncertain submission.
3. Inventory additional Studio workflows and implement adapters where the site supports them. Verify native installer registration, browser persistence, and Blender and Unity imports.
4. Publish milestones to GitHub and open a PR against main once the feature branch is available there. Keep it unmerged. The Cloud push for this milestone returned HTTP 403. Both commits are preserved locally, with a combined patch against the fork baseline in the Cloud workspace. GitHub write access is required to publish them.
