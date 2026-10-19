# Test fixtures

These are real Claude Code artefacts, recorded during Spike 0b (`docs/spikes/0b-tmux-typing.md`).

- **Source:** Claude Code **2.1.303**, recorded on **2026-10-19**.
- **Scrubbing:**
  - Paths are rewritten to `/home/user/dev/demo`.
  - Session and other UUIDs are replaced with `00000000-0000-4000-8000-…`.
  - Account-related keys (`organizationUuid`, `userType`, `requestRef`, `diagnostics`, `scratchpad_dir`) are dropped.
  - The personal status line is removed from the screens.

| Folder | Contents |
|---|---|
| `hooks/` | One stdin payload per hook event kind, plus `session_full_run.ndjson`: the full ordered log of one session (2 subagents, 3 failing `ls` calls, a permission dialog), for replay tests |
| `transcripts/` | The `assistant` and `cost-state` lines of the main transcript and both subagent transcripts |
| `screens/` | `tmux capture-pane -p` output for the idle prompt, working, the `@` autocomplete, the `/` menu, the permission dialog, the folder-trust dialog, and after Esc |

**When Claude Code changes a format:** re-record the fixtures, update the version above, and let the fixture tests show what broke.
