# Test Hunyuan3D Global on macOS or Windows

This procedure uses the official Studio in the dedicated Chrome profile. It separates the no-credit checks from a single optional generation. The signed-in English UI has yet to be validated against the adapter. Stop at any failed check and keep the output so the adapter can be corrected.

1. Install Python 3.11+ and Google Chrome. From this fork's checkout, run the installer for your platform. The examples skip MCP registration because the CLI uses the same worker and adapter. To test MCP registration as well, omit the final `none` argument and restart Codex or Claude Desktop.

   | macOS Terminal | Windows PowerShell |
   | --- | --- |
   | `bash scripts/install-macos.sh none` | `./scripts/install-windows.ps1 -McpHost none` |
   | `source .venv/bin/activate` | `./.venv/Scripts/Activate.ps1` |

   If activation is unavailable, use `./.venv/Scripts/python.exe -I -m hunyuan_workbench` on Windows or `./.venv/bin/python -I -m hunyuan_workbench` on macOS in place of `hunyuan-workbench`. Before an update, close the older worker's dedicated Chrome window so the new worker starts with the same profile.

2. Run `hunyuan-workbench --site global web-start`. The dedicated Chrome tab may open blank. Workbench now waits for you to open [the official Hunyuan3D Global homepage](https://hy3d.tencent.ai/) in that tab. Sign in manually if prompted, then open Geometry Generation from the site. Keep the same tab and state root throughout. The profile is persistent, so a later launch can reuse the session if Tencent still accepts it. An existing verification page stays open without a refresh.

3. Run `hunyuan-workbench --site global doctor` and confirm that `responsive` is true. `HUMAN_ACTION_REQUIRED` is expected until you have opened Geometry Generation and inspected it. Run `hunyuan-workbench --site global web-inspect` and look up the returned request with `hunyuan-workbench --site global web-poll REQUEST_ID`. Wait for `COMPLETE`. Check the official geometry route, `geometry_controls_detected`, available image modes and face counts, and the remaining quota. Compare the quota to the number displayed by Studio. If it is missing, zero, or inconsistent, stop before submission. If the worker reports an authentication block, follow the recovery steps below.

4. Copy [the sample specification](examples/global-single-prop.json) to `test-prop.json`. Set `image` to an absolute path to a JPG, PNG, or WebP you are comfortable uploading to Tencent. On Windows, use forward slashes or double each backslash in the JSON string. Run:

   ```text
   hunyuan-workbench --site global prepare-spec test-prop.json
   hunyuan-workbench --site global web-run JOB_ID --wait 60
   hunyuan-workbench --site global web-inspect --job-id JOB_ID
   hunyuan-workbench --site global web-poll INSPECTION_REQUEST_ID
   ```

   Replace `JOB_ID` with the ID returned by `prepare-spec`. If `web-run` returns a queued or running request after the wait, use `web-poll` with that ID. Confirm the preparation result shows `READY` and `submitted: false`. Check the visible image preview and requested face count in the job tab. The inspection should show the same `prepared_job_id`. You can stop here and repeat with a different spec to test multiview without spending any generation credits.

5. **Explicitly approve one generation** only after reviewing the job, the preview and remaining quota. In the example for your platform, set the real job ID first. The prompt requires typing the exact job ID. Declining or entering anything else skips submission. Use one terminal and run this confirmation once.

   macOS:

   ```bash
   job='REPLACE_WITH_JOB_ID'
   printf 'Type %s to approve one generation using your Studio quota: ' "$job"
   read -r confirmation
   if [ "$confirmation" = "$job" ] && [ "$job" != REPLACE_WITH_JOB_ID ]; then
     hunyuan-workbench --site global submit "$job" --wait 60
   fi
   ```

   Windows PowerShell:

   ```powershell
   $job = 'REPLACE_WITH_JOB_ID'
   $confirmation = Read-Host "Type $job to approve one generation using your Studio quota"
   if ($confirmation -ceq $job -and $job -ne 'REPLACE_WITH_JOB_ID') {
       hunyuan-workbench --site global submit $job --wait 60
   }
   ```

6. Keep Chrome and the worker running. Use the submission request ID with `web-poll` if necessary. Monitor the job and retrieve its output:

   ```text
   hunyuan-workbench --site global status JOB_ID
   hunyuan-workbench --site global watches
   hunyuan-workbench --site global status JOB_ID --refresh --wait 60
   hunyuan-workbench --site global download JOB_ID --format auto --wait 60
   hunyuan-workbench --site global inspect-asset "PATH_FROM_THE_ARCHIVE_RESULT"
   ```

   Request download once the matching job is `SUCCEEDED` or `DOWNLOADED`. The worker attempts automatic export when it can confirm the matching completed asset. Verify the archive path, format and hash. If a submission result is missing or uncertain, inspect the Studio job list and the same ledger job. A stale queue, timeout, or missing result is never a reason to send another submission. If a prepared job was interrupted before submission, restart the worker and reprepare the form before requesting fresh confirmation.

## Recover from CAPTCHA, rate limits, or sign-in failures

| Code | What to do |
| --- | --- |
| `HUMAN_ACTION_REQUIRED` | Complete Tencent's CAPTCHA or sign in manually in the dedicated Chrome window. This also covers failed or expired sign-in. |
| `AUTH_RATE_LIMITED` | If Tencent says “Operation too often. Please retry later.” or the worker reports a temporary restriction, stop trying. Wait until Tencent permits another attempt, then complete verification manually through its supported interface. |

Leave the same Chrome window and profile open. While paused, the worker does not reload the login page, retry CAPTCHA, or run background watches. `doctor` shows the authentication code as the worker state; a paused worker may still show `responsive: true`. A blocked browser request returns `state: ERROR` with the authentication `code`. Do not repeatedly run `web-start`, clear the profile, resubmit the job, or retry verification through automation.

If regular Chrome or Safari signs in but the dedicated window does not, note whether the latest worker waited on a blank or restored tab at startup. Its startup message should tell you to open the official homepage yourself. With the CAPTCHA already visible, one `web-inspect` and `web-poll` can collect the authentication code without another sign-in attempt. Playwright controls the dedicated browser even when you type and click manually, and websites can detect some automation signals. Tencent's rate-limit message does not identify which signal or rule triggered the restriction.

Once Tencent has accepted your manual verification, return the affected tab to Geometry Generation and wait for the image form to appear. Run `hunyuan-workbench --site global web-inspect` once and use `web-poll` to check its result. Inspection reads the existing tab without refreshing it. `web-inspect --job-id JOB_ID` also requires an existing tab for that job. After inspection succeeds, resume from the last confirmed job state. Prepare the form again if needed. If the block appeared after a submission attempt, check the ledger and Studio for that job before doing anything else. An uncertain submission must not be repeated.

For a failure report, include the operating system, commit, stage, UI control labels and sanitized CLI output. Omit account identifiers, session data, private images and asset URLs. Keep the original file for any subsequent Blender or Unity import.
