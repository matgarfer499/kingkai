# kingkai: design spec

- **Status:** approved design, revised 2026-10-19 after Phase 0 (spikes) and the pre-Phase-1 review.
- **Scope:** MVP (v1). Session comparison and the other v2 items are in [§14 Non-goals](#14-non-goals).
- **Audience:** whoever builds kingkai. It assumes you know Python and asyncio, but not Claude Code internals.
- **History:** the evidence behind each decision is in `docs/spikes/`, and the change history is in git. This document states only the current design.

> King Kai watches the fight from his planet and speaks straight into Goku's head.
> kingkai watches Claude Code from a side pane and types straight into its prompt.

---

## 1. What we are building

kingkai is a terminal sidekick for Claude Code. It does two things.

1. **Live view.** A Textual TUI shows what Claude Code is doing in the current project:
   - the tree of the main agent and its subagents, with their state;
   - the files each agent read or edited;
   - a timeline of tool calls;
   - alerts when the agent looks stuck: the same tool with the same arguments N times, tool errors, retry loops, long silences;
   - tokens and estimated cost for the session;
   - the last reference that was clicked.
2. **Click-to-reference.** Alt+click an element in the local dev app (Next.js/React 19 or Django templates). The source location of that element, for example `@src/components/Button.tsx#L42 `, is inserted into the Claude Code prompt as a tmux bracketed paste. kingkai never presses Enter. Outside tmux, the reference goes to the clipboard instead.

kingkai uses no local AI and makes no network calls beyond 127.0.0.1.

### 1.1 Settled decisions

Each line gives the decision, then the reason. The evidence is in `docs/spikes/`.

- **One process.** The "daemon" is a set of services in Textual's asyncio loop. The boundary between them is a port (§5.3), so it can be split into two processes later. A second process would bring IPC and lifecycle bugs and give the MVP nothing.
- **Hooks append to a spool file; kingkai tails it.** A failed command hook shows a `hook error` notice in Claude Code. A file append can't fail just because kingkai isn't running. The spool also gives replay after a restart for free.
- **Hooks go in `.claude/settings.local.json`.** It is per-user and gitignored, so kingkai never changes settings that teammates share.
- **The typed form is `@path#L<line> `.** Spike 0b: Claude Code resolves it and reads exactly that line. `@path:42` doesn't resolve.
- **Delivery is a tmux bracketed paste, never keystrokes.** Spike 0b: a lone digit keystroke selects an option in a permission dialog, and a paste can't.
- **React source comes from the runtime owner stack.** Spike 0a: it was correct in every case. A build-time attribute points at call sites instead.
- **Dialog safety follows policy (a).** The maintainer decided on 2026-10-19: layered checks, then type (§8.4).
- **`UserPromptSubmit` context injection** stays ruled out.

---

## 2. Glossary

- **Session:** one Claude Code conversation, identified by `session_id`.
- **Agent:** the main agent (it has no `agent_id`) or a subagent (`agent_id` plus `agent_type`). **Auxiliary agents** are Claude Code's hidden internal agents, such as prompt suggestion. Their `agent_type` is missing or empty, and they are ignored.
- **Hook payload:** the JSON that Claude Code writes to a hook command's stdin.
- **Spool:** an append-only NDJSON file of one session's hook payloads. Each line is a shrunk payload with a `_kk` envelope added.
- **Transcript:** Claude Code's own JSONL file under `~/.claude/projects/<encoded-cwd>/`. Its format is internal and **undocumented**; the docs say it "changes between versions".
- **Domain event:** kingkai's typed representation of something that happened (§4.2).
- **Reference:** a validated pointer to a project file and line. It is the only thing kingkai will ever type (§8.4).
- **Overlay:** the dev-only browser script that handles Alt+click.

---

## 3. Architecture

### 3.1 Process and data flow

```
 ┌──────────── tmux session "kingkai-<project>" ─────────────────────────────┐
 │ pane %L: claude                       pane %R: kingkai (Textual TUI)      │
 └──────┬──────────────────────────────────────────▲─────────────────────────┘
        │ hook (async, command)                     │ tmux paste-buffer -p (Reference only)
        ▼                                           │
 kingkai-hook (stdlib only) ──append──▶ spool/<session>.ndjson
                                            │ tail
 ~/.claude/projects/.../<session>.jsonl ────┤ tail (usage only)
                                            ▼
                 ┌──────────────── kingkai process (one asyncio loop) ───────────┐
                 │ adapters: SpoolDirectory, TranscriptSource → translate        │
                 │ application: SessionService (reducer + detectors) → Store     │
                 │ application: ReferenceService (validate → deliver)            │
                 │ adapters: HTTP ingress (aiohttp, 127.0.0.1:ephemeral)         │
                 │ ui: Textual app, re-rendered from the Store at most 10×/s     │
                 └──────────────────────────────▲────────────────────────────────┘
                                                │ POST /v1/references (token + Origin)
 browser: dev app + overlay.js ─────────────────┘
          (token injected server-side by the Django middleware or the Next.js snippet)
```

### 3.2 Layers and the dependency rule

Dependencies only point inwards. import-linter enforces this in CI (§11.6), so the layering is checked, not just a convention.

| Layer | Package | May import | Contains | Must not contain |
|---|---|---|---|---|
| Domain | `kingkai.domain` | stdlib only (no asyncio) | Value objects, domain events, the state model, the reducer, alert detectors, usage and cost arithmetic, reference parsing and rendering, the `SourceFiles` port it needs | I/O, asyncio, Textual, msgspec, `datetime.now()` |
| Application | `kingkai.application` | domain | Use cases (`SessionService`, `ReferenceService`), the `Store`, the supervisor, and the ports (Protocols) | Concrete I/O, Textual |
| Adapters | `kingkai.adapters` | domain, application | The anti-corruption layer (hook and transcript schemas plus translation), tailers, aiohttp ingress, tmux, clipboard, settings installer, config, pricing and logging | UI |
| UI | `kingkai.ui` | domain, application | Textual app, widgets, presenters (pure functions from state to view models) | Adapters |
| Composition | `kingkai.bootstrap`, `kingkai.cli` | everything | Wiring, command-line parsing | Logic |
| Hook client | `kingkai.hook_client` | **stdlib only, and no other `kingkai` module** | Reads stdin, shrinks the payload, adds the envelope, appends it to the spool | Anything slow to import |
| Integrations | `kingkai.integrations.django` | Django, stdlib | DEBUG-only template loader and middleware (the `kingkai[django]` extra) | Imports of the daemon |

### 3.3 Module map

```
src/kingkai/
  domain/
    ids.py            SessionId, AgentId, ToolUseId, EventId (NewType over str)
    json.py           JsonValue (recursive alias)
    events.py         DomainEvent union (frozen, slotted dataclasses)
    state.py          SessionState, AgentNode, ToolCall, FileTouch, Alert
    reducer.py        reduce(state, event) -> SessionState
    tools.py          touches_for(), fingerprint()
    alerts/           base.py (Detector, AlertChanges), repeated_call.py, tool_failure.py,
                      retry_loop.py, stall.py
    usage.py          TokenUsage, ModelPrice, Pricing, estimate_cost()
    reference.py      Reference, RawReference, Rejected, RejectionReason, parse_reference(),
                      GRAMMAR, SourceFiles / ResolvedFile (domain-owned port)
  application/
    ports.py          Clock, Sleeper, EventSource, PromptTyper, DeliveryOutcome
    store.py          Store, Diagnostics
    session_service.py
    reference_service.py
    supervisor.py
  adapters/
    hooks/schema.py, hooks/translate.py
    transcript/schema.py, transcript/translate.py
    tail.py               NdjsonTailer
    spool_source.py       SpoolDirectory (EventSource)
    transcript_source.py  TranscriptSource (EventSource)
    clock.py              SystemClock
    project.py            find_project_root(), ensure_locally_ignored()
    settings_installer.py install()/uninstall() for settings.local.json, write_shim()
    http/guards.py, http/payload.py, http/app.py
    session_file.py       .kingkai/session.json
    source_files.py       real-filesystem SourceFiles
    tmux.py               TmuxPromptTyper (pane checks, dialog signatures, paste)
    clipboard.py          ClipboardTyper + per-platform ClipboardCommand rows
    snippets.py           text printed by `init --next` / `--django`
    config.py, pricing.py, logging_setup.py
  hook_client/
    __main__.py, shrink.py, envelope.py, spool.py
  ui/
    app.py, messages.py, presenters.py, widgets/*.py
  integrations/django/
    loaders.py, middleware.py
  bootstrap.py            build_app(config) -> KingkaiApp   (the composition root)
  cli.py                  cyclopts app: init, uninstall, up, watch, doctor
  assets/overlay.js       built from overlay/ by esbuild (never committed)
  assets/pricing.toml
overlay/                  TypeScript source for the browser overlay (own package.json)
examples/next-demo/       minimal Next.js 16 app (has its own .claude/), for e2e tests and demos
examples/django-demo/     minimal Django 6 app, for e2e tests and demos
scripts/scrub_fixtures.py turns recorded hook, transcript and screen captures into public fixtures
```

### 3.4 Patterns, and why each one is here

1. **Ports and adapters, with `typing.Protocol`.** Claude Code's formats are undocumented or move fast, and tmux, the clipboard and the filesystem are side effects. Protocols let the use cases run in tests against in-memory fakes, with no mocks. They are structural, so adapters don't inherit from anything.
2. **Functional core, imperative shell.** All decisions (state transitions, alerts, reference validation, cost) are pure functions in `domain`. The shell only moves bytes, so most tests are plain function calls with table-driven inputs.
3. **State as a fold over events.** `SessionState = reduce(reduce(initial, e1), e2) …`. Replay after a restart is the same code path as live updates. Out-of-order async hooks are handled in one place, the reducer. There is no event store beyond the spool and no snapshots: sessions are small.
4. **Parse, don't validate.** A `Reference` exists only if `parse_reference()` accepted the input, and once you hold one it is safe to type. `PromptTyper.type_reference(ref: Reference)` takes no `str`, so mypy rejects typing free text. Construction is closed (S7):
   - `Reference.__init__` always raises. Only the private `Reference._mint()` builds instances, and `parse_reference` is its only caller: the one call carries `# noqa: SLF001`, ruff `SLF001` flags any other, and an AST test scans `src/`.
   - `Reference` is a plain slotted class, not a dataclass, so `dataclasses.replace` can't copy one. `__setattr__` and `__delattr__` raise, so it is immutable.
5. **Anti-corruption layer.** `adapters/hooks` and `adapters/transcript` are the **only** modules that know Claude Code's field names. When a release changes them, the fix stays in one place, and the fixture tests (§11.2) show what broke.
6. **Strategy, for detectors.** Each alert rule is a small object that satisfies `Detector`. `SessionService` gets a tuple of them, so a new rule means a new file and one line in `bootstrap.py`.
7. **Composition root and constructor injection.** `bootstrap.build_app()` is the only place that builds concrete adapters. There is no DI container: about ten objects are wired by hand in one readable function.
8. **Presenter / humble view.** Widgets only render view models from `ui/presenters.py`. Presenters are pure and unit-tested, which keeps the Textual layer thin.
9. **Ordered fallback for delivery.** `ReferenceService` tries a tuple of `PromptTyper`s (tmux, then clipboard), and the result says which one delivered.

**Not used, on purpose:**
- DI frameworks;
- ABC hierarchies;
- a plugin registry;
- the repository pattern (there is no database);
- an event bus library (`Store` with subscribers is enough);
- CQRS;
- async code in the domain.

### 3.5 Key types (signatures, not bodies)

```python
# application/ports.py
class Clock(Protocol):
    def now(self) -> datetime: ...                       # timezone-aware UTC
Sleeper = Callable[[float], Awaitable[None]]
class EventSource(Protocol):
    def events(self) -> AsyncIterator[DomainEvent]: ...
class PromptTyper(Protocol):
    name: str                                            # "tmux" | "clipboard"
    async def type_reference(self, ref: Reference) -> DeliveryOutcome: ...
DeliveryOutcome = Typed | Declined                       # Declined(reason: str)

# domain/reference.py
class SourceFiles(Protocol):                             # domain-owned port, read-only
    def resolve(self, root: Path, raw_path: str) -> ResolvedFile | None: ...  # realpath
    def line_count(self, f: ResolvedFile) -> int: ...
class Reference:                                         # __slots__ = ("path", "line")
    path: str                                            # POSIX, relative to root, NFC
    line: int
    def render(self) -> str: ...                         # "@{path}#L{line} ", re-checked against GRAMMAR
def parse_reference(raw: RawReference, root: Path, files: SourceFiles) -> Reference | Rejected: ...

# domain/reducer.py
def reduce(state: SessionState, event: DomainEvent) -> SessionState: ...
```

`Rejected` carries a `RejectionReason` (a StrEnum). Validation **returns** it instead of raising: a rejection is an expected outcome of handling untrusted input, so the caller has to deal with it, and the union type makes mypy check that.

---

## 4. Event model

### 4.1 Hook events we install

`kingkai init` installs the hooks in `.claude/settings.local.json`, and `kingkai uninstall` removes them. Both commands are idempotent. kingkai recognises its own entries by their command path (the shim), so it leaves user hooks alone.

- **Ignore check.** `init` runs `git -C <root> check-ignore -q .claude/settings.local.json`. If the file isn't ignored, `init` offers to add it to the repository's local exclude file, which is never committed. The root may be a subdirectory of the repository (a monorepo app, or `examples/next-demo` in this repo), so `init` finds that file with `git -C <root> rev-parse --git-path info/exclude` and writes the path relative to `git rev-parse --show-toplevel`. The user's `.gitignore` is never touched. Outside a git repository, the step is skipped.
- **Stable shim.** The hook command is `<state>/bin/kingkai-hook`, a POSIX `sh` file that `init` writes. `<state>` is the state directory from §5.1. Both the interpreter path inside the shim and the command string in `settings.local.json` are quoted with `shlex.quote`, so a home directory with spaces works.

  ```sh
  #!/bin/sh
  PY='/abs/venv/bin/python'; [ -x "$PY" ] && "$PY" -I -m kingkai.hook_client >/dev/null 2>&1; exit 0
  ```

  If kingkai is uninstalled or its venv moves or breaks, the hook still exits 0 with no output. `init` rewrites the shim, and `doctor` checks that it runs.
- **Entry shape.** Every installed entry uses `"type": "command"`, `"async": true` and `"timeout": 5`, with no matcher.

| Claude Code event | Why we need it | Fields we read (anything else is ignored) |
|---|---|---|
| `SessionStart` | Opens a session and gives the transcript path | `session_id`, `transcript_path`, `cwd`, `source`, `model?` |
| `UserPromptSubmit` | Opens a turn. A prompt starting with `<task-notification>` is a **system** turn: Claude Code submits one when a background subagent finishes. | `prompt` (first 80 characters only) |
| `PreToolUse` | Tool call started | `tool_name`, `tool_input`, `tool_use_id`, `agent_id?`, `agent_type?` |
| `PostToolUse` | Tool call succeeded | the same fields, plus `duration_ms?` |
| `PostToolUseFailure` | Tool call failed | the same fields, plus `error`, `is_interrupt?` |
| `SubagentStart` / `SubagentStop` | Subagent tree | `agent_id`, `agent_type`, `agent_transcript_path` (on Stop) |
| `PermissionRequest` | **The dialog signal.** It fires when the permission dialog opens. Our hook never returns a decision. | `tool_name`, `agent_id?` |
| `Stop` | Closes the turn (it doesn't fire after a cancelled dialog) | none |
| `PreCompact` | Compaction shown on the timeline | `trigger` |
| `SessionEnd` | Closes the session | `reason` |

- **Attribution.** A payload with `agent_id` belongs to that subagent; without it, it belongs to the main agent.
- **`async: true`.** The hook never blocks Claude.
- **`SessionEnd`.** Its 1.5 s default timeout is ample for a file append.
- **`Notification` isn't installed.** It is unreliable for dialogs (it fired for 1 dialog in 3), and no event reads it.

### 4.2 Domain events

Domain events are frozen, slotted dataclasses. Every event carries:
- `session_id`;
- `event_id: EventId`: `_kk.id` for hook events, or `"<file>:<byte offset>"` for transcript events;
- `at: datetime`, in UTC: `_kk.at`, or the transcript line's `timestamp`.

Events are applied in spool line order. Field names belong to kingkai, not to Claude Code.

```
SessionStarted(transcript_path, cwd, source, model, tmux_pane)
TurnStarted(kind: "user" | "system", prompt_preview)      TurnStopped()
ToolCallStarted(agent, agent_type, tool_use_id, tool, summary, input_fingerprint, touches)
ToolCallSucceeded(agent, tool_use_id, duration_ms)
ToolCallFailed(agent, tool_use_id, error_summary, interrupted)
SubagentStarted(agent_id, agent_type)
SubagentStopped(agent_id, agent_type: str | None, transcript_path)
AttentionRequested(agent, tool)                             # from PermissionRequest
Compacted(trigger)        SessionEnded(reason)
UsageRecorded(agent, message_id, model, usage: TokenUsage)  # from transcripts (Phase 2)
Tick(now)                 ReplayCompleted()                 # synthetic (Phase 2); never in the spool
```

- **`agent`.** An `AgentRef`: `MainAgent()` or `SubAgent(agent_id)`.
- **`summary`.** At most 60 characters for the timeline, built by the translator: `Bash` → `command`, `Agent` → `description`, `Grep`/`Glob` → `pattern`, otherwise the first touch path. A hashed value shows as `‹long input›`.
- **`input_fingerprint`.** The SHA-256 of the canonical JSON of the shrunk `tool_input` (keys sorted, compact separators). Detectors compare fingerprints, never raw input.
- **`touches`.** A tuple of `FileTouch(path, kind)`, where kind is `read`, `write` or `search`, built from `file_path`, `notebook_path` or `path` in `tool_input`:
  - read: `Read`
  - write: `Edit`, `MultiEdit`, `Write`, `NotebookEdit`
  - search: `Grep` with a `path`
  - nothing for `Glob` or `Bash`.

### 4.3 Reducer rules

- **Correlation by `tool_use_id`.** An end that arrives before its start is kept as a call with `started_at=None`, and the start fills it in later. Either order gives the same call state.
- **Idempotency.** An event whose `event_id` is in `state.seen: frozenset[EventId]` is a no-op, so replay can overlap with live tailing.
- **Agents.**
  - `SubagentStarted` creates a node.
  - A `ToolCallStarted` for an unseen `SubAgent` creates the node from its `agent_type`.
  - A `SubagentStopped` for an unseen agent whose `agent_type` is missing or empty is an auxiliary agent, and is ignored.
- **Turns.**
  - `TurnStarted` → `turn_open = True`.
  - `TurnStopped` → `turn_open = False`.
- **Abandoned calls.** A denied or cancelled tool call gets no end event. On the next `TurnStarted`, and at `SessionEnded`, every call still `running` becomes `abandoned`.
- **Dialog flag.**
  - `AttentionRequested(agent, …)` sets `awaiting_permission[agent] = at`.
  - The entry is removed only by a later `ToolCallStarted`, `Succeeded` or `Failed` from **that same agent**, or by any `TurnStarted` or `TurnStopped`.
  - Activity from another agent never clears it.
  - The flag is one input to S9; §8.4 says how `ReferenceService` uses it.
- **Liveness.** `SessionEnded` sets `ended = True`. "Idle" is not stored: presenters derive it from `last_activity` (more than 30 min ago).

### 4.4 Alert detectors (Strategy, Phase 2)

Each detector is `(before: SessionState, event, now) -> AlertChanges`, holding the alerts to raise and the keys to clear.
- **Keys.** Alerts have stable keys (for example `repeated:<agent>:<fp>`). They are raised once, then updated, and cleared when their condition no longer holds.
- **Activity** means a hook event for the session. `Tick` and `UsageRecorded` don't count.
- **Replay.** During replay `now` is the event's `at`, and the time-based detectors stay off until `ReplayCompleted`.
- **Thresholds** are constructor arguments with these constant defaults. They aren't user-configurable in the MVP.

| Detector | Fires when | Clears when | Default | Severity |
|---|---|---|---|---|
| `RepeatedCall` | The same `(agent, tool, fingerprint)` appears ≥ N times in that agent's last K calls | It appears fewer than N times in the last K | N = 3, K = 10 | warning |
| `ToolFailure` | A `ToolCallFailed` that isn't an interrupt | 60 s later | — | info |
| `RetryLoop` | ≥ M consecutive failures of the same `(agent, tool)` | That `(agent, tool)` succeeds | M = 3 | error |
| `Stall` | A turn is open, no dialog flag is set, and there has been no activity for T. Checked on `Tick`. | The next activity | T = 120 s, or 600 s while a call is running | warning |

### 4.5 Usage and cost (Phase 2)

- **Source.** `UsageRecorded` comes only from transcripts: `type == "assistant"` lines that have `message.usage`.
- **Files.** The main file is `transcript_path`. Subagent files are `<session>/subagents/agent-<agent_id>.jsonl`. They are watched while the subagent runs, and `SubagentStop` gives the path.
- **Dedupe.** Lines that share a `message.id` repeat usage cumulatively, so the **last** one wins. Usage is keyed by `message_id` across all of a session's files.
- **`TokenUsage` fields:**
  - `input` and `output`;
  - `cache_write_5m` and `cache_write_1h`, from `usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`;
  - `cache_read`.
- **Cost estimate.** `Σ tokens × price`, using `assets/pricing.toml` (USD per million tokens, per model, for the 5 kinds), with overrides from `kingkai.toml`.
  - It is always labelled **"≈ API-equivalent"**: subscription plans aren't billed per token.
  - If the model has no price, the cost shows `—`. kingkai never guesses.
- **Claude Code's own estimate.** If a transcript has a `cost-state` line (an internal format, written near the end of a session), its `totalCostUSD` is shown beside the estimate as "Claude Code's estimate". A parse failure just hides it.
- **Not counted.** Auxiliary agents have no transcript, so their usage (small amounts) isn't counted, and the help screen says so.
- **OpenTelemetry** is out of scope (§14). The `EventSource` port leaves room for it.

---

## 5. Ingress, tailing and daemon/TUI communication

### 5.1 Hook client (`kingkai-hook`)

1. It reads all of stdin and parses the JSON. If that fails, it exits 0 with no output.
2. **Shrink** (`shrink.py`, pure):
   - Top-level display fields are **cut**: `prompt` to 80 characters; `error` and `last_assistant_message` to 200.
   - Then, recursively, any string longer than 512 characters anywhere becomes `{"$sha256": <hex>, "$len": <n>}`.
   - The cut list applies to top-level keys only, so `tool_input.prompt` (for example on `Agent` calls) is hashed, not cut. That keeps fingerprints exact.
3. **Envelope** (`envelope.py`, pure): `envelope(payload, *, event_id, at, pane)` adds `"_kk": {"v": 1, "id": <uuid4 hex>, "at": <iso8601 UTC>, "pane": $TMUX_PANE or null}`.
4. **Append** one line to the spool, under an exclusive `fcntl.flock`, with file mode 0600.
5. It **always exits 0 and writes nothing to stdout or stderr** (S10).

**Spool location.** `<state>/spool/<project-key>/<session_id>.ndjson`:
- `<state>` is `$XDG_STATE_HOME/kingkai`, falling back to `~/.local/state/kingkai`. Directories have mode 0700.
- `<project-key>` is the first 16 hex characters of `sha256(realpath(CLAUDE_PROJECT_DIR or payload cwd))`.
- `session_id` must match `^[A-Za-z0-9-]{1,64}$`; otherwise the payload is dropped.
- `watch` deletes spool files older than 7 days when it starts.

### 5.2 Tailing and sessions

- **`NdjsonTailer(path, *, poll_interval, sleep, chunk_size=65536)`.**
  - It yields complete lines only, as `TailedLine(path, offset, data)`.
  - It reads in bounded chunks and awaits `sleep(0)` between chunks, so a large replay never blocks the loop.
  - It restarts from offset 0 if the file shrinks or its inode changes.
  - It polls: every 100 ms for spools and 500 ms for transcripts. There is no inotify: polling is one less dependency, behaves the same on WSL, macOS and Linux, and tests stay deterministic.
- **`SpoolDirectory`.** It scans the project's spool dir every second and tails each `*.ndjson` file modified in the last 24 h, from offset 0. It reports undecodable lines through an injected `on_skip(reason)` callback, which feeds `Diagnostics`.
- **`ReplayCompleted`** is emitted once every file has been read to EOF at startup.
- **Which session is shown:**
  - With `--pane`, the newest session (by `started_at`) whose `tmux_pane` matches; otherwise the newest session by `started_at`.
  - The view auto-follows newer sessions until the user presses `s`, which cycles through sessions.
- **Project root.** `find_project_root(start, home)` walks up from the cwd to the nearest directory containing `.git/` or `.claude/`. It **stops below `home`**, because `~/.claude` is user config, not a project. If it finds nothing, it uses the cwd. `--root` overrides all of this. `doctor` warns if the spool keys found don't match the resolved root.

### 5.3 Daemon to TUI

- `Store` keeps `dict[SessionId, SessionState]` and its subscribers, plus `Diagnostics`, the one deliberate piece of mutable application state: skipped-line counts per reason.
- `SessionService.run()` drains the `EventSource`s, applies `reduce` (and the detectors, from Phase 2) and puts the new state in the store.
- The Textual app subscribes with a callback that sets a **dirty flag**. A `set_interval(0.1)` timer re-renders the shown session from presenters when the flag is set. That gives at most 10 renders per second, with no message queue to manage.
- Background work runs as Textual `@work` async workers, and the supervisor wraps each one (§10). The aiohttp server uses `AppRunner` plus `TCPSite`, which leaves signal handlers alone.
- **Splitting later:** the `Store` subscription would become a stream over a Unix socket. `domain` and `application` wouldn't change.

---

## 6. CLI

`cyclopts` builds the CLI. Every command can be called in tests with an argv list.

| Command | What it does |
|---|---|
| `kingkai init [--yes] [--next] [--django] [--root P]` | Installs the hooks, writes the shim, and creates `.kingkai/` with its own `.gitignore` containing `*`. It shows a diff first unless `--yes` is given. Invalid JSON in the existing `settings.local.json` aborts with exit code 2 and writes nothing. `--next` / `--django` print the integration snippet; `init` never edits app code. |
| `kingkai uninstall [--root P]` | Removes kingkai's hook entries and `.kingkai/`. |
| `kingkai up [--root P]` | Creates or attaches the tmux session `kingkai-<dir>`: `claude` on the left, `kingkai watch --pane <%id>` on the right. The Claude pane starts with the parent's Claude Code session variables removed (`CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_PID`); otherwise they leak into child processes. |
| `kingkai watch [--pane %N] [--root P]` | Starts the TUI and the services. Without `--pane`, references go to the clipboard. |
| `kingkai doctor` | Checks Python, tmux (≥ 3.2), the hooks, the shim, the spool dir and its modes, a clipboard backend, and the session file. It explains each failure in one line. |

### 6.1 TUI layout and key bindings

```
┌ kingkai · myapp · session 3f2a… (live) ───────────────────── ≈ $0.42 · 81k tok ┐
│ Agents                     │ Timeline                                          │
│ ▼ main  ● working          │ 10:02:11 main  Read   src/app/page.tsx       12ms │
│   ├ Explore  ✓ done        │ 10:02:12 sub1  Grep   src/lib                40ms │
│   └ general  ● working     │ 10:02:15 main  Bash   ✗ exit 1               2.1s │
├────────────────────────────┼───────────────────────────────────────────────────┤
│ Files                      │ Alerts                                            │
│ W src/app/page.tsx      2  │ ⚠ RetryLoop  main · Bash failed 3× in a row       │
│ R src/lib/auth.ts       1  │ ⚠ Stall      no activity for 2m (turn open)       │
├────────────────────────────┴───────────────────────────────────────────────────┤
│ Last reference: @src/components/Button.tsx#L42  → typed (tmux %3) · Button      │
└ s next session  a agent filter  f written only  c clear alerts  y copy  ? help  q quit ┘
```

| Key | Action |
|---|---|
| `s` | Show the next session (and stop auto-following) |
| `a` | Filter the timeline and files by the agent selected in the tree (toggle) |
| `f` | Files panel: all touches, or written files only |
| `c` | Dismiss the current alerts; they come back if their condition fires again |
| `y` | Copy the last reference to the clipboard |
| `?` | Help |
| `q` / `ctrl+q` | Quit |

- **Narrow terminals.** Below 100 columns the layout collapses to tabs, and `1`–`4` switch panels (Phase 2).
- **No markup in data.** Every string that comes from data (paths, labels, prompt previews, errors) is rendered as a Rich `Text`, never parsed as markup. `app/[slug]/page.tsx` must display literally (S12).

---

## 7. Configuration

`kingkai.toml` sits at the project root and is optional. It is parsed into a frozen `Config`, and unknown keys are an error. The MVP has two settings:

```toml
[references]
allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:8000", "http://127.0.0.1:8000"]   # the default

[pricing."claude-opus-5-5"]        # optional; USD per million tokens
input = 0.0
output = 0.0
cache_write_5m = 0.0
cache_write_1h = 0.0
cache_read = 0.0
```

---

## 8. Click-to-reference

### 8.1 Overlay protocol

The overlay is written in TypeScript in `overlay/`. esbuild bundles it into one IIFE, `assets/overlay.js`, and it renders inside a closed shadow root so it shares no CSS with the app.

**Bootstrap.**
- The page includes `<script src="{url}/overlay.js" data-kingkai-url data-kingkai-token data-kingkai-app-root defer>`. The framework integration renders this tag **server-side** from `.kingkai/session.json`.
- `overlay.js` is static and holds no secret. Any site can load it and gains nothing: the token lives only in the dev app's own HTML, which other origins can't read.

**Session file.** `.kingkai/session.json` has mode 0600. It is deleted on a clean exit, and a file whose pid is dead is stale.

```json
{ "v": 1, "url": "http://127.0.0.1:53817", "token": "<secrets.token_urlsafe(32)>",
  "root": "/home/user/dev/myapp", "pid": 4242, "started_at": "2026-10-19T10:00:00Z" }
```

- **The port is ephemeral** (bound to `127.0.0.1:0`). The integrations read the URL from this file.
- **Integrations re-read the file on each request,** cached by mtime. They inject **nothing** when it's missing or stale.
- **After a kingkai restart,** the port and token change. If the overlay's POST can't connect or gets `403 bad_token`, it shows "kingkai restarted, reload the page".

**Interaction.**
- Holding Alt highlights the element under the pointer and shows a label.
- Alt+click is captured in the capture phase with `preventDefault()` and `stopPropagation()`.
- Esc cancels.
- A toast reports the result: "typed into Claude Code", "copied to clipboard", "couldn't locate source", or "rejected: <reason>".

**HTTP API (v1).** These are the only routes; anything else returns 404.

| Route | Checks | Purpose |
|---|---|---|
| `GET /overlay.js` | Host | Static asset, `Cache-Control: no-store` |
| `OPTIONS /v1/references` | Host and Origin | CORS preflight. Only allowlisted origins get `Access-Control-Allow-Origin: <that origin>`, plus `Allow-Headers: content-type, x-kingkai-token`, `Allow-Methods: POST` and `Vary: Origin` |
| `POST /v1/references` | Host, Origin, content type, size, token, rate | Submit a click |

Request body (≤ 4096 bytes, `Content-Type: application/json`):

```json
{ "v": 1, "kind": "react",
  "candidates": [
    { "file": "file:///home/user/dev/myapp/node_modules/next/dist/client/app-dir/link.js", "line": 787 },
    { "file": "file:///home/user/dev/myapp/src/components/ui/Button.tsx", "line": 5 } ],
  "label": "Button", "selector": "main > div:nth-child(2) > button",
  "page": "http://localhost:3000/settings", "view": null }
```

- **`kind`** is `react` or `django`; anything else gets `422 bad_kind`.
- **`candidates`** has 1–10 entries, innermost frame first; anything else gets `422 bad_candidates`. Django sends exactly one.
- **Choosing a candidate.** Python runs `parse_reference` on each candidate in order, and **the first accepted one wins**. Every containment decision therefore stays in Python. If none is accepted, the response gives the first candidate's reason.
- **`candidates[].file`** must be an absolute `file://` URL or an absolute POSIX path of at most 1024 characters. The overlay resolves every raw React frame URL before sending (§8.2).
- **`label`, `selector`, `page` and `view`** are display-only. They are never typed. Control characters are **stripped** from them and they are cut to 120 characters. Control characters inside a candidate cause a **rejection** instead (S6).

Responses:
- `200 {"status": "typed" | "copied" | "shown", "text": "@src/components/ui/Button.tsx#L5 "}`, sent after delivery finishes.
- On error, `{"error": <code>}` with the code as a `RejectionReason` or guard code: `400` (bad JSON), `403` (host, origin or token), `413` (size), `415` (content type), `422` (rejected) or `429` (rate).

### 8.2 React 19 / Next.js 16: source location (runtime owner stack)

React 19 removed `_debugSource`. The overlay resolves an element like this:
1. **Fiber.** Take the element, or its `parentElement` for a text node, and read its React fiber from the `__reactFiber$*` key.
2. **Owner stack.** Use `getSource(fiber, false)` and `getOwnerStack` from `bippy/source`. The `false` disables bippy's source-map cache, which hot reload (HMR) needs. bippy is pinned exactly in `overlay/package.json` and bundled into `overlay.js`.
3. **Server frames.** A frame like `about://React/<Env>/…` is resolved with a same-origin `POST /__nextjs_original-stack-frames`, which uses the fields `line1` and `column1`. The response paths are relative to the Next.js app root, so they are made absolute with `data-kingkai-app-root`.
4. **Send.** Up to 10 resolved frames go out as `candidates`.

If nothing resolves, the toast says "couldn't locate source". The overlay never guesses.

- **Accepted fragility:** React internals, a private Next.js dev endpoint, and bippy. The e2e suite runs the four spike cases on `examples/next-demo`, so a breaking upgrade fails CI.
- **Next integration:** `kingkai init --next` prints a dev-only server-component snippet, about 15 lines, for the root layout. It reads the session file and renders the script tag, with `data-kingkai-app-root={process.cwd()}`. No `next.config.ts` change is needed, and there's no npm package in the MVP.

### 8.3 Django: DEBUG-only template loader (Phase 4)

- **Loader.** `SourceAnnotatingLoader` subclasses `filesystem.Loader`, with an `app_directories.Loader` variant, so that `Origin.loader is self` (required by `cached.Loader`).
  - In TEXT tokens from `django.template.base.Lexer`, it inserts ` data-src="<absolute path>:<line>"` right after each opening `<tagname`.
  - It skips `<!doctype`, comments, closing tags, and the bodies of `<script>` and `<style>`.
  - It never adds newlines.
  - It only handles `.html`/`.htm` files, and only when `settings.DEBUG` is true.
- **Middleware.** `KingkaiMiddleware` (DEBUG only, `text/html` only):
  - injects the script tag before `</body>`;
  - adds `<meta name="kingkai-view" content="<absolute path>:<line>">`, built from `request.resolver_match` and `inspect.getsourcelines`. The overlay sends it as `view`.
- **Open question Q9** (mini-spike at the start of Phase 4):
  - Should the source be rewritten in `get_contents`, or the compiled nodelist patched instead?
  - How do `{% include %}`, `{% extends %}` and `{% block %}` map?
  - Do tag names built by template logic fail safely?
  - Does it work alongside django-debug-toolbar?
  - Default if unresolved: rewrite in `get_contents`. Jinja2 is v2.

### 8.4 The typed reference: grammar and delivery

**Grammar.** This is the only text kingkai ever types:

```
^@(?:[\w.\-()\[\]@+]+/)*[\w.\-()\[\]@+]+#L[1-9][0-9]* $        (re.UNICODE \w)
```

`parse_reference` also requires:
- **Path shape.**
  - The path is the **resolved filesystem name**, made relative to the root and NFC-normalized.
  - No segment is `.` or `..`.
  - No segment is `node_modules`, `.next`, `.git` or `.venv` (otherwise `excluded_dir`). Frames from inside the root's dependencies are skipped this way.
- **Line.** `1 ≤ line ≤ line_count`.
- **Allowed characters.**
  - Next.js app-router paths such as `app/(marketing)/[slug]/page.tsx` are allowed.
  - Spaces, `;`, `#`, `:`, quotes, backslashes, and every control or format character are rejected. Paths with spaces are not supported in the MVP.

**Delivery via tmux: bracketed paste.** Two commands run through `asyncio.create_subprocess_exec`, with no shell:
1. `["tmux", "load-buffer", "-b", buf, "-"]`, with the rendered text on stdin;
2. `["tmux", "paste-buffer", "-p", "-d", "-b", buf, "-t", pane]`.

Details:
- `buf` is `kingkai-<uuid4 hex>`.
- `-p` sends the text as one bracketed paste, so dialog digit hotkeys can't fire.
- tmux never parses the text for key names or `;`.
- kingkai never calls `send-keys`.

**Checks before typing (policy (a)).** Every check must pass; otherwise the clipboard is used. Check 1 runs in `ReferenceService`, which skips the tmux typer when it fails. Checks 2 and 3 run inside the tmux typer, which returns `Declined` when either fails.
1. **Dialog flag** (in `ReferenceService`). Use the newest session whose `tmux_pane` equals the target pane. If any agent in it has a dialog flag set **less than 10 s ago**, decline.
   - Older flags are not cleared. They are left to check 3, because `PermissionRequest` can fire seconds before the dialog appears.
   - If no session is bound to the pane yet, this check passes.
2. **Pane state.** `tmux display-message -p -t <pane> '#{pane_id} #{pane_in_mode} #{pane_current_command}'`. The pane must exist, must not be in copy mode, and must be running `claude` or `node`.
3. **Screen.** `tmux capture-pane -p -t <pane>` must not match a dialog signature.
   - `Esc to cancel` in the bottom 15 lines, or a line matching `^\s*❯ \d+\. `.
   - The signatures are data in `tmux.py`, tested against `tests/fixtures/screens/`.
   - The screen is never used to infer prompt contents: the grey prompt suggestion looks like real text in `capture-pane -p`.

**Residual risk.** tmux 3.4 can't report whether the pane enabled bracketed paste. The three checks still apply.

**Fallback:**
- **`ClipboardTyper(command)`.** One class driven by a `ClipboardCommand` row (argv builder, stdin encoding, whether to wait). `detect_clipboard(env, which)` picks the row.
- **Nothing works.** If no clipboard works either, the TUI shows the text in a selectable widget, and `y` retries.

| Row | Command | Notes |
|---|---|---|
| WSL | `powershell.exe -NoProfile -NonInteractive -Command "Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('<b64>')))"` | `clip.exe` garbles anything that isn't ASCII. Takes about 0.2 s. |
| macOS | `pbcopy` with `LANG=en_US.UTF-8` | |
| Wayland | `wl-copy` | Don't wait on piped output: it forks |
| X11 | `xclip -selection clipboard` | Same as Wayland |

---

## 9. Security model

kingkai types into a terminal running an agent with tool access, so it is a target. **Each rule is enforced by the tests named next to it, and this table is the only list of security test names.** Tests marked † are property-based (hypothesis).

| # | Rule | Mechanism | Enforcing test(s) |
|---|---|---|---|
| S1 | **Listen on localhost only** | `TCPSite("127.0.0.1", 0)`. The bind address can't be configured. | `tests/adapters/http/test_app.py::test_binds_loopback_only`. `tests/adapters/test_config.py::test_bind_host_key_rejected` |
| S2 | **Per-session token** | `secrets.token_urlsafe(32)`, new on each `watch` start, kept only in the 0600 session file. Compared with `hmac.compare_digest`, and read only from the `X-Kingkai-Token` header. | `tests/adapters/http/test_guards.py::test_missing_token_403`, `::test_wrong_token_403`, `::test_token_from_previous_session_403`, `::test_token_in_query_string_ignored`. `tests/adapters/test_session_file.py::test_mode_0600`, `::test_new_token_each_start` |
| S3 | **Origin check** | `Origin` must match `allowed_origins` exactly. A missing or `null` Origin on POST is rejected. | `test_guards.py::test_foreign_origin_403`, `::test_missing_origin_403`, `::test_null_origin_403`, `::test_lookalike_origin_403` (`http://localhost:3000.evil.com`, `http://localhost:30000`), `::test_preflight_foreign_origin_has_no_acao` |
| S3a | **Host check** (DNS rebinding) | `Host` must be `127.0.0.1:<port>` or `localhost:<port>`. | `test_guards.py::test_rebinding_host_403` |
| S3b | **Force a preflight** | POST requires `Content-Type: application/json`; anything else gets 415. | `test_guards.py::test_form_content_type_415`, `::test_text_plain_415` |
| S3c | **Body limit** | `client_max_size = 4096`. | `test_guards.py::test_oversized_body_413` |
| S4 | **Only files that exist inside the project** | `SourceFiles.resolve` uses realpath, which follows symlinks. `parse_reference` requires a regular file whose real path `is_relative_to(realpath(root))`, re-checks that itself, rejects excluded directories, and requires `1 ≤ line ≤ line_count`. | `tests/domain/test_reference.py::test_dotdot_escape_rejected`, `::test_absolute_outside_root_rejected`, `::test_directory_rejected`, `::test_missing_file_rejected`, `::test_line_zero_and_past_eof_rejected`, `::test_excluded_dirs_rejected` (`node_modules`, `.next`, `.git`, `.venv` inside the root), `::test_domain_rechecks_containment_against_lying_adapter`, `::test_resolved_path_always_inside_root`†. `tests/adapters/test_source_files.py::test_symlink_escape_rejected`, `::test_symlinked_parent_dir_escape_rejected`, `::test_symlink_inside_root_allowed` (real symlinks under `tmp_path`) |
| S5 | **Normalize the path** | Input must be an absolute `file://` URL or an absolute POSIX path of at most 1024 characters; otherwise `bad_scheme` or `too_long`. The output is POSIX, relative to the root, and NFC. Backslashes and empty segments are rejected. Candidates are tried in order. | `test_reference.py::test_normalizes_absolute_inside_root`, `::test_file_url_prefix`, `::test_unknown_scheme_rejected` (`http:`, `about:`, `webpack-internal:`, relative), `::test_backslash_rejected`, `::test_too_long_rejected`, `::test_nfc_normalization`. `tests/application/test_reference_service.py::test_first_valid_candidate_wins`, `::test_node_modules_frame_skipped` |
| S6 | **No newlines or control characters** | A character of Unicode category `Cc`, `Cf`, `Zl` or `Zp` in a candidate causes a rejection. The same characters are stripped from display fields. The rendered text must match the grammar. | `test_reference.py::test_rejects_control_chars` (`\n \r \t \x00 \x1b   ‮ ​`), `::test_render_matches_grammar`†, `::test_render_never_contains_cr_lf_esc`†. `tests/adapters/http/test_payload.py::test_display_fields_stripped_not_rejected`, `::test_bad_kind_422`, `::test_more_than_10_candidates_422` |
| S7 | **No free text, only `@path#L<line> `** | `PromptTyper.type_reference` takes a `Reference`, not a `str`. `Reference.__init__` raises, and only `parse_reference` calls `Reference._mint`: ruff `SLF001` flags any other access, and an AST test checks it too. `render()` re-checks the grammar, and every typer types only `render()` output. Display fields are never typed. | `test_reference.py::test_direct_construction_raises`, `::test_render_rechecks_grammar`. `tests/architecture/test_reference_minting.py::test_mint_called_only_in_parse_reference`. `test_reference_service.py::test_label_selector_page_view_never_typed`. `tests/adapters/test_clipboard.py::test_copies_only_rendered_reference`. mypy `--strict` and ruff in CI. |
| S8 | **Never send Enter** | Delivery is exactly `load-buffer -b <buf> -` (text on stdin), then `paste-buffer -p -d -b <buf> -t <pane>`. `send-keys` is never called, and the text has no CR or LF (S6). | `tests/adapters/test_tmux.py::test_commands_exact`, `::test_never_invokes_send_keys`†. `tests/integration/test_tmux_real.py::test_text_arrives_without_newline`: a real tmux server on a private `-L` socket, with a byte recorder in the pane that turns on bracketed paste. It asserts the exact bytes `ESC[200~` + text + `ESC[201~`. |
| S9 | **Never type into a dialog** | The three checks in §8.4: a recent dialog flag for the pane's session, the pane state, and the screen signatures. If any check fails, the clipboard is used. | `test_reference_service.py::test_recent_permission_request_falls_back_to_clipboard`, `::test_old_flag_defers_to_screen_check`, `::test_uses_session_bound_to_target_pane`. `tests/domain/test_reducer.py::test_permission_request_sets_flag_for_that_agent_only`, `::test_subagent_activity_does_not_clear_main_dialog_flag`, `::test_late_permission_request_after_tool_start_still_blocks`, `::test_turn_boundary_clears_dialog_flags`. `test_tmux.py::test_declines_when_pane_in_mode`, `::test_declines_when_command_not_claude_or_node`, `::test_signatures_match_only_dialog_screens` (every fixture screen). `test_tmux_real.py::test_capture_pane_dialog_detected` |
| S10 | **The hook client can't harm the session** | It always exits 0 with empty stdout and stderr, uses only the stdlib, and validates `session_id` before using it in a path. The spool is 0600 inside 0700 directories, and the shim swallows every failure. | `tests/hook_client/test_main.py::test_exit_zero_on_garbage`, `::test_no_output_ever`, `::test_unwritable_state_dir_still_exit_zero`. `tests/hook_client/test_spool.py::test_bad_session_id_dropped`, `::test_spool_modes`. `tests/adapters/test_settings_installer.py::test_shim_exits_zero_when_python_missing`, `::test_shim_exits_zero_when_module_missing`. import-linter `hook-client-stdlib-only` |
| S11 | **Rate limit** | At most 5 references per second; more get 429. | `test_guards.py::test_rate_limit_429` (injected clock) |
| S12 | **Data is never markup** | Strings that come from data are rendered as Rich `Text` objects (§6.1). | `tests/ui/test_widgets.py::test_display_strings_rendered_without_markup` (`app/[slug]/page.tsx`, `[bold]x[/]`) |

**Threats, and the rules that stop them:**
- A malicious website POSTs to the daemon: S3, S3b, S2.
- DNS rebinding: S3a.
- Another localhost app on a different port: S3 (exact match) and S2.
- Path traversal or symlink escape: S4, S5.
- Terminal injection: S6, S7, S8.
- Accidentally approving a dialog: S9.
- Flooding: S11.
- Spoofed TUI output: S12.

**Out of scope:**
- A local attacker who can already run commands as the user: they can read the token file and use tmux directly.
- Scripts and browser extensions running inside the dev app's own origin: they can read the injected token. That is the trust boundary, and the docs say so.

---

## 10. Error handling

| Class | Example | Behaviour |
|---|---|---|
| Malformed untrusted input | A bad spool or transcript line, an unknown event, a missing field | The translator returns `None` and the line is counted in `Diagnostics` (shown in the footer). kingkai never crashes. Unknown fields are ignored, so new Claude Code fields don't break it. |
| Rejected reference | Outside the root, a bad line | `Rejected(reason)`, returned as a 4xx. The overlay shows a toast and the TUI shows the reason. |
| Delivery declined or failed | tmux missing, pane gone, a dialog | The next typer is tried. If none works, the text is shown for copying. |
| Environment | Spool dir not writable, tmux older than 3.2, invalid `settings.local.json` | Fail fast with a one-line message and a fix hint, exit code 2. `doctor` runs the same checks. |
| Bug in a background task | An exception in a tailer | `supervise()` logs the traceback, raises an `internal` alert, and restarts the task with exponential backoff (max 30 s). |
| Hook client | Anything | Swallowed; it exits 0 silently (S10). |

- **Exceptions vs results.** Exceptions are for programming errors and environment failures. Typed results (`Rejected`, `DeliveryOutcome`, `None` from translators) are for outcomes that are expected with untrusted input.
- **No bare except.** ruff `BLE` allows none outside the hook client and the supervisor.
- **Logging.** It goes to `<state>/kingkai.log` (rotating, 1 MB × 3). Nothing is written to stdout while the TUI runs, and prompt text is never logged.

---

## 11. Testing strategy

The test tree mirrors `src/`, and the pyramid is weighted towards pure tests.

### 11.1 Unit tests (most of the suite)

- **Domain.** The reducer, detectors, references and cost, with table-driven `parametrize`, `FakeClock` and `FakeSourceFiles`.
- **Property tests** (hypothesis):
  - **Out-of-order tolerance:** for any interleaving of a set of calls' start and end events, the per-call state and the file touches are the same. Turn state, dialog flags, alerts and activity depend on order by design, so they get example tests instead.
  - **Idempotency:** applying an event list twice gives the same state as applying it once.
  - **References:** for any generated candidate, `parse_reference` either rejects it or returns a `Reference` whose rendered text matches the grammar and resolves inside the root.
  - **Shrink:** for any payload, `shrink` returns JSON in which every string is ≤ 512 characters. The fingerprints of two shrunk `tool_input`s are equal exactly when the original `tool_input`s are equal. The cut top-level display fields aren't part of the fingerprint.
- **Presenters.** State in, view model out. No Textual.

### 11.2 Contract tests against Claude Code formats

- **Real data.** `tests/fixtures/` holds real hook payloads, transcript lines and screen captures, from Claude Code 2.1.303, scrubbed (see the README there).
- **Spool shape.** The hook fixtures are **raw hook stdin**. Tests turn them into spool lines with `tests/support/spool.py::as_spool_line(payload, n)`, which calls the real `shrink` and `envelope` with deterministic ids (`f"{n:032x}"`) and times. That way the fixtures exercise the hook client's output format too.
- **One place to fail.** When Claude Code changes a format, the fixture tests fail in the anti-corruption layer.
- **Re-recording.** `scripts/scrub_fixtures.py` turns a new capture into fixtures, and `tests/fixtures/README.md` records the version.

### 11.3 Adapter integration tests

- **HTTP:** `aiohttp.test_utils.TestClient` against the real app factory, with fake ports.
- **tmux:** a real tmux server on a private socket, `tmux -L kingkai-test-<uuid>`. The pane runs `tests/integration/byte_recorder.py`, which turns on bracketed paste and writes raw stdin bytes to a file. Marked `integration`, and run in the Ubuntu CI job.
- **Tailer:** temp files written in chunks that split lines, then rotated and truncated.
- **Settings installer and shim:** golden files, idempotency, preservation of user hooks, invalid JSON, and real `sh` runs of the shim.
- **Django:** the Django test client on `examples/django-demo` (Phase 4), against Django 5.2 LTS and 6.1.

### 11.4 UI tests

- **Pilot** (`App.run_test(size=(120, 40))`): events reach the panels, and the key bindings work.
- **Snapshots** (`pytest-textual-snapshot`): 120×40 in Phase 1, and 80×24 once the tabbed layout lands in Phase 2. Always take them after `await pilot.pause()`.

### 11.5 End-to-end (Phase 3 onwards)

`pytest-playwright` drives Chromium against the example apps, with a byte recorder standing in as the Claude pane. It checks the four Spike 0a cases (client root, server element, `.map` item, imported `ui/Button`) and the Django click, and asserts the exact bytes that get typed. The security matrix stays in the faster HTTP tests.

### 11.6 Architecture tests

- **import-linter:**
  - `layers` (ui | adapters → application → domain);
  - `domain-pure` (no asyncio, msgspec, textual or aiohttp in `kingkai.domain`);
  - `hook-client-stdlib-only` (no other `kingkai` package and no third-party package; `include_external_packages = true`).
- **`test_reference_minting.py`** (S7).

### 11.7 Overlay (TypeScript)

Vitest covers candidate resolution (mocked fiber and fetch), absolutizing paths against the app root, the 10-candidate cap and the request builder. The overlay holds no security logic.

### 11.8 Gates

- One branch-coverage gate: **≥ 85 %**.
- The unit tests finish in under 5 s.

---

## 12. Toolchain

Versions were checked on PyPI, npm and GitHub on 2026-10-19.

| Concern | Choice | Why |
|---|---|---|
| Python | `requires-python = ">=3.12"`. CI runs 3.12 and 3.15 on Ubuntu and 3.15 on macOS. | 3.12 is the oldest version with security support that every dependency covers (Django 6.1 needs it). Testing the lowest and newest versions catches what the middle ones would. |
| Packaging | **uv** 0.13 with the **uv_build** backend, a `src/` layout, `[project.scripts]` (`kingkai`, `kingkai-hook`), and `[dependency-groups]`. `uv.lock` is committed. | One fast tool for locking, environments, running and building. uv_build needs no config for a pure-Python package. |
| Runtime deps | `textual>=8.2`, `aiohttp>=3.14`, `msgspec>=0.22`, `cyclopts>=5.2`; the extra `django = ["django>=5.2"]` | **aiohttp:** runs in Textual's loop without taking over signal handlers. **msgspec:** typed, strict and fast decoding of large JSONL; its Structs are plain classes to mypy. **cyclopts:** a type-hint CLI that tests can call with argv, lighter than Typer/Click. |
| Lint and format | **ruff** 0.17: `ruff format`, plus `extend-select` for `ANN, ASYNC, S, TRY, PTH, DTZ, FBT, ARG, ERA, T20, BLE, PL, TC, FURB, RUF, SLF`, relaxed for tests | One fast tool. `extend-select` keeps the larger default set added in ruff 0.16. `SLF` backs S7. Pydocstyle (`D`) is left out: names and types carry the meaning, and docstrings explain *why* where needed. |
| Type checking | **mypy** 2.4 `--strict` as the gate; **ty** in the editor, not gated | mypy is the stable reference, and it caught a real Textual gotcha in research. ty is still 0.0.x beta. pyright strict is noisy with Textual's generics. |
| Tests | **pytest `>=8.4,<9`**, pytest-asyncio 1.4 (`asyncio_mode = "auto"`), pytest-textual-snapshot 1.1, hypothesis, pytest-cov | `<9` because pytest-textual-snapshot pins syrupy 4.8. Lift it when the plugin updates. |
| Architecture | **import-linter** 2.15 | Turns the layering into a CI failure instead of a review comment. |
| Git hooks | **prek** with a standard `.pre-commit-config.yaml`: ruff, ruff-format, mypy, import-linter, and **conventional-pre-commit** v4.4 at `commit-msg` | Enforces Conventional Commits. prek is fast and uv-native, and the config stays compatible with pre-commit. |
| CI | **GitHub Actions** with `astral-sh/setup-uv@v10`. Jobs: `check` (ruff, format, mypy, import-linter); `test` (the matrix above plus the coverage gate; installs tmux and runs the integration tests on Ubuntu); `overlay` (Node 24: biome, tsc, vitest, build; from Phase 3); `e2e` (from Phase 3). Dependabot for uv, npm and actions; actions pinned by SHA. | Few jobs, and each failure says what broke. |
| Overlay | **TypeScript 7** (strict, `noEmit`), **esbuild** 0.28 (IIFE), **Biome** 2.5, **Vitest** 5, **npm** on **Node 24 LTS**; **bippy** pinned exactly | A handful of dev deps, so npm is enough. Biome matches the maintainer's other repos. The bundle is built in CI before `uv build`, and never committed. |
| Release | Phase 5: a hand-made `v0.1.0` tag and GitHub release. PyPI via Trusted Publishing is v2. | PyPI polish is a v2 item. |
| License | **MIT** | Maximum adoption with minimal friction. Apache-2.0's patent grant adds little for a personal dev tool, and MIT matches the maintainer's other public repos. |

### 12.1 Code conventions

- **Types.** Domain types are `@dataclass(frozen=True, slots=True)`, except `Reference` (§3.4). Boundary types are `msgspec.Struct(frozen=True)`, with unknown fields ignored. The envelope field is declared as `kk: Envelope = msgspec.field(name="_kk")`.
- **Modules.** One responsibility and one public surface (`__all__`) per module, roughly ≤ 200 lines each.
- **No `Any`** outside `adapters/*/schema.py`.
- **Time** comes from `Clock`. `datetime.now()` appears only in `adapters/clock.py` and the hook client.
- **Textual:**
  - Never name an attribute `tree`.
  - Build typed widget refs in `__init__` and yield them in `compose`.
  - Write `BINDINGS: ClassVar[list[BindingType]]`.
  - Render data as `Text` (S12).
  - Pause before taking snapshots.
- **Commits** follow Conventional Commits with no attribution trailers. Public artefacts use only `examples/` or the maintainer's personal projects.

---

## 13. Open questions

Q1–Q8 were resolved by Phase 0; see `docs/spikes/0a-react-source.md` and `docs/spikes/0b-tmux-typing.md`. The only one still open:

| ID | Question | Resolved by | Default if inconclusive |
|---|---|---|---|
| Q9 | Django: rewrite in `get_contents` or patch the nodelist? How do include/extends/block map? Does it work with debug-toolbar? | The Phase 4 mini-spike (Task 4.0) | Rewrite in `get_contents` |

---

## 14. Non-goals

- **Not in the MVP:**
  - comparing sessions;
  - historical statistics;
  - Vue and Svelte;
  - Jinja2;
  - an npm package for Next;
  - a PyPI release with a demo GIF;
  - user-tunable alert thresholds;
  - `#L<start>-<end>` ranges.
- **Out of scope:**
  - local AI or any outbound network call;
  - changing Claude's behaviour (hooks never block, decide, or inject context);
  - parsing `Bash` commands for file touches;
  - OpenTelemetry ingestion;
  - native Windows (WSL2, Linux and macOS are supported; the hook client uses `fcntl`);
  - remote or multi-user setups, or any listening address other than 127.0.0.1;
  - typing anything but a `Reference`;
  - production use of the integrations (everything is gated on DEBUG or development).

---

## 15. Phases

The detail is in `docs/superpowers/plans/2026-10-19-kingkai-roadmap.md`. Each phase ends in something that can be demoed.

| Phase | Delivers | Demo / exit |
|---|---|---|
| 0 ✓ | The spikes (`docs/spikes/`) and the fixtures | Done on 2026-10-19 |
| 1 | Toolchain, hook client, `init`/`uninstall`, spool, tailer, reducer, a TUI with agents, timeline and files | A real Claude Code task with 2 subagents shows a live tree and files |
| 2 | Detectors, usage and cost, alerts and usage panels, `doctor`, the supervisor, the tabbed layout | A forced failure loop raises RetryLoop, and cost updates live |
| 3 | HTTP ingress, the reference service, tmux and clipboard typers, the overlay, `up`, the Next snippet, e2e | Alt+click in `examples/next-demo` types `@…#L<n> ` without submitting |
| 4 | The Q9 mini-spike, the Django loader and middleware, e2e | The same, from a Django template |
| 5 | README with a GIF (from a personal project), docs, `v0.1.0` | A fresh clone works by following only the README |
