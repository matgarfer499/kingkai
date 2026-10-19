# Spike 0b: typing references into Claude Code through tmux

- **Date:** 2026-10-19
- **Setup:** Claude Code 2.1.303 (native binary) and tmux 3.4, on WSL2.
- **Method:**
  - Claude ran in a private tmux server (`tmux -L <name>`) with a clean environment.
  - A temporary logging command hook covered every event in spec §4.1, plus `PermissionRequest` and `PermissionDenied`.
  - The scratch project had a 300-line `src/big.ts` and `app/(group)/[slug]/page.tsx`.
  - The spike code was throwaway and lives outside the repo. Only the scrubbed fixtures in `tests/fixtures/` came from it.

## Answers

| ID | Question | Answer | Evidence |
|---|---|---|---|
| Q3 | Separator | **`#L`.** `@src/big.ts#L120 ` resolves as a file mention. Claude Code runs `Read src/big.ts (1 lines)` and the model gets exactly line 120. `@src/big.ts:140 ` does **not** resolve, and the model said that nothing was attached for line 140. | Runs 1 and 2 |
| Q4a | `@` autocomplete | Typing a partial `@src/bi` opens the file menu. The full reference with its trailing space closes it, and the text is left unchanged. | `screens/at_autocomplete.txt` |
| Q4b | Cursor mid-text | The reference is inserted at the cursor: `look at @src/big.ts#L7  and fix it`. | Run 4 |
| Q4c | While Claude is working | The text stays in the prompt, **is not submitted**, and is still there after the turn ends. | `screens/working.txt` |
| Q5 | `()` and `[]` in paths | They work. `@app/(group)/[slug]/page.tsx#L1 ` resolves, with `Read … (1 lines)`. | Run 3 |
| Q6 | `pane_current_command` | `claude` for the native binary. The npm install (`node`) wasn't tested, so keep accepting both. | `list-panes` |
| Q7 | `agent_id` on subagent tool events | **Confirmed.** `PreToolUse` and `PostToolUse` from a subagent carry `agent_id` and `agent_type`; main-agent events have neither. Subagent transcripts are at `<session>/subagents/agent-<agent_id>.jsonl`. | `hooks/pre_tool_use_subagent.json` |
| Q8 | Usage across streamed lines | Lines that share a `message.id` repeat the usage, and it is **cumulative**: for example `output_tokens` went 7 → 185 across the same id. **Last one wins** is correct. Subagent usage appears only in the subagent's own file. Cache writes come in two tiers (`usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`), so pricing needs separate rates for 5 m and 1 h writes. | `transcripts/*` |

## Q-S9: typing into a dialog (policy (a) inputs)

Claude Code's permission dialog is a numbered menu. A **lone digit keystroke selects an option.** Sending `4` with `send-keys -l` chose "4. No" and closed the dialog.

| Input while the dialog is open | Result |
|---|---|
| `send-keys -l -- '@src/big.ts#L12 '` (one burst) | Ignored; the dialog stays open |
| `send-keys -l -- '4'` (lone digit) | **Option 4 selected** |
| `send-keys -l -- '@src/big.ts#L'`, then `send-keys -l -- '4'` (a split burst) | **Option 4 selected.** If delivery is split, `send-keys` can action a dialog. |
| `load-buffer` of `1`, then `paste-buffer -p -d` (bracketed paste of a lone digit) | Ignored; the dialog stays open and nothing runs |
| Bracketed paste of `@src/big.ts#L77 ` in the normal prompt | Shown inline (not collapsed into `[Pasted text]`). It resolves as a mention: `Read src/big.ts (1 lines)`. |

**Decision for policy (a):**
- The typing primitive becomes **bracketed paste**: `tmux load-buffer -b <unique> -` with the text on stdin, then `tmux paste-buffer -p -d -b <unique> -t <pane>`. A paste arrives as one input event, so dialog hotkeys don't fire, and tmux never parses the text for key names or `;`.
- **Residual risk:** tmux 3.4 has no format variable that reports whether the pane enabled bracketed-paste mode. If the app ever disabled it, `-p` would degrade to raw keystrokes. The other layers still guard against that.

