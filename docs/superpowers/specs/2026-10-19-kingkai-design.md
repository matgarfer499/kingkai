# kingkai: design spec

- **Status:** draft for review, 2026-10-19
- **Scope:** MVP (v1). Session comparison and the other v2 items are in [§14 Non-goals](#14-non-goals).
- **Audience:** whoever builds kingkai. It assumes you know Python and asyncio, but not Claude Code internals.

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
2. **Click-to-reference.** Alt+click an element in the local dev app (Next.js/React 19 or Django templates). The source location of that element, for example `@src/components/Button.tsx#L42 `, is **typed** into the Claude Code prompt as a tmux bracketed paste (`paste-buffer -p`). kingkai never presses Enter. Outside tmux, the reference goes to the clipboard instead.

kingkai uses no local AI and makes no network calls beyond 127.0.0.1.

### 1.1 Decisions inherited from the approved plan (settled)

- Python, Textual, and tmux for delivery, with a clipboard fallback.
- Hooks plus JSONL transcripts as the data sources.
- The security rules in §9.
- `UserPromptSubmit` context injection is ruled out for the MVP.

### 1.2 Where this spec departs from the plan's wording, and why

| Plan says | Spec does | Why |
|---|---|---|
| "Daemon" plus a TUI | **One process.** The daemon is a set of services in the same asyncio loop as the Textual app. The boundary between them is a port (§5), so it can be split into two processes later. | Research confirmed that aiohttp runs inside Textual's loop. Two processes would add an IPC protocol, its versioning and lifecycle bugs, and the MVP gains nothing from that. State survives a TUI restart thanks to the event spool (§5.2). |
| Hook script sends events to the daemon | The hook script **appends to a per-session spool file**, and kingkai tails that file. | A failed command hook shows a `hook error` notice in the Claude Code transcript (hooks docs, "Non-blocking error"). A spool write cannot fail just because kingkai isn't running, so the hook stays silent. The spool also replays history after a restart and handles out-of-order events with the same code. |
| `@ruta:línea` | `@<path><sep><line> `, where `<sep>` is one value of a closed enum chosen by Spike 0b. The default is `#L` (`@src/x.tsx#L42 `). | Claude Code documents `@file#L1-99` and `@file#5-10` (the IDE integration docs). `@file:line` appears nowhere in the docs. The "no free text" rule still holds: the grammar is fixed (§8.4). |
| Hooks in `.claude/settings.json` | Hooks go in **`.claude/settings.local.json`**. | That file is per-user and gitignored. kingkai should never change settings that teammates share. |
| Event list: SessionStart, UserPromptSubmit, Pre/PostToolUse, SubagentStop, Stop | Adds `PostToolUseFailure`, `SubagentStart`, `Notification`, `SessionEnd` and `PreCompact` (§4.1). | The tool-error alert needs `PostToolUseFailure`. The tree needs `SubagentStart` to show a subagent before it ends. Typing must be blocked while a permission dialog is open (§9, rule S9), which needs `Notification`. |

---

## 2. Glossary

- **Session:** one Claude Code conversation, identified by `session_id`.
- **Agent:** the main agent (it has no `agent_id`) or a subagent (`agent_id` plus `agent_type`).
- **Hook payload:** the JSON that Claude Code writes to a hook command's stdin.
- **Spool:** an append-only NDJSON file that holds a session's hook payloads after the hook client has shrunk them.
- **Transcript:** Claude Code's own JSONL file under `~/.claude/projects/<encoded-cwd>/`. Its format is internal and **undocumented**; the docs say it "changes between versions".
- **Domain event:** kingkai's typed, versionless representation of something that happened (§4.2).
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
                 │ adapters: SpoolTailer, TranscriptTailer → translate → events  │
                 │ application: SessionService (reducer + detectors) → Store     │
                 │ application: ReferenceService (validate → deliver)            │
                 │ adapters: HttpIngress (aiohttp, 127.0.0.1:ephemeral)          │
                 │ ui: Textual app ← Snapshot messages (≤10 Hz)                  │
                 └──────────────────────────────▲────────────────────────────────┘
                                                │ POST /v1/references (token + Origin)
 browser: dev app + overlay.js ─────────────────┘
          (token injected server-side by the Django middleware or the Next.js snippet)
```

### 3.2 Layers and the dependency rule

Dependencies only point inwards. import-linter enforces this in CI (§12), so the layering is checked, not just a convention.

| Layer | Package | May import | Contains | Must not contain |
|---|---|---|---|---|
| Domain | `kingkai.domain` | stdlib only | Value objects, domain events, the state model, the reducer, alert detectors, usage and cost arithmetic, reference parsing and rendering | I/O, asyncio, Textual, msgspec, `time.time()` |
| Application | `kingkai.application` | domain | Use cases (`SessionService`, `ReferenceService`), the `Store`, and the **ports** (Protocols) | Concrete I/O, Textual |
| Adapters | `kingkai.adapters` | domain, application | Hook and transcript schemas plus translation (the anti-corruption layer), tailers, aiohttp ingress, tmux, clipboard, settings installer, pricing loader, config loader | UI |
| UI | `kingkai.ui` | domain, application | Textual app, widgets, **presenters** (pure functions from state to view models) | Adapters (the UI only sees ports and the store) |
| Composition | `kingkai.bootstrap`, `kingkai.cli` | everything | Wiring, command-line parsing | Logic |
| Hook client | `kingkai.hook_client` | **stdlib only, no other `kingkai` module** | Reads stdin, shrinks the payload, appends it to the spool | Anything slow to import |
| Integrations | `kingkai.integrations.django` | Django, stdlib | DEBUG-only template loader and middleware. Installed via the `kingkai[django]` extra. | Imports of the daemon |

### 3.3 Module map

```
src/kingkai/
  domain/
    ids.py            SessionId, AgentId, ToolUseId (NewType over str)
    events.py         DomainEvent union (frozen, slotted dataclasses)
    state.py          SessionState, AgentNode, ToolCall, FileTouch, Alert (frozen)
    reducer.py        reduce(state, event) -> SessionState
    tools.py          tool_name -> FileTouch extraction (Read/Edit/Write/...)
    alerts/
      base.py         Detector Protocol: (state, event, now) -> tuple[Alert, ...]
      repeated_call.py, tool_failure.py, stall.py
    usage.py          TokenUsage, Pricing, CostEstimate
    reference.py      ProjectRoot, ProjectPath, LineNumber, Reference, ReferenceFormat,
                      RejectionReason, parse_reference(), render(), and the
                      SourceFiles/ResolvedFile Protocols it needs (a domain-owned port)
  application/
    ports.py          Clock, EventSource, PromptTyper, Clipboard, PaneInspector
    store.py          Store: holds SessionState per session, notifies subscribers
    session_service.py
    reference_service.py
  adapters/
    hooks/schema.py       msgspec Structs for hook payloads (tolerant: unknown fields ignored)
    hooks/translate.py    payload -> DomainEvent | None
    transcript/schema.py  msgspec Structs for the transcript lines we read
    transcript/translate.py
    tail.py               NdjsonTailer: offset-tracking, partial-line-safe, rotation-aware
    http/app.py           aiohttp application factory
    http/guards.py        host/origin/token/content-type/size checks (pure functions)
    tmux.py               TmuxPromptTyper
    tmux_dialogs.py       dialog screen signatures (data, with fixture screens)
    clipboard.py          WSL / macOS / Wayland / X11 clipboards
    source_files.py       real-filesystem SourceFiles
    settings_installer.py idempotent hook install/uninstall in settings.local.json
    pricing.py            loads bundled pricing.toml plus user overrides
    session_file.py       writes .kingkai/session.json (0600)
    config.py             kingkai.toml -> Config
  hook_client/
    __main__.py           entry point for the `kingkai-hook` console script
    shrink.py             pure: payload -> shrunk payload
  ui/
    app.py                KingkaiApp(App[None])
    messages.py           SnapshotUpdated, ReferenceDelivered
    presenters.py         pure: SessionState -> view models
    widgets/              agent_tree.py, files.py, timeline.py, alerts.py, usage.py, reference.py
  integrations/django/
    loaders.py            SourceAnnotatingLoader (filesystem / app_directories variants)
    middleware.py         KingkaiMiddleware (script tag + view location)
  bootstrap.py            build_app(config) -> KingkaiApp   (the composition root)
  cli.py                  cyclopts app: init, uninstall, up, watch, doctor
  assets/overlay.js       built from overlay/ by esbuild (not committed; built in CI)
  assets/pricing.toml
overlay/                  TypeScript source for the browser overlay (own package.json)
examples/next-demo/       minimal Next.js 16 app used by the spikes, e2e tests and demos
examples/django-demo/     minimal Django 6 app used by the e2e tests and demos
```

### 3.4 Patterns, and why each one is here

Each pattern below solves a specific problem in this codebase. Patterns we deliberately leave out are listed too.

1. **Ports and adapters, with `typing.Protocol`.** Claude Code's formats are undocumented or move fast, and tmux, the clipboard and the filesystem are side effects. Protocols in `application/ports.py` let the use cases run in tests against in-memory fakes, with no mocks and no monkeypatching. They are structural, so adapters don't inherit from anything.
2. **Functional core, imperative shell.** All decisions (state transitions, alerts, reference validation, cost) are pure functions in `domain`. The shell only moves bytes. Most tests are then plain function calls with table-driven inputs.
3. **State as a fold over events (light event sourcing).** `SessionState = reduce(reduce(initial, e1), e2) …`. Spool replay after a restart is the same code path as live updates. Out-of-order async hooks are handled in a single place, the reducer, and property tests can check order independence (§11). There is no event store beyond the spool file and no snapshots: sessions are small.
4. **Parse, don't validate (value objects).** A `Reference` comes from `parse_reference()`. Once you hold one, it is safe to type. `PromptTyper.type_reference(ref: Reference)` takes no `str`, so mypy rejects any call that tries to type free text. Python can't truly make a constructor private, so three layers back this up (S7):
   - `Reference.__post_init__` raises unless it receives the module-private capability sentinel `_MINT`, so a direct `Reference(...)` call fails at runtime.
   - ruff `PLC2701` flags any import of a private name.
   - `Reference.render()` checks the result against the grammar regex again before returning, and every typer goes through `render()`, the clipboard as well as tmux.
5. **Anti-corruption layer.** `adapters/hooks` and `adapters/transcript` are the **only** modules that know Claude Code's field names. When a Claude Code release changes them, the fix stays in one place, and the fixture tests (§11.2) catch the drift.
6. **Strategy, for detectors.** Each alert rule is a small object that satisfies `Detector`. `SessionService` gets a tuple of them. A new rule means a new file and one line in `bootstrap.py`.
7. **Composition root and constructor injection.** `bootstrap.build_app()` is the only place that builds concrete adapters. There is no DI container: about ten objects can be wired by hand in one readable function.
8. **Presenter / humble view.** Widgets only render view models that `ui/presenters.py` computes from state. Presenters are pure and unit-tested, which leaves the Textual layer thin, plus a few Pilot and snapshot tests.
9. **Ordered fallback for delivery.** `ReferenceService` holds a tuple of `PromptTyper`s (tmux, clipboard) and uses the first one that accepts. The result says which one delivered, and the TUI shows it.

**Not used, on purpose:** DI frameworks; ABC hierarchies; a plugin registry; the repository pattern (there is no database); a generic event bus library (the `Store` with a subscriber list is enough); CQRS; async generators running through the domain (the domain stays sync).

### 3.5 Key types (signatures, not bodies)

```python
# application/ports.py
class Clock(Protocol):
    def now(self) -> datetime: ...              # timezone-aware UTC

class EventSource(Protocol):
    def events(self) -> AsyncIterator[DomainEvent]: ...

class PromptTyper(Protocol):
    name: str                                   # "tmux", "clipboard"
    async def type_reference(self, ref: Reference) -> DeliveryOutcome: ...

class PaneInspector(Protocol):                  # tmux adapter implements it; fakes in tests
    async def inspect(self, pane: PaneId) -> PaneStatus | None: ...   # None = pane gone

# domain/reference.py
class SourceFiles(Protocol):                    # domain-owned port; read-only
    def resolve(self, root: ProjectRoot, raw: str) -> ResolvedFile | None: ...  # realpath
    def line_count(self, f: ResolvedFile) -> int: ...
# parse_reference also re-checks ResolvedFile.real_path.is_relative_to(root.real_path),
# so a buggy SourceFiles adapter can't widen the boundary.

class ReferenceFormat(StrEnum):
    HASH_L = "#L"                               # default, pending Spike 0b
    COLON = ":"

@dataclass(frozen=True, slots=True)
class Reference:
    path: ProjectPath                           # validated, POSIX, relative to the root
    line: LineNumber
    def render(self, fmt: ReferenceFormat) -> str: ...   # "@{path}{fmt}{line} "

def parse_reference(raw: RawReference, root: ProjectRoot, files: SourceFiles
                    ) -> Reference | Rejected: ...

# domain/reducer.py
def reduce(state: SessionState, event: DomainEvent) -> SessionState: ...
```

`Rejected` is a frozen dataclass that carries a `RejectionReason` (StrEnum). Validation **returns** it instead of raising. A rejection is an expected outcome of handling untrusted input, so the caller has to deal with it, and mypy makes sure of that through the union.

---

## 4. Event model

### 4.1 Hook events we install

All hooks go in `.claude/settings.local.json`, each with a type `command` handler. `kingkai init` writes them and `kingkai uninstall` removes them. Both commands are idempotent. Every entry kingkai writes is identified by its command path, which is the shim below, so user hooks are left alone.
- `init` runs `git check-ignore .claude/settings.local.json`. If the file isn't ignored, `init` offers to add it to `.git/info/exclude`. That file is local and never committed, so the user's `.gitignore` is not touched.
- **A stable shim, so reinstalling can't break hooks.** The hook command is `~/.local/state/kingkai/bin/kingkai-hook`, a POSIX `sh` script written by `init`:

  ```sh
  PY="/abs/venv/bin/python"; [ -x "$PY" ] || exit 0; exec "$PY" -I -m kingkai.hook_client
  ```

  If kingkai is uninstalled or its venv moves, the hook still exits 0 silently. `init` rewrites the shim, and `doctor` checks that it points at a working interpreter.

```json
{ "hooks": { "PreToolUse": [ { "hooks": [ {
    "type": "command",
    "command": "/home/<user>/.local/state/kingkai/bin/kingkai-hook",
    "async": true,
    "timeout": 5
} ] } ] } }
```

| Claude Code event | Why we need it | Fields we read (anything else is ignored) |
|---|---|---|
| `SessionStart` | Opens a session and gives the transcript path | `session_id`, `transcript_path`, `cwd`, `source`, `model?` |
| `UserPromptSubmit` | Opens a turn (the stall detector only runs inside a turn) | `session_id`, `prompt` (only its length and first 80 characters are kept) |
| `PreToolUse` | Tool call started | `tool_name`, `tool_input`, `tool_use_id`, `agent_id?`, `agent_type?` |
| `PostToolUse` | Tool call succeeded | the same as above, plus `duration_ms?` (`tool_response` is shrunk, §5.1) |
| `PostToolUseFailure` | Tool call failed | the same as above, plus `error`, `is_interrupt?` |
| `SubagentStart` / `SubagentStop` | Subagent tree. A `SubagentStop` with no `agent_type` for an agent never seen before is an internal auxiliary agent (for example the prompt-suggestion agent) and is ignored. | `agent_id`, `agent_type`, `agent_transcript_path` (on Stop) |
| `PermissionRequest` | **The dialog signal.** It fires as the permission dialog opens (Spike 0b). It marks the prompt as **not safe to type into**. Our hook never returns a decision. | `tool_name`, `agent_id?` |
| `Notification` | Informational only. Spike 0b showed it is unreliable for dialogs: it fired for 1 of 3. | `notification_type`, `message` |
| `Stop` | Closes the turn | `stop_hook_active` |
| `PreCompact` | Shows compaction on the timeline | `trigger` |
| `SessionEnd` | Closes the session | `reason` |

- **Attribution.** A payload with `agent_id` belongs to that subagent; without it, it belongs to the main agent. This follows the hooks docs, and Spike 0b confirmed it (Q7).
- **`async: true`.** The hook never blocks Claude, and Claude Code doesn't enforce a timeout on async hooks. The `timeout: 5` is there in case async stops being honoured.
- **`SessionEnd`.** It has a 1.5 s default timeout. Appending to the spool takes milliseconds, so that is fine.

### 4.2 Domain events

Domain events are frozen, slotted dataclasses. Every one carries:
- `session_id`;
- `event_id: str`. For hook events this is a UUID4 that the hook client writes into `_kk.id`. For transcript events it is `"<file>:<byte offset>"`.
- `at: datetime`, in UTC: when the hook client received the payload, or the transcript line's `timestamp`.

Order is the order in which the service applies events: spool line order within one file. Field names belong to kingkai, not to Claude Code.

```
SessionStarted(transcript_path, cwd, source, model, tmux_pane)   # tmux_pane from _kk.pane
TurnStarted(kind, prompt_preview)      TurnStopped()   # kind: user | system ("<task-notification>" prompts)
ToolCallStarted(agent, tool_use_id, tool, input_fingerprint, touches)
ToolCallSucceeded(agent, tool_use_id, duration_ms)
ToolCallFailed(agent, tool_use_id, error_summary, interrupted)
SubagentStarted(agent_id, agent_type)  SubagentStopped(agent_id, transcript_path)
AttentionRequested(agent, tool)  # from PermissionRequest
Compacted(trigger)        SessionEnded(reason)
UsageRecorded(agent, message_id, model, usage: TokenUsage)   # from the transcript
Tick(session_id, now)     # synthetic, one per active session per second; never stored
```

- **`agent`.** `AgentRef = Main | Sub(agent_id)`.
- **`input_fingerprint`.** The SHA-256 of the canonical JSON of the shrunk `tool_input`: keys sorted, compact separators. The repeated-call detector compares fingerprints, never raw input.
- **`touches`.** A tuple of `FileTouch(path, kind: read|write|search)`, taken from `file_path` / `notebook_path` / `path` in `tool_input`:
  - read: `Read`
  - write: `Edit`, `MultiEdit`, `Write`, `NotebookEdit`
  - search: `Glob`, `Grep`
  - `Bash` is not parsed (§14).

### 4.3 Reducer rules

- **Correlation by `tool_use_id`.** If a `Succeeded` or `Failed` arrives before its `Started` (possible with async hooks), the reducer records a "dangling end". The matching `Started` closes it when it arrives. The final state is the same in either order, and a property test checks this (§11.1).
- **Idempotency.** An event whose `event_id` the reducer has already applied is a no-op. The state keeps a bounded set of seen ids (the last 10 000). Replay can then overlap with live tailing safely. `UsageRecorded` is additionally deduped by `message_id` (§4.5).
- **Unknown agent.** A `ToolCallStarted` for an `agent_id` with no `SubagentStarted` creates the node implicitly, with `agent_type="unknown"`.
- **Turn and typeability.**
  - `TurnStarted` → `turn_open = True`. `TurnStopped` → `turn_open = False`.
  - `AttentionRequested(agent, tool)` adds `agent` to `awaiting_permission: frozenset[AgentRef]`, and records when it happened.
  - Only events from **that same agent** remove it: its next `ToolCallStarted`, `Succeeded` or `Failed`. A `TurnStopped` or `TurnStarted` clears the whole set. A parallel subagent's activity never clears the main agent's dialog flag.
  - `Notification` (including `idle_prompt`) never blocks typing.
  - A cancelled dialog (Esc) emits **no** event (Spike 0b). The flag would otherwise stay set until the next prompt, so §8.4 layer 3 can override a flag that is more than 1.5 s old once the screen shows no dialog.
- **Abandoned calls.** A denied or cancelled tool call gets no `Succeeded` or `Failed`. On the next `TurnStarted`, and at `SessionEnded`, every call still `running` for that agent becomes `abandoned`.
  - The reducer's flag is only **one of the layers** for S9. Hooks are async and polled, so it can lag. See §8.4 for the pane check done just before typing, and §16 Q-S9 for the residual risk.

### 4.4 Alert detectors (Strategy)

Each detector is `(state_before, event, now) -> AlertChanges`, which holds the alerts to raise and the keys to clear. An alert has a stable `key` (for example `repeated:<agent>:<fp>`), so it is raised once and then updated, never duplicated. It also **clears** when its condition no longer holds.
- "Activity" means a **hook event** for that session. `Tick` and `UsageRecorded` don't count.
- During replay, `now` is the event's own `at`. Time-based detectors stay off until the service emits `ReplayCompleted`, so a restart doesn't raise stale stall alerts.

| Detector | Fires when | Clears when | Default (`kingkai.toml`) | Severity |
|---|---|---|---|---|
| `RepeatedCall` | The same `(agent, tool, input_fingerprint)` appears ≥ N times among that agent's last K tool calls | That fingerprint is in fewer than N of the last K calls | N = 3, K = 10 | warning |
| `ToolFailure` | Any `ToolCallFailed` that isn't an interrupt | Expires 60 s later (informational) | n/a | info |
| `RetryLoop` | ≥ M consecutive failures of the same `(agent, tool)` | The same `(agent, tool)` succeeds | M = 3 | error |
| `Stall` | A turn is open, no agent is awaiting permission, and there has been no activity for T seconds. While a tool call is in flight, the threshold is T_tool instead (checked on `Tick`). | The next activity | T = 120 s, T_tool = 600 s | warning |

The plan's verification criterion ("the same command failing 3 times raises an alert") is covered by both `RetryLoop` and `RepeatedCall`.

### 4.5 Usage and cost

- **Where usage comes from.** `UsageRecorded` events come only from the transcript, because hooks carry no token data. The tailer reads only `type == "assistant"` lines that have `message.usage`. It keeps `message.id`, `message.model`, `input_tokens`, `output_tokens`, `cache_creation_input_tokens` and `cache_read_input_tokens`.
- **Dedupe.** A streamed message may repeat its usage across several lines. The reducer keeps the **last** usage per `message_id`. Usage is keyed by `message_id` across *all* files of a session, so if a subagent's usage also shows up in the main transcript, it is counted once.

  Spike 0b confirmed that repeated usage is **cumulative**, so the last value wins. It also confirmed that subagent usage appears only in the subagent's own file.
- **Subagent usage.** Read from the `agent_transcript_path` that `SubagentStop` reports. While a subagent is still running, the tailer also watches `<session>/subagents/agent-*.jsonl`. The file name is `agent-<agent_id>.jsonl` (confirmed). Auxiliary agents have no transcript, so their usage (small amounts, e.g. Haiku) is not counted, and the UI help says so.
- **Cost.**
  - The estimate is `Σ tokens × price` from `assets/pricing.toml` (USD per million tokens, for each model and each of 5 token kinds: input, output, cache write 5 m, cache write 1 h, cache read). Cache writes are split using `usage.cache_creation.ephemeral_5m_input_tokens` and `ephemeral_1h_input_tokens`.. Users can override it in `kingkai.toml`.
  - The UI always labels it **"≈ API-equivalent"**. It isn't a bill: subscription plans aren't billed per token.
  - If the model has no price, tokens are shown and cost shows `—`. kingkai never guesses a price.
  - **Claude Code's own figure.** When the transcript has a `cost-state` line (internal format; written near the end of a session), kingkai shows its `totalCostUSD` beside the estimate as "Claude Code's estimate". It is optional: parsing failures are ignored.
- **OpenTelemetry.** Claude Code's OTel export is a documented alternative that includes `cost_usd` and `query_source`. It is out of scope for the MVP (§14): it only works for sessions started with OTel env vars, and it would need an OTLP receiver. The `EventSource` port leaves room for it.

---

## 5. Ingress, tailing and daemon/TUI communication

### 5.1 Hook client (`kingkai-hook`)

The hook client is a separate console script. It imports only the stdlib, and an import-linter contract checks that.

1. It reads all of stdin. There is no size cap, because shrinking happens before anything is written.
2. It parses the JSON. If that fails, it exits 0.
3. **Shrink** (`shrink.py`, a pure function, applied recursively to the whole payload):
   - These display fields are **cut** to a preview: `prompt` to 80 characters; `error`, `message` and `last_assistant_message` to 200.
   - Any other string longer than 512 characters becomes `{"$sha256": <hex>, "$len": <n>}`. This keeps the spool small (a `Read` response can carry a whole file) and keeps fingerprints exact.
   - Afterwards, every string in the line is ≤ 512 characters.
4. It adds `"_kk": {"v": 1, "id": <uuid4 hex>, "at": <iso8601 UTC>, "pane": $TMUX_PANE or null}`.
5. It appends one line to the spool file, under an exclusive `fcntl.flock`, with mode 0600.
6. It **always exits 0 and never writes to stdout or stderr**. Every exception is caught and dropped.

**Spool location.** `<state>/spool/<project-key>/<session_id>.ndjson`:
- `<state>` is `$XDG_STATE_HOME/kingkai`, falling back to `~/.local/state/kingkai`. Directories are created with mode 0700.
- `<project-key>` is the first 16 hex characters of `sha256(realpath(CLAUDE_PROJECT_DIR or cwd))`. Claude Code sets `CLAUDE_PROJECT_DIR` for hook processes (hooks docs, "path placeholders").
- `session_id` is checked against `^[A-Za-z0-9-]{1,64}$` before it is used in a path. If the check fails, the payload is dropped.
- Retention: spool files older than 7 days are deleted when `kingkai watch` starts. The spool can contain prompt previews and tool inputs, so it stays under the user's state dir with 0600/0700 permissions.

### 5.2 Tailing

- `NdjsonTailer(path, poll_interval, clock)` yields complete lines only. It keeps a partial trailing line until it gets its `\n`. If the file shrinks or its inode changes, the tailer starts again from offset 0.
- It polls (default 100 ms for spools, 500 ms for transcripts) and uses `asyncio.sleep` with an injected interval, so tests run with zero sleep.
- **Decision (my call):** polling instead of inotify/watchfiles. There is one less dependency, behaviour is the same on WSL, macOS and Linux, tests are deterministic, and the latency is good enough.
- **Discovery.** `SpoolDirectory` scans the project's spool dir every second. It tails every `*.ndjson` modified in the last 24 h, plus any new file that appears, each from offset 0. Each spool also starts a `TranscriptTailer` for the `transcript_path` its `SessionStarted` gives. Thanks to reducer idempotency (§4.3), replay followed by live tailing is safe. Once every file has been read to EOF on startup, the service emits `ReplayCompleted`.
- **Session liveness.** A session is `live` from `SessionStarted` until `SessionEnded`, or until 30 minutes pass with no activity, when it becomes `idle`. A session that crashed without a `SessionEnd` then shows as idle, not live forever. The switcher lists live sessions first. The default is the newest session bound to `--pane` (§8.4), or else the newest live one.
- **Project root.** `watch`, `init` and `up` walk up from the cwd to the nearest directory containing `.claude/` or `.git/`. `--root` overrides this. `doctor` warns when the spool's `CLAUDE_PROJECT_DIR`-based key differs from the resolved root.

### 5.3 Daemon to TUI

Both run in one process and one asyncio loop.

- `Store` keeps `dict[SessionId, SessionState]` and a list of subscriber callbacks.
- `SessionService.run()` drains the `EventSource`s. For each event it runs `reduce` and the detectors, and puts the new state in the store.
- The Textual app subscribes. Its callback coalesces changes to **at most 10 Hz**, keeping only the latest snapshot, and calls `app.post_message(SnapshotUpdated(snapshot))`. Widgets update from presenters.
- A `Tick` event goes into the service every second for the time-based detectors.
- Background tasks run as Textual `@work` async workers (`exclusive=True`, with a group per task). The servers are started in `on_mount` and stopped in `on_unmount`.
- The aiohttp ingress uses `AppRunner` plus `TCPSite`, which doesn't touch signal handlers. uvicorn does replace them, which is why it isn't used.
- **Splitting later:** if the TUI and daemon ever need to be separate processes, `Store` subscriptions become a stream over a Unix socket. Nothing in `domain` or `application` would change.

---

## 6. CLI

`cyclopts` builds the CLI. Every command can be called in tests as a function with an argv list.

| Command | What it does |
|---|---|
| `kingkai init [--next] [--django]` | Installs the hooks in `.claude/settings.local.json` (with a diff preview; `--yes` skips it). It creates `.kingkai/` with its own `.gitignore` containing `*`, so the user's `.gitignore` is never edited. With `--next` / `--django` it prints the integration snippet (§8.2, §8.3); it never edits app code. |
| `kingkai uninstall` | Removes kingkai's hook entries and `.kingkai/`. |
| `kingkai up` | Creates or attaches the tmux session `kingkai-<dir>`: `claude` on the left, `kingkai watch --pane <%id>` on the right. The Claude pane id is recorded at creation time. |
| `kingkai watch [--pane %N]` | Starts the TUI and the services. Without `--pane` (outside `up`), references go to the clipboard. |
| `kingkai doctor` | Checks Python, tmux (≥ 3.2), installed hooks, the spool dir and its permissions, a clipboard backend, and the session file. It explains any failure in one line. |

### 6.1 TUI layout and key bindings

```
┌ kingkai · myapp · session 3f2a… (live) ───────────────────── ≈ $0.42 · 81k tok ┐
│ Agents                     │ Timeline                                          │
│ ▼ main  ● working          │ 10:02:11 main  Read   src/app/page.tsx       12ms │
│   ├ Explore  ✓ done        │ 10:02:12 sub1  Grep   "useAuth"              40ms │
│   └ general  ● working     │ 10:02:15 main  Bash   ✗ exit 1               2.1s │
├────────────────────────────┼───────────────────────────────────────────────────┤
│ Files                      │ Alerts                                            │
│ W src/app/page.tsx      2  │ ⚠ RetryLoop  main · Bash failed 3× in a row       │
│ R src/lib/auth.ts       1  │ ⚠ Stall      no activity for 2m (turn open)       │
├────────────────────────────┴───────────────────────────────────────────────────┤
│ Last reference: @src/components/Button.tsx#L42  → typed (tmux %3) · Button      │
└ s sessions  a agent filter  f files: all/written  c clear alerts  ? help  q quit ┘
```

| Key | Action |
|---|---|
| `s` | Session switcher (modal list) |
| `a` | Filter the timeline and files by the agent selected in the tree (toggle) |
| `f` | Files panel: show all touches, or written files only |
| `c` | Dismiss the current alerts. They come back if their condition fires again. |
| `y` | Copy the last reference to the clipboard (the manual fallback) |
| `?` | Help screen |
| `q` / `ctrl+q` | Quit |

Below 100 columns, the layout collapses to tabs (`1`–`4` switch panels). Snapshot tests cover 120×40 and 80×24.

---

## 7. Configuration

`kingkai.toml` sits at the project root, is optional, and is parsed into a frozen `Config`. Unknown keys are an error: a typo should not be silently ignored.

```toml
[references]
format = "#L"                     # "#L" | ":"
allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:8000", "http://127.0.0.1:8000"]
[alerts]
repeated_call = { threshold = 3, window = 10 }
retry_loop = { threshold = 3 }
stall_seconds = 120
[pricing."claude-opus-5-5"]       # optional overrides, USD per MTok
input = 0.0                        # (example key shape only)
```

---

## 8. Click-to-reference

### 8.1 Overlay protocol

The browser overlay is TypeScript in `overlay/`. esbuild bundles it into one IIFE (`assets/overlay.js`), and it renders inside a closed shadow root so it shares no CSS with the app.

**Bootstrap.** The page includes `<script src="{url}/overlay.js" data-kingkai-url="{url}" data-kingkai-token="{token}" defer>`. The tag is **rendered server-side** by the framework integration, which reads `.kingkai/session.json`. The overlay itself is static and holds no secret. Any site may load `overlay.js`, and gains nothing from it: the token lives only in the dev app's own HTML, which other origins can't read (same-origin policy).

**Session file.** `.kingkai/session.json` is created with mode 0600 and deleted on a clean exit. If its pid is gone, it is stale and gets overwritten.

```json
{ "v": 1, "url": "http://127.0.0.1:53817", "token": "<43 chars, secrets.token_urlsafe(32)>",
  "root": "/home/<user>/dev/myapp", "pid": 4242, "started_at": "2026-10-19T10:00:00Z" }
```

The port is ephemeral (bound to `127.0.0.1:0`). That's possible because the integrations read the URL from this file, and it avoids port conflicts.

**Integrations read the session file on each request.** They cache it by mtime and inject **nothing** when the file is missing or its pid is dead. When kingkai restarts, the port and token change. If the overlay's POST fails to connect or gets `403 token`, the overlay shows "kingkai restarted, reload the page".

**Paths.** Integrations send **absolute** file paths. Django's loader writes `origin.name`, and the React method is normalized to absolute in the overlay where possible. Python is the only place paths are made relative, against `root`. That keeps monorepos and Django `BASE_DIR` layouts unambiguous.

**Interaction.**
- Holding Alt highlights the element under the pointer and shows a label (`Button.tsx:42`).
- Alt+click is captured in the **capture phase** with `preventDefault()` and `stopPropagation()`, so the app's handlers and the browser's Alt+click download are suppressed.
- Esc cancels.
- The result shows as a toast: "typed into Claude Code", "copied to clipboard" or "rejected: <reason>".

**HTTP API (v1).** Only these routes exist; every other path returns 404.

| Route | Auth | Purpose |
|---|---|---|
| `GET /overlay.js` | Host check only | Static asset, `Cache-Control: no-store` |
| `OPTIONS /v1/references` | Host and Origin | CORS preflight. Only allowlisted origins get `Access-Control-Allow-Origin: <exact origin>`, plus `Allow-Headers: content-type, x-kingkai-token`, `Allow-Methods: POST` and `Vary: Origin` |
| `POST /v1/references` | Host, Origin, token, content type, size | Submit a click |

Request body (≤ 4 KiB, `Content-Type: application/json`):

```json
{ "v": 1,
  "source": { "kind": "react", "file": "src/components/Button.tsx", "line": 42, "column": 7 },
  "label": "Button",                 "selector": "main > div:nth-child(2) > button",
  "page": "http://localhost:3000/settings" }
```

- `source.kind` is `react` or `django`.
- `source.file` may be relative to the project root, absolute, or a `file://` URL. Before validation, the adapter normalizes it with a **closed list** of prefixes: `file://`, plus whatever Spike 0a finds the chosen React method produces.
- `label`, `selector`, `page` and `view` (Django's `kingkai-view` meta, shown next to the reference) are **only displayed in the TUI**. They are never typed, and before display they are **stripped** of control characters and cut to 120 characters. The `source.*` fields are **rejected** if they contain any (S6).

Responses:
- `200 {"status": "typed" | "copied" | "shown", "text": "@src/components/Button.tsx#L42 "}`. Delivery finishes before the response is sent.
- `400` / `403` / `413` / `415` / `422` / `429 {"error": "<code>"}`, where `<code>` is a `RejectionReason` or a guard code.

### 8.2 React 19 / Next.js 16: where the source location comes from (open question → Spike 0a)

React 19 removed `_debugSource` and the `__source` JSX prop (react#28265). The two candidate replacements:

| | **A. Build-time attribute** | **B. Runtime owner stack** |
|---|---|---|
| How | `code-inspector-plugin` 2.0.9 through `turbopack.rules` adds `data-insp-path="file:line:col:tag"` | Read the DOM node's fiber, then `_debugStack`, then symbolicate with source maps (what bippy 0.7 / react-grab do) |
| Server Components | Works: the attribute is in the RSC HTML | Needs Next's private `/__nextjs_original-stack-frames` dev endpoint |
| Setup | A change to `next.config.ts` | Only the overlay script |
| Fragility | Loader or Turbopack API changes. DOM rendered by libraries has no attribute. | React internals, a private Next endpoint, the 10k owner-stack limit. `captureOwnerStack()` returns null in DOM event handlers. |
| Read | Synchronous DOM read | Asynchronous (fetches the maps) |

**Spike 0a must answer these:**
1. Which method gives the right `file:line` on Next 16.4 / React 19.3 with Turbopack in these four cases: (a) a client component, (b) a server component, (c) a list item rendered with `.map`, (d) a component imported from `src/components/ui/`.
2. In what form the path comes out (absolute? relative? which URL scheme?).
3. Whether it survives HMR.
4. How much configuration a user has to add.

**Default if the spike is inconclusive:** A first, falling back to B, as research suggested. The overlay reads `data-insp-path` first and only runs B when it's missing.

**Next.js integration in the MVP:** `kingkai init --next` prints a dev-only server component snippet (about 15 lines, for the root layout) that reads `.kingkai/session.json` and renders the script tag, plus the `next.config.ts` lines if method A is chosen. **Decision (my call):** there's no npm package in the MVP. A snippet is easy to audit, and publishing to npm is v2.

### 8.3 Django: DEBUG-only template loader (open questions → Phase 3 spike)

- **Loader.** `SourceAnnotatingLoader` subclasses `django.template.loaders.filesystem.Loader`, with a second variant for `app_directories.Loader`, so that `Origin.loader is self`, which `cached.Loader` needs.
  - `get_contents(origin)` tokenizes the source with `django.template.base.Lexer`. Only in **TEXT** tokens, it inserts ` data-src="<relpath>:<line>"` right after each opening `<tagname`. It skips `<!doctype`, comments, closing tags, and the bodies of `<script>` and `<style>`.
  - It never adds newlines, so line numbers in debug pages stay correct.
  - It only runs on `.html` and `.htm` templates, and is a no-op unless `settings.DEBUG` is true.
- **Middleware.** `KingkaiMiddleware` (DEBUG only, `text/html` responses only):
  - injects the overlay script tag before `</body>`;
  - adds `<meta name="kingkai-view" content="<relpath>:<line>">`, using `request.resolver_match.func` (or `.view_class` for class-based views) and `inspect.getsourcelines`.
- **Open questions for the Phase 3 spike:**
  1. Should the source be rewritten in `get_contents`, or should the compiled nodelist's `TextNode`s be patched afterwards? Patching would leave `Template.source` untouched in debug pages.
  2. What exactly happens with `{% include %}`, `{% extends %}` and `{% block %}` (expected: each element maps to the file it appears in).
  3. Do tags whose name is built by template logic (`<{{ tag }}>`) fail safely?
  4. Does it behave correctly with `django-debug-toolbar` installed?
  5. Is Jinja2 support via `Extension.preprocess` cheap enough for the MVP? (Default: no, it goes to v2.)

### 8.4 The typed reference: grammar and delivery

**Grammar.** This is the only text kingkai ever types:

```
typed   = "@" path sep line " "
path    = segment *( "/" segment )          ; relative to the project root, POSIX separators
segment = Python regex [\w.\-()\[\]@+]+ with re.UNICODE \w (letters, digits, "_")
          ; "." and ".." are not allowed as a whole segment
sep     = "#L" / ":"                        ; ReferenceFormat; chosen once per config
line    = [1-9][0-9]*                       ; 1 ≤ line ≤ number of lines in the file
```

The whole-string regex is `^@(?:[\w.\-()\[\]@+]+/)*[\w.\-()\[\]@+]+(?:#L|:)[1-9][0-9]* $`, plus a check on `.` and `..` segments. The rendered path is the **resolved filesystem name** made relative to the root, so the user can't choose its spelling. It is NFC-normalized before matching against the grammar.

- Next.js app-router paths are allowed (`app/(marketing)/[slug]/page.tsx`).
- Spaces, `;`, `#`, `:`, quotes, backslashes and every control or format character are rejected.

> **Decision (my call):** paths containing spaces are rejected in the MVP. Spike 0b checks whether Claude Code accepts a quoted mention.

**Delivery via tmux: bracketed paste** (decided by Spike 0b for policy (a)). It runs two commands, both through `asyncio.create_subprocess_exec`, with no shell:
1. `("tmux", "load-buffer", "-b", buf, "-")`, with `text` written to stdin;
2. `("tmux", "paste-buffer", "-p", "-d", "-b", buf, "-t", pane_id)`.

- `buf` is `kingkai-<uuid4 hex>`, unique for each delivery.
- `-p` wraps the text in bracketed-paste markers, so Claude Code receives a single paste event, and dialog digit hotkeys can't fire. Spike 0b showed that split `send-keys` keystrokes *can* fire them.
- `-d` deletes the buffer afterwards.
- tmux never parses the text for key names or `;`.
- **Residual risk:** tmux 3.4 can't report whether the pane enabled bracketed paste. Layers 1–3 below still apply.

**Which session a pane belongs to.** The hook client records `$TMUX_PANE` in every payload (`_kk.pane`). `ReferenceService` checks typeability against the **newest session whose `tmux_pane` equals the target pane**. If no session is bound to the pane yet (Claude has just started), only the pane checks below apply.

**Checks just before typing.** These are layered and all must pass; otherwise the tmux typer declines and the next typer in the fallback order is tried.
1. The domain flag: no agent of the bound session is in `awaiting_permission` (§4.3).
2. `tmux display-message -p -t <pane> '#{pane_id} #{pane_in_mode} #{pane_current_command}'`. The pane must exist, must not be in copy mode, and its command must be `claude` or `node`.
3. **Dialog detection on screen.** `tmux capture-pane -p -t <pane>` shows the visible screen, which must not match a dialog signature.
   - The primary signature is `Esc to cancel` within the bottom 15 lines. It matched the permission and folder-trust dialogs, and none of the idle, working, `@`, `/` or after-Esc screens.
   - The secondary signature is a line matching `^\s*❯ \d+\. ` (a numbered menu cursor).
   - The signatures live in `adapters/tmux_dialogs.py` as data and are tested against `tests/fixtures/screens/`.
   - **Layer 1 override:** if the dialog flag is more than 1.5 s old and the screen shows no dialog, the flag is treated as stale (a cancelled dialog) and cleared.
   - The screen is never used to infer prompt contents: the grey prompt suggestion looks like real text in `capture-pane -p`.

**Clean environment.** `kingkai up` starts the Claude pane with the parent's Claude Code session variables removed: `CLAUDECODE`, `CLAUDE_CODE_*` and `CLAUDE_PID`. They leak into child processes otherwise (Spike 0b).

**Fallback.** The clipboard comes next. If no clipboard works, the TUI shows the text in a selectable widget.

| Platform | Command | Notes |
|---|---|---|
| WSL | `powershell.exe -NoProfile -NonInteractive -Command "Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('<b64>')))"` | `clip.exe` garbles anything that isn't ASCII (tested). Takes about 0.2 s. |
| macOS | `pbcopy`, with `LANG=en_US.UTF-8` in its env | |
| Wayland | `wl-copy` | Do not wait on piped stdout: it forks |
| X11 | `xclip -selection clipboard` | |

**Spike 0b answers** (`docs/spikes/0b-tmux-typing.md`):
- `#L` resolves and the model receives exactly that line; `:` doesn't resolve.
- The `@` menu closes on the trailing space, and the text is left unchanged.
- The reference is inserted at the cursor.
- While Claude is working, the text stays in the prompt and isn't submitted.
- `()` and `[]` paths work.
- `pane_current_command` is `claude` for the native install.

---

## 9. Security model

kingkai is a process that types into a terminal running an agent with tool access, so it is a target. These rules are not negotiable. **Each one is enforced by the test named next to it.** Tests marked † are property-based (hypothesis).

| # | Rule (from the plan unless marked *new*) | Mechanism | Enforcing test(s) |
|---|---|---|---|
| S1 | **Listen on localhost only** | aiohttp `TCPSite("127.0.0.1", 0)`. Binding to anything else is not configurable. | `tests/adapters/http/test_bind.py::test_binds_loopback_only` (checks `getsockname()[0] == "127.0.0.1"`). `test_config_rejects_bind_host_key`. |
| S2 | **Per-session token** | `secrets.token_urlsafe(32)`, new on every `watch` start, stored only in `.kingkai/session.json` (0600). Compared with `hmac.compare_digest`. Sent in the `X-Kingkai-Token` header, never in the URL. | `tests/adapters/http/test_guards.py::test_missing_token_403`, `::test_wrong_token_403`, `::test_token_from_previous_session_403`, `::test_token_in_query_string_ignored`. `tests/adapters/test_session_file.py::test_mode_0600`, `::test_new_token_each_start`. |
| S3 | **Origin check** | `Origin` must exactly match an entry in `allowed_origins`: no wildcards, no suffix or prefix matching. A missing `Origin` is rejected on POST. | `test_guards.py::test_foreign_origin_403`, `::test_missing_origin_403`, `::test_null_origin_403`, `::test_lookalike_origin_403` (`http://localhost:3000.evil.com`, `http://localhost:30000`). `::test_preflight_foreign_origin_has_no_acao`. |
| S3a | *new*: **Host check** (DNS rebinding) | `Host` must be `127.0.0.1:<port>` or `localhost:<port>` | `test_guards.py::test_rebinding_host_403` |
| S3b | *new*: **Force a preflight** | POST requires `Content-Type: application/json`. Otherwise 415, so no "simple" CORS request can get through. | `test_guards.py::test_form_content_type_415`, `::test_text_plain_415` |
| S3c | *new*: **Body limit** | `client_max_size = 4096` | `test_guards.py::test_oversized_body_413` |
| S4 | **References only to files that exist inside the project** | `parse_reference` uses `SourceFiles.resolve` (realpath, which follows symlinks) and requires `is_relative_to(realpath(root))`, a regular file, and `1 ≤ line ≤ line_count`. | `tests/domain/test_reference.py::test_dotdot_escape_rejected`, `::test_absolute_outside_root_rejected`, `::test_directory_rejected`, `::test_missing_file_rejected`, `::test_line_zero_and_past_eof_rejected`, `::test_resolved_path_always_inside_root`†, `::test_domain_rechecks_containment_against_lying_adapter`. Real filesystem, using `tmp_path` with real symlinks: `tests/adapters/test_source_files.py::test_symlink_escape_rejected`, `::test_symlinked_parent_dir_escape_rejected`, `::test_symlink_inside_root_allowed`. |
| S5 | **Normalize the path** | Normalized to POSIX, relative to the root. `.` and `..` segments, empty segments and backslashes are rejected. `file://` and the spike-chosen prefixes are stripped through a closed list. | `test_reference.py::test_normalizes_absolute_inside_root`, `::test_file_url_prefix`, `::test_unknown_scheme_rejected`, `::test_backslash_rejected` |
| S6 | **No newlines or control characters** | Any char of Unicode category `Cc`, `Cf`, `Zl` or `Zp` in a `source.*` field causes a **rejection**. The same chars are **stripped** from display-only fields. The rendered text must match the grammar regex (§8.4). | `test_reference.py::test_rejects_control_chars` (parametrized over `\n \r \t \x00 \x1b   ‮ ​`). `::test_render_matches_grammar`†. `::test_render_never_contains_cr_lf_esc`†. `tests/adapters/http/test_payload.py::test_display_fields_stripped_not_rejected`. |
| S7 | **No free text, only `@path<sep>line `** | Typing goes through `PromptTyper.type_reference(ref: Reference)`, which takes no `str` (mypy enforces this). `Reference` can only be minted through `parse_reference`: `__post_init__` checks for the private `_MINT` sentinel, and ruff `PLC2701` bans importing private names. `Reference.render()` checks the grammar regex again, and every typer (tmux and clipboard) types only `render()` output. `label`, `selector`, `page` and `view` are display-only. | `tests/domain/test_reference.py::test_direct_construction_raises`, `::test_render_rechecks_grammar`. `tests/application/test_reference_service.py::test_label_selector_page_view_never_typed`. `tests/adapters/test_clipboard.py::test_copies_only_rendered_reference`. mypy `--strict` and ruff in CI. |
| S8 | **Never send Enter** | The only commands are `load-buffer -b <buf> -` (text on stdin) and `paste-buffer -p -d -b <buf> -t <pane>`. No code path runs `send-keys`, so no key names are ever sent. The text never contains CR or LF (S6). | `test_tmux.py::test_commands_exact`, and `::test_never_invokes_send_keys`†: for any Reference, exactly two commands run, `["tmux","load-buffer","-b",buf,"-"]` with `stdin == text`, then `["tmux","paste-buffer","-p","-d","-b",buf,"-t",pane]`, and no argv contains `send-keys`. Integration: `tests/integration/test_tmux_real.py::test_text_arrives_without_newline`. It uses a real tmux server on a private `-L` socket; the pane runs a byte recorder that turns bracketed paste on. The test asserts the exact bytes received, `ESC[200~` + text + `ESC[201~`, and that there is no `\r` or `\n`. |
| S9 | *new*: **Never type into a dialog** | Three layers (§8.4), and every one must pass: (1) the agent-scoped `awaiting_permission` flag of the session bound to the pane; (2) the pane is not in copy mode and is running `claude` or `node`; (3) `capture-pane` matches no recorded dialog signature. If any layer fails, the reference goes to the clipboard. The residual risk is in §16 Q-S9. | `test_reference_service.py::test_permission_prompt_falls_back_to_clipboard`, `::test_uses_session_bound_to_target_pane`. `tests/domain/test_reducer.py::test_subagent_activity_does_not_clear_main_dialog_flag`, `::test_late_notification_after_tool_start_still_blocks`, `::test_idle_prompt_does_not_block`. `test_tmux.py::test_declines_when_pane_in_mode`, `::test_declines_when_dialog_signature_on_screen` (fixture screens from Spike 0b). Integration: `test_tmux_real.py::test_capture_pane_dialog_detected`. |
| S10 | *new*: **Hook client can't harm the session** | It always exits 0 with empty stdout and stderr, uses the stdlib only, and validates `session_id` before using it in a path. The spool has mode 0600 inside a 0700 directory. | `tests/hook_client/test_main.py::test_exit_zero_on_garbage`, `::test_no_output_ever`, `::test_bad_session_id_dropped`, `::test_spool_modes`. import-linter contract `hook-client-stdlib-only`. |
| S11 | *new*: **Rate limit** | At most 5 references per second. Excess requests get 429. This stops a buggy overlay from flooding the prompt. | `test_guards.py::test_rate_limit_429` (with an injected clock) |

**Threats we consider, and the rule that stops each one:**
- A malicious website POSTs to the daemon: S3, S3b, S2.
- DNS rebinding: S3a.
- Another localhost app on a different port: S3 (exact match) and S2.
- Path traversal or symlink escape: S4 and S5.
- Terminal injection through control characters or key names: S6, S7, S8.
- Accidentally approving a permission prompt: S9.
- Flooding: S11.

**Out of scope:** a local attacker who can already run commands as the user. That attacker can read the token file and type into tmux directly.

---

## 10. Error handling

| Class | Example | Behaviour |
|---|---|---|
| Untrusted input is malformed | A bad spool or transcript line, an unknown event, a missing field | Translation returns `None`. The line is skipped and counted in `Diagnostics` (shown in a TUI footer, e.g. "3 lines skipped"). One log line per distinct reason. **Never crash.** Unknown fields are ignored so that kingkai keeps working when Claude Code adds fields. |
| A reference is rejected | Path outside the root, bad line | A `Rejected(reason)` value, returned as 4xx `{"error": reason}`. The overlay shows a toast, and the TUI "last reference" panel shows the reason. |
| Delivery declined or failed | tmux missing, pane gone, pane in copy mode, permission dialog | The next typer in the fallback is tried. The TUI shows which one delivered. If all of them fail, the text is shown so the user can copy it. |
| Environment or startup | Not a project dir, `CLAUDE_PROJECT_DIR` mismatch, spool dir not writable, tmux older than 3.2 | Fail fast with a one-line error and a fix hint. Exit code 2. `doctor` runs the same checks. |
| Bug in a background task | An exception in a tailer | A supervisor around each worker logs the traceback to `<state>/kingkai.log`, raises an `internal` alert in the TUI, and restarts the task with exponential backoff (max 30 s). One task failing doesn't take the UI down. |
| Hook client | Anything | It swallows every exception and exits 0 silently (S10). |

Exceptions are used for programming errors and environment failures. Typed return values (`Rejected`, `DeliveryOutcome`, `None` from translators) are used for outcomes that are **expected** when handling untrusted input. There are no bare `except:` clauses outside the hook client and the supervisor, and ruff's `BLE` rule enforces that.

Logging uses stdlib `logging` writing to `<state>/kingkai.log` (rotating, 1 MB × 3). Nothing is written to stdout while the TUI is running. Prompt text is never logged.

---

## 11. Testing strategy

There is one test tree, and it mirrors `src/`. The test pyramid weighs heavily towards pure tests.

### 11.1 Unit tests (fast, pure; most of the suite)

- **Domain.** The reducer, the detectors, reference parsing and rendering, and usage/cost, all with table-driven `pytest.mark.parametrize`. A `FakeClock` and a `FakeSourceFiles` (an in-memory tree; real symlinks are tested against the real adapter, S4) are injected.
- **Property tests** (hypothesis):
  - For any interleaving of the `Started` and `Succeeded`/`Failed` events of a set of tool calls, `reduce` gives the same **per-tool-call state** and the same file touches (out-of-order tolerance). Turn state, dialog flags, alerts and last activity *depend on order by design*, so they get example-based tests instead.
  - Applying an event twice is the same as applying it once (idempotency).
  - For any generated raw path or line, `parse_reference` either rejects it or returns a `Reference` whose rendered text matches the grammar regex and resolves inside the root (S4, S6).
  - For any payload, `shrink` returns valid JSON whose strings are all ≤ 512 characters, with the same fingerprint for equal inputs and different fingerprints for different `tool_input`s.
- **Presenters.** State in, view model out. No Textual involved.

### 11.2 Contract tests against Claude Code formats

- `tests/fixtures/hooks/*.json` and `tests/fixtures/transcripts/*.jsonl` are **real payloads**. They are recorded in Phase 0 and Phase 1 from runs against `examples/` (never an employer project) and scrubbed by `scripts/scrub_fixture.py`, which replaces home paths, user names and session ids.
- Each fixture is loaded through the schema and translator, and the domain event that comes out is asserted.
- When Claude Code changes a format, a fixture test fails in one place (the anti-corruption layer).
- `tests/fixtures/README.md` records the Claude Code version each fixture came from.

### 11.3 Adapter integration tests

- **HTTP:** `aiohttp.test_utils.TestClient` runs the whole S1–S11 matrix against the real app factory with fake ports.
- **tmux:** a real tmux server on a private socket (`tmux -L kingkai-test-<uuid>`). The pane runs `python -m tests.integration.byte_recorder`, which writes raw stdin bytes (in raw mode) to a file. Tests assert exact bytes. This job runs where tmux is installed (CI Ubuntu and macOS) and is skipped elsewhere with a clear reason.
- **Tailer:** writes to temporary files in chunks that split lines, rotates them, and truncates them.
- **Settings installer:** golden-file tests that it is idempotent and keeps unrelated user hooks and keys intact.
- **Django integration:** the Django test client on `examples/django-demo` templates, asserting `data-src` values, include/extends mapping, script injection and DEBUG gating. Runs against Django 5.2 LTS and 6.1.

### 11.4 UI tests

- **Pilot** (`App.run_test(size=(120, 40))`): the feed reaches the panels, keyboard navigation works, and the session switcher works.
- **Snapshots** (`pytest-textual-snapshot`): one per main screen state (empty, live session with 2 subagents, alerts, rejected reference). Snapshot tests always run after `await pilot.pause()`, and around screen switches they wait for Textual 8's 50 ms delay.

### 11.5 End-to-end (Phase 3 onwards, separate CI job)

`pytest-playwright` drives Chromium against `examples/next-demo` and `examples/django-demo`, with kingkai running and a tmux byte recorder as the Claude pane. The test Alt+clicks an element and asserts the exact typed bytes. The same job also checks that a page served from a foreign origin gets a 403.

### 11.6 Architecture tests

- import-linter contracts (§3.2) run in CI: `layers` (ui | adapters → application → domain), `hook-client-stdlib-only` (forbids `kingkai.*` and every third-party package), and `domain-pure` (forbids asyncio, msgspec, textual and aiohttp in `kingkai.domain`).

### 11.7 Overlay (TypeScript)

- Vitest covers source extraction (attribute parsing, path normalization helpers) and the request builder.
- The overlay holds no security logic. All validation happens in Python (S4–S7).

### 11.8 Gates

- **Coverage:** branch coverage ≥ 90 % for `domain` and `application`, ≥ 80 % overall, enforced by `coverage report --fail-under` per package.
- **Speed:** all unit tests together < 5 s.

---

## 12. Toolchain

Versions were checked on PyPI, npm and the GitHub releases on 2026-10-19.

| Concern | Choice | Why |
|---|---|---|
| Python | `requires-python = ">=3.12"`; CI on 3.12, 3.13, 3.14, 3.15 | 3.12 is the oldest version with security support that all the dependencies cover (Django 6.1 needs it). It gives us PEP 695 generics and `StrEnum`. |
| Packaging and env | **uv** 0.13 with the **uv_build** backend, a `src/` layout, `[project.scripts]` (`kingkai`, `kingkai-hook`), and `[dependency-groups]` for dev | One fast tool for locking, venvs, running and building. uv_build needs no config for a pure-Python package. `uv.lock` is committed. |
| Runtime deps | `textual>=8.2`, `aiohttp>=3.14`, `msgspec>=0.22`, `cyclopts>=5.2`. Extra `django = ["django>=5.2"]` | **aiohttp:** HTTP that runs in Textual's loop without taking over signal handlers. **msgspec:** typed, strict and fast decoding of large JSONL at the boundary, and its Structs are plain classes for mypy. **cyclopts:** a type-hint driven CLI, testable by calling it with argv, and lighter than Typer/Click. |
| Lint and format | **ruff** 0.17: `ruff format` plus `extend-select` for `ANN, ASYNC, S, TRY, PTH, DTZ, FBT, ARG, ERA, T20, BLE, PL, TC, FURB, RUF`, relaxed for tests | One tool, very fast. `extend-select` keeps 0.16's larger default set. `PLC2701` backs S7. Pydocstyle (`D`) is left out on purpose: names and types should carry the meaning, and docstrings are written where they explain *why*. Forcing them everywhere produces noise. |
| Type checking | **mypy** 2.4 `--strict` as the CI gate. **ty** is recommended in the editor but not gated. | mypy is the stable reference for typeshed, and in research it caught a real Textual gotcha (the `tree` property clash). ty is still a 0.0.x beta, so gating CI on it would break builds for no reason. pyright strict was noisy with Textual's generics. |
| Tests | **pytest 8.4.x (`>=8.4,<9`)**, pytest-asyncio 1.4 (`asyncio_mode = "auto"`), pytest-textual-snapshot 1.1, hypothesis, pytest-cov | `pytest<9` is required because pytest-textual-snapshot pins syrupy 4.8, which caps pytest. Lift the cap when the plugin updates (a Renovate/Dependabot note). |
| Architecture | **import-linter** 2.15 | Turns the layering in §3.2 into a CI failure instead of a review comment. |
| Git hooks | **prek** running a standard `.pre-commit-config.yaml` (works with pre-commit too). Hooks: ruff, ruff-format, mypy (local), import-linter (local), biome (overlay), **conventional-pre-commit** v4.4 at the `commit-msg` stage | Conventional Commits get enforced on every commit, not just remembered. prek is fast and uv-native, and the config stays portable. |
| CI | **GitHub Actions** with `astral-sh/setup-uv@v10`. Jobs: `lint` (ruff, import-linter), `types` (mypy), `test` (matrix of Python 3.12–3.15 × ubuntu/macos, coverage gate), `integration` (tmux installed), `overlay` (Node 24 LTS: biome, tsc, vitest, build), `e2e` (Phase 3+). Dependabot for `uv`, `npm` and `github-actions`. Actions pinned by SHA. | The jobs are fast and separate, so a failure says what broke. |
| Overlay | **TypeScript 7** (strict, `noEmit` checking), **esbuild** 0.28 (IIFE bundle), **Biome** 2.5 (lint and format), **Vitest** 5, **npm** on **Node 24 LTS** | The overlay has a handful of dev deps, so npm is enough and adds no tooling. Biome matches the conventions of the maintainer's other repos. The bundle is built in CI and placed in `src/kingkai/assets/` before `uv build`; it is never committed. |
| Release (v2) | release-please driven by Conventional Commits, publishing to PyPI via Trusted Publishing | Deferred: PyPI polish is a v2 item. |
| License | **MIT** | A dev tool wants maximum adoption with minimal friction. Apache-2.0's patent grant matters little for a personal tool like this, and MIT matches the maintainer's other public repos. |

### 12.1 Code conventions

- Domain types: `@dataclass(frozen=True, slots=True)`. Boundary types: `msgspec.Struct(frozen=True, forbid_unknown_fields=False)`.
- Each module has one responsibility and one public surface (`__all__`). Files are kept to roughly ≤ 200 lines.
- No `Any` outside the boundary schemas. `tool_input` is `Mapping[str, JsonValue]`, a recursive alias.
- Time comes from `Clock`. `datetime.now()` is banned outside the clock adapter (ruff `DTZ` plus a review rule).
- **Textual gotchas, from research:**
  - Never name an attribute `tree` on an App or widget.
  - Build typed widget refs in `__init__` and yield them in `compose`. Subscripted generics can't be passed to `query_one`.
  - Write `BINDINGS: ClassVar[list[BindingType]]`.
  - Textual 8 adds a 50 ms delay on screen switches, so tests pause before taking snapshots.
- Commits follow Conventional Commits (commit-msg hook) with no attribution trailers. Public artifacts (fixtures, screenshots, docs) only use `examples/` or the maintainer's personal projects.

---

## 13. Open questions resolved by spikes

| ID | Question | Resolved by | Default if inconclusive |
|---|---|---|---|
| Q1 | React source method: A (build-time) vs B (runtime) vs A then B | Spike 0a | A, falling back to B |
| Q2 | The path form each method produces | Spike 0a | Normalize `file://` and absolute paths only |
| Q3 | `#L` vs `:` as the separator | **Resolved (0b):** `#L` | — |
| Q4 | `@` autocomplete, typing mid-text, during a turn, in a dialog | **Resolved (0b):** safe at the prompt. Dialogs need bracketed paste and the layers in §8.4. | — |
| Q5 | `()` and `[]` in mentions | **Resolved (0b):** they work | — |
| Q6 | `pane_current_command` | **Resolved (0b):** `claude` (native); `node` still accepted | — |
| Q7 | `agent_id` on subagent tool events; transcript naming | **Resolved (0b):** confirmed; `subagents/agent-<agent_id>.jsonl` | — |
| Q8 | Is usage cumulative across streamed lines? Is subagent usage duplicated? Cache-write tiers? | **Resolved (0b):** cumulative, so last wins; not duplicated; two tiers (5 m and 1 h), priced separately | — |
| Q9 | Django: rewrite in `get_contents` or patch the nodelist; include/extends; debug toolbar | Phase 3 spike | Rewrite in `get_contents` |

---

## 14. Non-goals

These are out of the MVP, though several are fine for v2:

- **Not in the MVP:**
  - Comparing sessions with each other.
  - Historical statistics.
  - Vue and Svelte.
  - The Jinja2 backend.
  - An npm package for the Next integration.
  - A polished PyPI release with a demo GIF.
- **Out of scope, and no plans:**
  - Local AI or any outbound network call.
  - Changing Claude's behaviour: kingkai's hooks never block, approve, or inject context (`UserPromptSubmit` injection was ruled out).
  - Parsing `Bash` commands to infer which files they touched.
  - OpenTelemetry ingestion. It's a candidate future `EventSource`.
  - Native Windows. WSL2, Linux and macOS are supported, and the hook client uses `fcntl`.
  - Remote, multi-user or containerized setups, and any listening address other than 127.0.0.1.
  - Typing anything other than a `Reference`, or sending any key other than literal characters.
  - Production use of the Django or Next integrations: everything is gated on DEBUG or development.

---

## 15. Decisions made while writing this spec (for review)

These are my calls. Each one is reversible, and none needs the maintainer's input unless they disagree.

1. **Topology.** One process, with the daemon/TUI boundary as a port (§1.2, §5.3).
2. **Hook transport.** A spool file, not a socket or an http hook, so the hook can never be noisy or fail (§1.2, §5.1).
3. **Where hooks go.** `.claude/settings.local.json`, not the shared `settings.json`.
4. **Reference format.** A closed `ReferenceFormat` enum, `#L` by default, settled by Spike 0b.
5. **Paths with spaces.** Rejected in the MVP.
6. **Typing during a turn.** Allowed; blocked only during permission prompts (S9, a new rule).
7. **Security additions.** The Host check, the forced preflight, the body limit and the rate limit (S3a–S3c, S11), on top of the plan's rules.
8. **Tailing.** Polling instead of inotify.
9. **Cost.** An estimate from a bundled price table, always labelled API-equivalent; OTel is deferred.
10. **Next integration.** A printed snippet instead of an npm package.
11. **Library choices.** msgspec over pydantic, cyclopts over Typer, aiohttp over starlette/uvicorn, mypy over ty/pyright as the gate.
12. **Demo apps.** `examples/next-demo` and `examples/django-demo` live in the repo, so that demos and fixtures never touch employer code.

These came out of the builder review (2026-10-19):

13. **Event identity.** The hook client writes a UUID into `_kk.id`, and transcript events use `file:offset`. Usage is deduped by `message_id`. There is no `seq` counter.
14. **Pane-to-session binding.** It comes from `$TMUX_PANE`, which the hook client records.
15. **Clearing the dialog flag.** It is agent-scoped, and `idle_prompt` doesn't block typing.
16. **Stall.** It counts hook events only, uses a longer threshold while a tool is in flight, and stays off during replay. All alerts clear when their condition goes away.
17. **Hook shim.** A stable shim that exits 0 when kingkai is gone. `init` uses `git check-ignore` and `.git/info/exclude`.
18. **Shrinking.** The hook client shrinks payloads instead of dropping them. Every string ends up ≤ 512 characters.
19. **Paths and the session file.** Integrations send absolute paths, and Python makes them relative to `session.json.root`. The session file is read on each request and cached by mtime.
20. **`SourceFiles`.** It is a domain-owned port, and the domain re-checks containment.
21. **`Reference` minting.** It is guarded at runtime by a private sentinel and `PLC2701`. Every typer re-checks the grammar.
22. **HTTP status.** 200 rather than 202, and 429 is listed.
23. **Docstrings.** ruff `D` is dropped.

---

## 16. Phases (summary; the plan has the detail)

Each phase ends in something that can be demoed, and has exit criteria. The plan lives at `docs/superpowers/plans/2026-10-19-kingkai-roadmap.md`.

| Phase | Delivers | Demo / exit |
|---|---|---|
| 0 | Spikes 0a (React source location) and 0b (tmux typing and dialogs). The code is throwaway and never merged. Findings go in `docs/spikes/`. | Q1–Q6 answered. Dialog signatures and real hook fixtures recorded. |
| 1 | Toolchain, hook client, `init`/`uninstall`, spool, tailers, reducer, TUI with agents, timeline and files | A real Claude Code task with 2 subagents shows a live tree and files |
| 2 | Detectors, transcript usage and cost, alerts and usage panels, session switcher, `doctor` | A forced failure loop raises RetryLoop. Cost updates live. |
| 3 | HTTP ingress (S1–S11), reference service, tmux and clipboard typers, overlay, `up`, Next.js snippet, e2e | Alt+click in `examples/next-demo` types `@…#L42 ` into the Claude prompt without submitting |
| 4 | Django loader and middleware (after the Q9 mini-spike), e2e | The same as Phase 3, from a Django template |
| 5 | Public polish: README with a GIF recorded on a personal project, docs, a v0.1.0 GitHub release | A fresh clone works end to end following only the README |

### Q-S9: residual risk of typing into a dialog (**decided 2026-10-19: policy (a)**)

Hooks are async and polled, so the domain's dialog flag can be up to a few hundred ms late. The `capture-pane` signature check (§8.4) closes most of that window, but it is a heuristic that depends on Claude Code's UI text. If a dialog is open and missed, the digits in `#L42` could select a menu option. Spike 0b measures whether that can actually happen. The maintainer chose **(a)**. The options were:

- **(a) Default:** layered checks, and kingkai types whenever they all pass. If Spike 0b shows that a dialog *can* be triggered by typed text, kingkai switches to bracketed paste, provided the spike shows a paste can't trigger it.
- **(b) Strict:** kingkai types only when no turn is open (Claude is idle at the prompt). During a turn, references always go to the clipboard.
- **(c) Paranoid:** kingkai always uses the clipboard, unless the user presses a key in the kingkai pane to confirm.
