# Test fixtures

These are real Claude Code artefacts, recorded during Spike 0b (`docs/spikes/0b-tmux-typing.md`).

- **Source:** Claude Code **2.1.303**, recorded on **2026-10-19**.
- **Scrubbing:**
  - Paths are rewritten to `/home/user/dev/demo`.
  - Session and other UUIDs are replaced with `00000000-0000-4000-8000-…`.
  - Account-related keys (`organizationUuid`, `userType`, `requestRef`, `diagnostics`, `scratchpad_dir`) are dropped, and `requestId` is zeroed.
  - The personal status line and plan name are removed from the screens.

| Folder | Contents |
|---|---|
| `hooks/` | One stdin payload per hook event kind, plus two full ordered session logs for replay tests. `session_full_run.ndjson` has 2 subagents and 3 failing `ls` calls; it predates the `PermissionRequest` hook, so its permission dialog appears only as a `Notification` line. `session_permission_cancelled.ndjson` covers a permission dialog that was cancelled with Esc: `PreToolUse`, then `PermissionRequest`, then no end event. `pre_compact.json` is **synthetic**, as its `_synthetic` key says. |
| `transcripts/` | The `assistant` and `cost-state` lines of the main transcript and both subagent transcripts |
| `screens/` | `tmux capture-pane -p` output for the idle prompt, working, the `@` autocomplete, the `/` menu, the permission dialog, the folder-trust dialog, and after Esc. Menu entries that listed the maintainer's own skills were replaced with generic ones. |

**When Claude Code changes a format:** re-record the fixtures with `scripts/scrub_fixtures.py` (added in Phase 1, Task 1.7), update the version above, and let the fixture tests show what broke.