## Hook behaviour that changes the design

1. **`Notification` is not a dialog signal.**
   - It fired for only 1 of 3 permission dialogs, and in a second run not even 8.5 s after the dialog appeared.
   - **`PermissionRequest` fires reliably, before the dialog is drawn** (seen ≤ 0.5 s after the hook log was checked, while the dialog took about 7 s to appear).
   - `PermissionRequest` should therefore be installed and used to set `awaiting_permission`.
   - `PermissionDenied` did not fire for a user Esc; it is for auto-mode denials.
2. **A cancelled or denied dialog emits nothing.** After Esc there was no `PostToolUse`, no `PostToolUseFailure` and no `Stop`; the next event was the next `UserPromptSubmit`. So:
   - The reducer must close the agent's still-running calls as `abandoned` on the next `TurnStarted`, and at `SessionEnded`.
   - The dialog flag must also clear when the screen shows no dialog after a short grace period (§8.4 layer 3). Otherwise one Esc would block typing until the next prompt.
3. **Auxiliary agents.**
   - `SubagentStop` fires for hidden internal agents that have **no `agent_type` and no preceding `SubagentStart`**, and whose transcript file doesn't exist. One of them produces the grey prompt suggestion: its `last_assistant_message` was the ghost text.
   - The reducer ignores a `SubagentStop` for an agent it has never seen, when that stop has no `agent_type`.
   - Their usage is invisible to kingkai, so the cost estimate slightly undercounts. Note this in the UI help.
4. **`UserPromptSubmit` also fires for system turns.**
   - When a background subagent finishes, Claude Code submits a prompt that starts with `<task-notification>`.
   - Treat it as `TurnStarted(kind="system")`. It is not shown as a user prompt.
5. **`Stop` fires after each turn, including system turns.**
   - It does **not** fire after a turn that ended in a cancelled dialog.
6. **Transcripts contain `cost-state` lines.** They hold `totalCostUSD` and per-model `costUSD`, including the Haiku auxiliary usage.
   - They were written only twice in the session, near the end, so they can't drive a live view.
   - **Use:** when present, show the cost-state figure as "Claude Code's estimate" for the session, next to the live estimate. The format is internal, so it is optional.

## Dialog signatures (layer 3)

The screens in `tests/fixtures/screens/` were checked for markers. The marker that works:
- **`Esc to cancel` within the bottom 15 lines** matches the permission dialog and the folder-trust dialog.
- It matches none of the other screens: idle, working, `@` autocomplete, `/` menu, after Esc.

A secondary marker, `^\s*❯ \d+\. `, catches numbered menus.

Caveat for screen parsing: the grey prompt suggestion appears in `capture-pane -p` as if it were real text (it's only distinguishable with `-e`, as SGR 2 dim). kingkai must never infer prompt contents from the screen.

## Other notes

- **Environment:** a nested `claude` inherits `CLAUDECODE`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_MESSAGING_*` and the other session variables from the parent session. `kingkai up` must start the tmux pane with those removed.
- **`#L` attaches one line.** Claude then reads more context by itself. A `#L<start>-<end>` range covering the element's JSX span is a possible v2 improvement.

## Spec changes made from this spike

- **§4.1:** `PermissionRequest` added to the installed events; `Notification` is now only informational.
- **§4.2 and §4.3:**
  - `AttentionRequested` comes from `PermissionRequest`.
  - Abandoned calls close on the next `TurnStarted` or at `SessionEnded`.
  - System turns are recognised.
  - Unknown untyped `SubagentStop` events are ignored.
- **§4.5:** two cache-write tiers; `cost-state` as an optional reference figure.
- **§8.4 and S8:**
  - Bracketed paste is the primitive.
  - The dialog signature is `Esc to cancel`.
  - The flag clears on a no-dialog screen after a 1.5 s grace period.
  - Environment variables are scrubbed in `kingkai up`.
- **§13:** Q3–Q8 resolved.
