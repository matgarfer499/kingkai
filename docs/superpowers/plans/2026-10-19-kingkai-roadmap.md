# kingkai MVP Implementation Plan (phased roadmap)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the kingkai MVP. It is a Textual TUI that shows Claude Code's agents, files, tool calls, alerts and cost live. Alt+clicking an element in a local Next.js or Django app types `@path#L<line> ` into the Claude Code prompt and never submits it.

**Architecture:** There is one asyncio process. Layers: a pure `domain` (reducer, detectors, reference grammar), an `application` layer (use cases and ports), `adapters` (hook and transcript anti-corruption layer, tailers, aiohttp, tmux, clipboard) and a thin Textual `ui`. A stdlib-only hook client appends Claude Code hook payloads to a per-session spool file, which kingkai tails.

**Tech Stack:**
- Python ≥ 3.12 with uv/uv_build.
- textual 8.2, aiohttp 3.14, msgspec 0.22, cyclopts 5.2.
- ruff 0.17, mypy 2.4 `--strict`, pytest 8.4.x, hypothesis, import-linter 2.15, prek.
- Overlay: TypeScript 7, esbuild, Biome, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-19-kingkai-design.md`. Section numbers like §4.3 refer to it.

**How this roadmap is detailed:**
- Phase 0 and Phase 1 are written down to the step.
- Phases 2–5 are written down to the task: files, interfaces, named tests and exit criteria. The spikes may change their details.
- At the start of each of Phases 2–5, run superpowers:writing-plans again on that phase's section. That turns it into step-level tasks with the spike findings included.
- **Decision (my call):** this keeps the plan proportional to what is known today.

## Global Constraints

- `requires-python = ">=3.12"`; CI runs Python 3.12, 3.13, 3.14 and 3.15 on ubuntu-latest and macos-latest.
- Pin `pytest>=8.4,<9`, because pytest-textual-snapshot 1.1 pins syrupy 4.8.
- Runtime deps are limited to `textual>=8.2`, `aiohttp>=3.14`, `msgspec>=0.22` and `cyclopts>=5.2`, plus the `django = ["django>=5.2"]` extra. Adding any other runtime dependency needs a spec change.
- `kingkai.hook_client` imports **only the stdlib** (import-linter `hook-client-stdlib-only`).
- `kingkai.domain` imports only the stdlib, and no asyncio (import-linter `domain-pure`).
- Use `datetime.now()` only in the clock adapter. Every timestamp is a timezone-aware UTC value.
- Domain types: `@dataclass(frozen=True, slots=True)`. Boundary types: `msgspec.Struct(frozen=True)` with unknown fields ignored.
- mypy `--strict` must pass, with no `Any` outside `adapters/*/schema.py`.
- Never name a Textual attribute `tree`. Write `BINDINGS: ClassVar[list[BindingType]]`.
- The typed text must match `^@(?:[\w.\-()\[\]@+]+/)*[\w.\-()\[\]@+]+(?:#L|:)[1-9][0-9]* $`.
- tmux delivery is exactly `["tmux","load-buffer","-b",<buf>,"-"]` (text on stdin), then `["tmux","paste-buffer","-p","-d","-b",<buf>,"-t",<pane>]`. kingkai never calls `send-keys` (Spike 0b).
- The HTTP server binds `127.0.0.1` only, on port 0. Bodies are limited to 4096 bytes and requests to 5 per second.
- Hooks are installed only in `.claude/settings.local.json`, with `"async": true, "timeout": 5`. The command is the shim `~/.local/state/kingkai/bin/kingkai-hook`.
- File modes: spool dir 0700, spool and session files 0600.
- Commits follow Conventional Commits, with no `Co-Authored-By` or "Generated with" trailers.
- No employer names, code, URLs or screenshots anywhere. Fixtures and demos come only from `examples/` or the maintainer's personal projects (for example `~/dev/portfolio-web`).

## Review Focus

These are the five input classes or failure modes most likely to bite a user that no task's main tests exercise. Each has a test in the task that owns the code.

1. **Two hook processes append to the same spool at the same moment.** Expect no torn or interleaved lines. → Task 1.4, `test_concurrent_appends_never_tear_lines`.
2. **The project path contains spaces or non-ASCII characters (`~/dev/mi proyecto`).** Expect the project key, the spool and the session file to work, and references inside it to render relative paths. → Task 1.4, `test_project_key_with_spaces_and_unicode`; Task 3.3, `test_root_with_spaces_renders_relative_path`.
3. **The existing `settings.local.json` is invalid JSON or already has user hooks.** Expect the installer to never destroy user data. It aborts on invalid JSON and merges otherwise. → Task 1.5, `test_invalid_json_aborts_without_writing`, `test_preserves_user_hooks_on_same_event`.
4. **A large transcript (50 MB) exists when `watch` starts.** Expect the TUI to stay responsive during replay: the tailer reads in bounded chunks and yields to the loop. → Task 1.6, `test_reads_in_bounded_chunks_and_yields`; Task 2.2, `test_replay_large_transcript_does_not_block_loop`.
5. **Claude Code runs outside `kingkai up` (no tmux, no `--pane`).** Expect `watch` to work fully and references to go to the clipboard, with the TUI saying so. → Task 3.6, `test_no_pane_uses_clipboard_and_reports_it`.

---

## Phase 0: Spikes (throwaway)

**Rules:**
- Spike code lives under `/tmp`-style scratch dirs or on `spike/*` branches that are **never merged**.
- What gets committed to `main` is only `docs/spikes/0a-react-source.md`, `docs/spikes/0b-tmux-typing.md`, and any fixtures recorded for later phases.
- Each spike is time-boxed to one session.

### Task 0a: React 19 source location (answers Q1, Q2)

**Files:**
- Create: `docs/spikes/0a-react-source.md`
- Scratch, not committed: `spike-0a/` holding a throwaway Next.js 16.4 app, or a branch of `~/dev/portfolio-web` that is never pushed.

- [x] **Step 1: Create a scratch Next.js app** (`npx create-next-app@latest spike-0a --ts --app`) and check that `next` is 16.4.x and `react` is 19.3.x. Add 4 cases:
  - (a) a client component `src/components/Counter.tsx` with `'use client'`;
  - (b) a server component `src/app/page.tsx`;
  - (c) a list `items.map(i => <Item key=…/>)`;
  - (d) `src/components/ui/Button.tsx`, imported from (a) and (b).
- [x] **Step 2: Method A.** Add `code-inspector-plugin@2.0.9` via `turbopack: { rules: codeInspectorPlugin({ bundler: 'turbopack' }) }`. In DevTools, record the `data-insp-path` values for cases a–d. Write down each value's exact format (absolute or relative, and the `file:line:col:tag` order). Check that they survive HMR: edit the file, insert 3 lines above, and confirm the line shifts.
- [x] **Step 3: Method B.** Paste a 30-line test script into the console. It walks DOM → `__reactFiber$*` → `_debugStack`, and symbolicates with `bippy@0.7.3` (via an esm.sh import). Record the resolved `file:line` for cases a–d, and the URL scheme of the raw frames (`webpack-internal://`, `rsc://`, `file://`).
- [x] **Step 4: Write `docs/spikes/0a-react-source.md`** containing:
  - a results table (case × method → correct?/value);
  - the setup lines each method needs;
  - the decision for Q1;
  - the exact path prefixes for Q2, which feed the normalizer list in spec §8.1.
- [x] **Step 5: Update spec §8.2 and §13** with the decision.
- [x] **Step 6: Commit**

```bash
git add docs/spikes/0a-react-source.md docs/superpowers/specs/2026-10-19-kingkai-design.md
git commit -m "docs(spikes): record react 19 source-location findings"
```

**Exit criteria:**
- Q1 and Q2 are answered, with evidence for all 4 cases.
- The spec is updated.
- No spike code is on `main`.

### Task 0b: tmux typing into Claude Code (answers Q3–Q6, Q-S9 evidence, records fixtures)

**Files:**
- Create: `docs/spikes/0b-tmux-typing.md`
- Create: `tests/fixtures/screens/*.txt` (captured `capture-pane -p` screens: idle prompt, working, permission dialog, `/` menu, `@` autocomplete)
- Create: `tests/fixtures/hooks/*.json` (real payloads recorded with a 5-line logging hook during the same run, then scrubbed by hand: replace `/home/<user>` with `/home/user` and session ids with `00000000-…`)
- Scratch, not committed: the logging hook script, and a scratch project with a 300-line file, an `app/(group)/[slug]/page.tsx` path and a nested directory.

- [x] **Step 1: Set up the scratch project.** In tmux, run `claude` in pane %A. Install a temporary logging command hook for every event in §4.1 into the scratch project's `.claude/settings.local.json`. The hook appends stdin to `/tmp/kk-spike-hooks.ndjson`.
- [x] **Step 2: Test the separator (Q3).** Run `tmux send-keys -t %A -l -- '@src/big.ts#L120 '` and observe the prompt. Then type "what is on that line?" by hand and press Enter. Record whether the mention resolved (it shows as a file chip, or the file is attached) and whether the model answered about line 120. Repeat with `@src/big.ts:120 `.
- [x] **Step 3: Test autocomplete and the cursor (Q4).**
  - Type with the `@` menu open: does the trailing space close it, and is the text altered?
  - With text already typed and the cursor in the middle, is the reference inserted at the cursor?
  - Type while Claude is working: is the text queued?
- [x] **Step 4: Test dialogs (Q-S9).** Trigger a permission prompt (ask Claude to run `touch x` in default mode). While it is open:
  - capture the screen into `tests/fixtures/screens/permission_prompt.txt`;
  - send `@src/big.ts#L12 ` with `send-keys -l` and record what happens (did an option get selected?);
  - repeat with `tmux load-buffer` plus `paste-buffer -p -t %A`.

  Also capture the `/` menu screen and the idle prompt screen. Write down 1–3 **stable substrings** that identify each dialog.
- [x] **Step 5: Test paths and process names (Q5, Q6).** Type `@app/(group)/[slug]/page.tsx#L3 ` and record whether it resolves. Record `#{pane_current_command}` for the installed claude.
- [x] **Step 6: Collect fixtures.** Run a task that launches 2 subagents in parallel and makes one tool fail 3 times. Copy the hook log, split it into one file per event type (`session_start.json`, `pre_tool_use_main.json`, `pre_tool_use_subagent.json`, `post_tool_use_failure.json`, `subagent_start.json`, `subagent_stop.json`, `notification_permission.json`, `stop.json`, `session_end.json`), scrub it, and save it under `tests/fixtures/hooks/`. Also copy about 30 transcript lines that include assistant `usage` (main and subagent) to `tests/fixtures/transcripts/` (scrubbed). Record the Claude Code version (`claude --version`) in `tests/fixtures/README.md`.
- [x] **Step 7: Write `docs/spikes/0b-tmux-typing.md`.** It answers Q3–Q8 (Q7 is `agent_id` on subagent events, Q8 is usage repetition) and gives a recommendation for Q-S9 with evidence. Update spec §8.4, §13 and the default `ReferenceFormat`.
- [x] **Step 8: Grep for anything that shouldn't be public.**

```bash
grep -rniEf ~/.config/kingkai-dev/private-terms.txt docs tests   # patterns live outside the repo
```

Expected: no output.
- [x] **Step 9: Commit**

```bash
git add docs/spikes/0b-tmux-typing.md tests/fixtures docs/superpowers/specs/2026-10-19-kingkai-design.md
git commit -m "docs(spikes): record tmux typing findings and claude code fixtures"
```

**Exit criteria:**
- Q3–Q8 are answered.
- The Q-S9 evidence is written down, including whether `send-keys -l` or bracketed paste is the primitive under policy (a).
- At least 9 hook fixtures and 1 transcript fixture are committed.
- The grep check is clean.

---

## Phase 1: Walking skeleton, the live view

**Demo:** in `examples/next-demo` (created in Task 1.1 as a bare `create-next-app`), run `kingkai init`, open `claude` in one terminal and `kingkai watch` in another, and ask Claude for a task that launches 2 subagents. The TUI shows the agent tree, a timeline of tool calls and the touched files, all live.

**Exit criteria:**
- The demo above works.
- `uv run pytest` passes, and so do `uv run mypy`, `uv run ruff check`, `uv run ruff format --check` and `uv run lint-imports`.
- CI is green on the matrix.
- Coverage is ≥ 90 % for `domain`/`application` and ≥ 80 % overall.

### Task 1.1: Project scaffold and toolchain

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `src/kingkai/__init__.py` (holding `__version__ = "0.0.0"` only), `src/kingkai/py.typed`, `tests/test_smoke.py`
- Create: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.importlinter`, `CONTRIBUTING.md`
- Create: `examples/next-demo/` (`npx create-next-app@latest --ts --app --no-eslint`, with `node_modules` gitignored)

**Interfaces:**
- Produces:
  - console scripts `kingkai = "kingkai.cli:main"` and `kingkai-hook = "kingkai.hook_client.__main__:main"`;
  - the dependency groups `dev` and `test`.

- [ ] **Step 1: Write `tests/test_smoke.py`**

```python
import kingkai

def test_version_is_string() -> None:
    assert isinstance(kingkai.__version__, str)
```

- [ ] **Step 2: Write `pyproject.toml`.**
  - The build backend is `uv_build>=0.13.1,<0.14` and the runtime deps are the ones in Global Constraints.
  - `[dependency-groups] dev` holds `ruff==0.17.*`, `mypy==2.4.*`, `import-linter==2.15.*`, `pytest>=8.4,<9`, `pytest-asyncio>=1.4`, `pytest-textual-snapshot>=1.1`, `pytest-cov>=7.1`, `hypothesis>=6.170` and `textual-dev>=1.8`.
  - `[tool.pytest.ini_options]` sets `asyncio_mode = "auto"`, `addopts = "-ra --strict-markers"` and `markers = ["integration: needs tmux"]`.
  - `[tool.mypy]` sets `strict = true`, `files = ["src", "tests"]`.
  - `[tool.ruff]` follows spec §12 (`target-version = "py312"`, `line-length = 100`, the extend-select list, and the test per-file ignores `S101, ANN, PLR2004, FBT`).
  - `[tool.coverage]` uses `branch = true`.
- [ ] **Step 3: Write the `.importlinter` contracts.**
  - `layers`: `kingkai.ui | kingkai.adapters` → `kingkai.application` → `kingkai.domain`.
  - `domain-pure`: forbidden `asyncio, msgspec, textual, aiohttp`, with `include_external_packages = True`.
  - `hook-client-stdlib-only`: forbidden `kingkai.domain, kingkai.application, kingkai.adapters, kingkai.ui, textual, aiohttp, msgspec, cyclopts`.
- [ ] **Step 4: Write `.pre-commit-config.yaml`.** It uses `astral-sh/ruff-pre-commit` v0.17.1 (ruff-check `--fix`, ruff-format), local hooks for `uv run mypy` and `uv run lint-imports`, and `compilerla/conventional-pre-commit` v4.4.0 at the `commit-msg` stage. Run `prek install --hook-type pre-commit --hook-type commit-msg`.
- [ ] **Step 5: Write `ci.yml`.**
  - Jobs: `lint` (ruff check, ruff format --check, lint-imports), `types` (mypy), `test` (matrix of py3.12–3.15 × ubuntu/macos: `uv run --frozen pytest --cov=kingkai --cov-report=term-missing -m "not integration"`), `integration` (ubuntu: `sudo apt-get install -y tmux`, then `pytest -m integration`).
  - Use `astral-sh/setup-uv@v10` with `enable-cache: true` and `python-version: ${{ matrix.python }}`.
  - Pin third-party actions by SHA, with a `# vX.Y.Z` comment.
- [ ] **Step 6: Write `dependabot.yml`.** Ecosystems: `uv`, `github-actions` and `npm` (`/overlay`, added later). Weekly schedule, with commit-message prefix `build(deps)`.
- [ ] **Step 7: Run everything.** Run `uv sync && uv run pytest && uv run mypy && uv run ruff check && uv run ruff format --check && uv run lint-imports`. Expected: all pass (lint-imports may warn that packages are empty; create empty `__init__.py` files for `domain`, `application`, `adapters`, `ui` and `hook_client` so the contracts resolve).
- [ ] **Step 8: Commit, push and check CI**

```bash
git add -A
git commit -m "build: scaffold uv project with ruff, mypy, pytest, import-linter and ci"
git push
gh run watch   # or: check the Actions tab (gh may be unauthenticated; then use the GitHub MCP)
```

Expected: all CI jobs are green.

### Task 1.2: Domain ids, events, state and reducer (tool-call correlation)

**Files:**
- Create: `src/kingkai/domain/ids.py`, `events.py`, `state.py`, `reducer.py`
- Test: `tests/domain/test_reducer.py`, `tests/domain/test_reducer_properties.py`, `tests/domain/factories.py` (event builders for tests)

**Interfaces:**
- Produces:
  - `SessionId`, `AgentId`, `ToolUseId`, `EventId`: `NewType(str)`.
  - `AgentRef = MainAgent | SubAgent`, where `MainAgent` is a singleton dataclass and `SubAgent(agent_id: AgentId)`.
  - The `DomainEvent` union: every event in spec §4.2 except `UsageRecorded`, `Tick` and `ReplayCompleted`, which Phase 2 adds. Each has the base fields `session_id: SessionId`, `event_id: EventId`, `at: datetime`.
  - `ToolCall(tool_use_id, agent, tool, input_fingerprint, touches, status: Literal["running","succeeded","failed","abandoned"], started_at: datetime | None, ended_at: datetime | None, duration_ms: int | None, error_summary: str | None)`.
  - `AgentNode(ref, agent_type, status: Literal["running","done"], started_at)`.
  - `SessionState(session_id, agents: Mapping[AgentRef, AgentNode], calls: Mapping[ToolUseId, ToolCall], call_order: tuple[ToolUseId, ...], touches: tuple[FileTouch, ...], turn_open: bool, awaiting_permission: frozenset[AgentRef], liveness: Literal["live","idle","ended"], last_activity: datetime | None, seen: frozenset[EventId], tmux_pane: str | None, transcript_path: str | None)`.
  - `SessionState.initial(session_id) -> SessionState`.
  - `reduce(state: SessionState, event: DomainEvent) -> SessionState`.

- [ ] **Step 1: Write failing tests** in `tests/domain/test_reducer.py`:
  - `test_started_then_succeeded_marks_call_succeeded`: the call has status `"succeeded"`, `duration_ms == 12`, and `call_order == ("t1",)`.
  - `test_succeeded_before_started_converges`: applying `[Succeeded(t1), Started(t1)]` gives the same `calls["t1"]` as `[Started(t1), Succeeded(t1)]`.
  - `test_duplicate_event_id_is_noop`: `reduce(reduce(s, e), e) == reduce(s, e)`.
  - `test_unknown_subagent_created_implicitly`: a `ToolCallStarted` with `SubAgent("a1")` and no `SubagentStarted` gives `agents[SubAgent("a1")].agent_type == "unknown"`.
  - `test_subagent_start_stop_lifecycle`.
  - `test_permission_request_sets_flag_for_that_agent_only`.
  - `test_subagent_activity_does_not_clear_main_dialog_flag` (S9).
  - `test_late_notification_after_tool_start_still_blocks` (S9): a `Notification` with `at` earlier than an already-applied `Started` from the same agent still adds the flag, because flags clear only on events *applied after* them.
  - `test_notification_never_blocks` (S9).
  - `test_permission_prompt_clears_on_next_tool_event` (S9).
  - `test_turn_stopped_clears_all_dialog_flags`.
  - `test_session_ended_sets_liveness_ended`.
  - `test_running_calls_abandoned_on_next_turn_started` (Spike 0b: a cancelled dialog emits no end event).
  - `test_running_calls_abandoned_on_session_end`.
  - `test_system_turn_kind_from_task_notification_prompt`.
  - `test_untyped_subagent_stop_for_unseen_agent_ignored` (auxiliary agents).
- [ ] **Step 2: Run** `uv run pytest tests/domain/test_reducer.py -v`. Expected: FAIL, because `kingkai.domain.reducer` doesn't exist yet.
- [ ] **Step 3: Implement** `ids.py`, `events.py` and `state.py`, then `reduce`.
  - `reduce` dispatches with a `match` on the event type to one private `_apply_<event>` function per event.
  - Dangling ends are stored as a `ToolCall` with `started_at=None`, and a later `Started` fills in the start fields.
  - `seen` is capped at 10 000 ids: drop the oldest, tracked in a parallel tuple.
- [ ] **Step 4: Write the property tests** in `test_reducer_properties.py`:
  - `test_tool_call_state_independent_of_interleaving`: hypothesis generates 1–6 tool calls, each with a Started and an end event, and a random interleaving that keeps them all. It asserts `state.calls` and the set of `state.touches` are equal across interleavings.
  - `test_reduce_idempotent`: applying any generated event list twice gives the same state as applying it once.
- [ ] **Step 5: Run** `uv run pytest tests/domain -v`. Expected: PASS.
- [ ] **Step 6: Commit** with `feat(domain): add session state reducer with tool-call correlation`.

### Task 1.3: File touches from tool input

**Files:**
- Create: `src/kingkai/domain/tools.py`
- Test: `tests/domain/test_tools.py`

**Interfaces:**
- Produces:
  - `FileTouch(path: str, kind: Literal["read","write","search"])`.
  - `touches_for(tool: str, tool_input: Mapping[str, JsonValue]) -> tuple[FileTouch, ...]`.
  - `JsonValue`, a recursive type alias defined in `domain/json.py`.
  - `fingerprint(tool_input: Mapping[str, JsonValue]) -> str`: the sha256 hex of `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

- [ ] **Step 1: Write failing tests.** Parametrize over:
  - `("Read", {"file_path": "/p/a.ts"}) → (FileTouch("/p/a.ts","read"),)`
  - `Edit` / `MultiEdit` / `Write` → write
  - `("NotebookEdit", {"notebook_path": …})` → write
  - `("Grep", {"pattern": "x", "path": "/p/src"})` → search on `/p/src`
  - `("Glob", {"pattern": "**/*.ts"})` → `()`
  - `("Bash", {"command": "cat a"})` → `()`
  - `("Read", {"file_path": {"$sha256": "…", "$len": 900}})` → `()`, because a non-string path is ignored

  Also add `test_fingerprint_key_order_insensitive` and `test_fingerprint_differs_on_value_change`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** `touches_for` as a dict from tool name to `(field, kind)`. Tools not in the dict return `()`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat(domain): extract file touches and input fingerprints from tool calls`.

### Task 1.4: Hook client (shrink, spool append)

**Files:**
- Create: `src/kingkai/hook_client/__init__.py`, `__main__.py`, `shrink.py`, `spool.py`
- Test: `tests/hook_client/test_shrink.py`, `test_main.py`, `test_spool.py`

**Interfaces:**
- Produces:
  - `shrink(payload: dict[str, object]) -> dict[str, object]`. It cuts `prompt` to 80 characters, and `error`, `message` and `last_assistant_message` to 200. Every other string longer than 512 becomes `{"$sha256": hex, "$len": n}`. It recurses into dicts and lists.
  - `project_key(root: str) -> str`: the first 16 hex characters of `sha256(os.path.realpath(root))`.
  - `spool_path(state_dir: Path, root: str, session_id: str) -> Path | None`: `None` unless `session_id` matches `^[A-Za-z0-9-]{1,64}$`.
  - `append_line(path: Path, line: bytes) -> None`: the directory is created with mode 0700 and the file is opened with `O_APPEND|O_CREAT`, mode 0600. The write happens under `fcntl.flock(LOCK_EX)`.
  - `main(stdin: BinaryIO = sys.stdin.buffer, env: Mapping[str,str] = os.environ, now: Callable[[], datetime] = …) -> int`. It always returns 0. `state_dir` comes from `$XDG_STATE_HOME/kingkai`, or else `~/.local/state/kingkai`, then `spool/`. The root comes from `CLAUDE_PROJECT_DIR`, or else the payload's `cwd`. It adds `_kk = {"v":1,"id":uuid4().hex,"at":iso,"pane":env.get("TMUX_PANE")}`.

- [ ] **Step 1: Write failing tests.**
  - `test_shrink.py`:
    - `test_long_string_becomes_digest`: a 600-character `tool_response.content` turns into a `$sha256` dict with `$len == 600`.
    - `test_prompt_cut_to_80`, `test_error_cut_to_200`, `test_nested_lists_shrunk`.
    - `test_all_strings_bounded`†: for hypothesis JSON trees, every string in `shrink(x)` is ≤ 512.
    - `test_equal_inputs_equal_output`†.
  - `test_spool.py`:
    - `test_bad_session_id_dropped` (S10): `"../x"`, `""`, a 65-character id and `"a/b"` all give `None`.
    - `test_spool_modes` (S10): the directory is `0o700` and the file is `0o600`.
    - `test_concurrent_appends_never_tear_lines` (Review Focus 1): 8 `multiprocessing` workers each append 200 lines of 3 000 bytes. The file then holds exactly 1 600 lines, and each one parses as JSON.
    - `test_project_key_with_spaces_and_unicode` (Review Focus 2): a root `tmp_path / "mi proyecto ñ"` gives a 16-hex key, and appending works.
  - `test_main.py`:
    - `test_exit_zero_on_garbage` (S10): with stdin `b"not json"`, it returns 0 and writes nothing.
    - `test_no_output_ever` (S10): with valid and invalid stdin, `capsys` sees empty stdout and stderr.
    - `test_writes_kk_envelope`: the line has `_kk.v == 1`, a 32-hex `_kk.id`, and `_kk.pane` equal to the `TMUX_PANE` env value.
    - `test_unwritable_state_dir_still_exit_zero`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement** the four modules. `main` wraps everything in `try/except BaseException` except `KeyboardInterrupt`, with the comment `# noqa: BLE001  S10: must never fail`.
- [ ] **Step 4: Run** `uv run pytest tests/hook_client -v && uv run lint-imports`. Expected: PASS, and `hook-client-stdlib-only` is KEPT.
- [ ] **Step 5: Time it.** Run `python -X importtime -m kingkai.hook_client < tests/fixtures/hooks/pre_tool_use_main.json 2>&1 | tail -1`. Expected: the cumulative import time is < 50 ms. Write the figure in the commit body.
- [ ] **Step 6: Commit** with `feat(hook-client): append shrunk hook payloads to per-session spool`.

### Task 1.5: Settings installer, shim, `init` and `uninstall`

**Files:**
- Create: `src/kingkai/adapters/settings_installer.py`, `src/kingkai/adapters/project.py`, `src/kingkai/cli.py`
- Test: `tests/adapters/test_settings_installer.py`, `tests/adapters/test_project.py`, `tests/test_cli.py`, `tests/adapters/golden/*.json`

**Interfaces:**
- Produces:
  - `HOOK_EVENTS: tuple[str, ...]`: the 12 events in spec §4.1, which are SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, SubagentStart, SubagentStop, PermissionRequest, Notification, Stop, PreCompact and SessionEnd.
  - `install(settings: Mapping[str, JsonValue], shim: str) -> dict[str, JsonValue]` and `uninstall(settings, shim) -> dict[str, JsonValue]`. Both are pure.
  - `write_shim(path: Path, python: str) -> None`: the file is mode 0755, its content is exactly the one-liner in spec §4.1, and it starts with `#!/bin/sh`.
  - `find_project_root(start: Path) -> Path | None`: walks up to the nearest directory that contains `.claude/` or `.git/`.
  - `ensure_locally_ignored(root: Path, rel: str, run: Runner) -> Literal["ignored","added","not-git"]`: uses `git check-ignore -q`, then appends to `.git/info/exclude`.
  - cyclopts `app` with the commands `init(*, yes: bool = False, next: bool = False, django: bool = False, root: Path | None = None)` and `uninstall(...)`.
  - `main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Write failing tests.**
  - `test_install_adds_all_events_async` (it matches the golden file `golden/installed.json`).
  - `test_install_idempotent`: `install(install(s)) == install(s)`.
  - `test_preserves_user_hooks_on_same_event` (Review Focus 3).
  - `test_preserves_unrelated_keys`.
  - `test_uninstall_removes_only_ours`.
  - `test_invalid_json_aborts_without_writing` (Review Focus 3; this test runs through `cli.init`, which exits 2 and leaves the file bytes unchanged).
  - `test_shim_exits_zero_when_python_missing`: it runs the shim with a nonexistent `PY` via `subprocess` and checks the return code is 0 and the output is empty.
  - `test_find_project_root_walks_up`.
  - `test_init_creates_kingkai_dir_with_star_gitignore`.
  - `test_init_shows_diff_and_requires_yes_noninteractive`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** The CLI reads and writes JSON with `json` and an `indent=2` round-trip. The diff preview uses `difflib.unified_diff`. `Runner` is a `Protocol` with `__call__(argv: Sequence[str]) -> CompletedProcess[str]`, so the git calls can be faked in tests.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Try it by hand.** In `examples/next-demo`, run `uv run kingkai init --yes`, then `cat .claude/settings.local.json` and `git check-ignore .claude/settings.local.json`. Expected: the hooks are present and the file is ignored.
- [ ] **Step 6: Commit** with `feat(cli): install and remove hooks in settings.local.json via a stable shim`.

### Task 1.6: NDJSON tailer

**Files:**
- Create: `src/kingkai/adapters/tail.py`, `src/kingkai/application/ports.py` (`Clock`, `Sleeper`)
- Test: `tests/adapters/test_tail.py`

**Interfaces:**
- Produces:
  - `class NdjsonTailer` with `__init__(self, path: Path, *, poll_interval: float, sleep: Sleeper, chunk_size: int = 65536)`.
  - `async def lines(self) -> AsyncIterator[TailedLine]`, where `TailedLine(path: Path, offset: int, data: bytes)` and `offset` is where the line starts.
  - `def at_eof(self) -> bool`.
  - `Sleeper = Callable[[float], Awaitable[None]]`.

- [ ] **Step 1: Write failing tests.** They use a `FakeSleeper` that records calls and lets the test append data between polls.
  - `test_yields_complete_lines_only`: write `b'{"a":1}\n{"b"'`, and only the first line comes out. Append `b':2}\n'`, and the second comes out with offset 8.
  - `test_truncation_restarts_from_zero`.
  - `test_inode_change_restarts_from_zero`: rename and recreate the file.
  - `test_missing_file_waits`.
  - `test_reads_in_bounded_chunks_and_yields` (Review Focus 4): with a 5 MB file and `chunk_size = 65536`, `sleep(0)` is awaited at least `5 MB / 64 KiB` times during the first drain.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use plain `open`/`seek`/`read` on a binary handle, and track `(st_ino, offset)`. After each chunk, call `await sleep(0)`. When a read returns nothing, call `await sleep(poll_interval)`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat(adapters): add offset-tracking ndjson tailer`.

### Task 1.7: Hook schema and translation (anti-corruption layer)

**Files:**
- Create: `src/kingkai/adapters/hooks/schema.py`, `translate.py`
- Test: `tests/adapters/hooks/test_translate.py` (driven by the `tests/fixtures/hooks/*.json` files from Phase 0)

**Interfaces:**
- Consumes: the domain events from Task 1.2, and `touches_for` and `fingerprint` from Task 1.3.
- Produces:
  - one `msgspec.Struct` per payload kind, with tag field `hook_event_name`;
  - `decode_line(data: bytes) -> HookPayload | None`, which returns `None` on any `msgspec.DecodeError` or `ValidationError`;
  - `to_domain(p: HookPayload) -> DomainEvent | None`, which returns `None` for event types kingkai ignores. `agent_id` present gives `SubAgent(agent_id)`; absent gives `MainAgent`. `event_id` comes from `_kk.id` and `at` from `_kk.at`.

- [ ] **Step 1: Write failing tests.**
  - `test_full_run_replays_to_expected_tree`: decoding and reducing `hooks/session_full_run.ndjson` gives 2 visible subagents (both `general-purpose`), 3 failed `Bash` calls, and no auxiliary agents.
  - One test per fixture file, asserting the exact domain event. For example, `test_pre_tool_use_subagent_fixture` asserts that `agent == SubAgent(<id in fixture>)` and that `touches` has the read path.
  - `test_unknown_event_returns_none`.
  - `test_unknown_fields_ignored` (add `"brand_new_field": 1`).
  - `test_missing_required_field_returns_none`.
  - `test_garbage_bytes_return_none`.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** Use `msgspec.json.Decoder(HookPayload)` with a tagged union. `tool_input` is typed as `dict[str, Any]` here, which is the one place `Any` is allowed, and is converted to `JsonValue`.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat(adapters): translate claude code hook payloads into domain events`.

### Task 1.8: Store, SessionService and spool discovery

**Files:**
- Create: `src/kingkai/application/store.py`, `session_service.py`, `src/kingkai/adapters/spool_source.py`, `src/kingkai/adapters/clock.py`
- Test: `tests/application/test_store.py`, `test_session_service.py`, `tests/adapters/test_spool_source.py`

**Interfaces:**
- Consumes: `NdjsonTailer` (Task 1.6), `decode_line` and `to_domain` (Task 1.7), `reduce` (Task 1.2).
- Produces:
  - `Store` with `get(session_id) -> SessionState | None`, `sessions() -> tuple[SessionState, ...]`, `put(state) -> None` and `subscribe(cb: Callable[[SessionState], None]) -> Callable[[], None]`. The returned function unsubscribes.
  - `SessionService(store: Store, sources: Sequence[EventSource])` with `async run() -> None` and `apply(event: DomainEvent) -> None`. `apply` is sync and is the method tests call.
  - `EventSource` Protocol: `def events(self) -> AsyncIterator[DomainEvent]`.
  - `SpoolDirectory(dir: Path, *, scan_interval: float, sleep: Sleeper, tailer_factory: Callable[[Path], NdjsonTailer])`, which implements `EventSource`. It starts one tailer task per file modified in the last 24 h, and merges their output through an `asyncio.Queue`.
  - `SystemClock` implements `Clock`.

- [ ] **Step 1: Write failing tests.**
  - `test_apply_routes_by_session_and_notifies_subscribers`.
  - `test_unsubscribe_stops_notifications`.
  - `test_run_drains_all_sources`, using two fake `EventSource`s backed by lists.
  - `test_discovers_new_spool_file_after_start`.
  - `test_ignores_files_older_than_24h` (set the mtime with `os.utime`).
  - `test_skipped_lines_counted_in_diagnostics`: `Store.diagnostics.skipped_lines == 1` after a garbage line.
- [ ] **Step 2: Run them.** Expected: FAIL.
- [ ] **Step 3: Implement.** `Store.diagnostics` is a small mutable `Diagnostics` dataclass, the one deliberate piece of mutable application state. Spec §10 says it is shown in the footer.
- [ ] **Step 4: Run them.** Expected: PASS.
- [ ] **Step 5: Commit** with `feat(application): add store and session service fed by spool discovery`.

### Task 1.9: Presenters, Textual app, bootstrap and `watch`

**Files:**
- Create: `src/kingkai/ui/presenters.py`, `ui/messages.py`, `ui/app.py`, `ui/widgets/agent_tree.py`, `ui/widgets/timeline.py`, `ui/widgets/files.py`, `ui/app.tcss`, `src/kingkai/bootstrap.py`
- Modify: `src/kingkai/cli.py`, to add `watch(*, root: Path | None = None, pane: str | None = None)`
- Test: `tests/ui/test_presenters.py`, `tests/ui/test_app.py`, `tests/ui/test_snapshots.py`, `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `Store`, `SessionService` and `SessionState`.
- Produces:
  - `AgentTreeVM(nodes: tuple[AgentRowVM, ...])`, `TimelineVM(rows: tuple[TimelineRowVM, ...])` and `FilesVM(rows: tuple[FileRowVM, ...])`.
  - `present(state: SessionState, now: datetime, *, root: Path) -> ScreenVM`. Paths are shown relative to `root` when they are inside it.
  - `SnapshotUpdated(Message)` carries `vm: ScreenVM`.
  - `KingkaiApp(App[None])` with `__init__(self, store: Store, service: SessionService, clock: Clock, root: Path)`.
  - `build_app(config: Config) -> KingkaiApp`. In Phase 1, `Config` is a minimal frozen dataclass `Config(root: Path, state_dir: Path, pane: str | None)` defined in `adapters/config.py`.

- [ ] **Step 1: Write failing presenter tests.**
  - `test_tree_nests_subagents_under_main`.
  - `test_timeline_newest_last_with_duration_and_status_icon`.
  - `test_files_aggregates_counts_and_write_wins_over_read`.
  - `test_paths_relative_to_root`.
- [ ] **Step 2: Run them.** Expected: FAIL. **Step 3:** implement `presenters.py`. **Step 4:** Expected: PASS.
- [ ] **Step 5: Write failing app tests.**
  - `test_snapshot_updates_reach_widgets`: in `run_test(size=(120,40))`, apply 3 events through the service, call `await pilot.pause()`, and assert that the timeline `DataTable` has `row_count == 3`.
  - `test_updates_coalesced_to_10hz`: apply 50 events in one loop tick and assert that ≤ 2 `SnapshotUpdated` messages are posted (use `message_hook`).
  - `test_quit_binding`.
  - Snapshots: `test_snapshot_empty`, `test_snapshot_two_subagents` at 120×40 and 80×24.
- [ ] **Step 6: Implement.**
  - Widgets are built as typed attributes in `__init__` and yielded in `compose`.
  - The service runs as `@work(exclusive=True, group="service")`.
  - The store subscription calls a coalescer that, at most every 100 ms, posts the `SnapshotUpdated` of the selected session. It uses `self.set_timer` for the trailing edge.
  - Generate the snapshots with `uv run pytest tests/ui --snapshot-update`, then inspect the SVGs by eye before committing.
- [ ] **Step 7: Run** `uv run pytest tests/ui -v`. Expected: PASS.
- [ ] **Step 8: Add `test_bootstrap.py::test_build_app_wires_spool_dir_for_project_key`.** Implement `bootstrap.build_app` and `cli.watch`.
- [ ] **Step 9: Commit** with `feat(ui): show live agent tree, timeline and files in the textual app`.

### Task 1.10: Phase 1 demo check

- [ ] **Step 1: Run the demo.** In `examples/next-demo`: `uv run kingkai init --yes`, then `claude` in terminal A and `uv run kingkai watch` in terminal B. Prompt: "Use two subagents in parallel: one lists the files in src/app, the other reads package.json. Then summarize."
- [ ] **Step 2: Check the result.** Expected: the tree shows main plus 2 subagents, the timeline shows Read/Glob/LS calls attributed to the right agent, and the files panel shows `package.json` (R).
- [ ] **Step 3: Restart the TUI.** Quit `watch` and start it again. Expected: the same state is rebuilt from the spool (replay).
- [ ] **Step 4: Fix anything the demo surfaced** with a failing test first, then the fix. Commit each fix as `fix(<scope>): …`.
- [ ] **Step 5: Record a screenshot.** Run `textual run --screenshot` or take an SVG via `app.save_screenshot()` from the demo app only, and save it to `docs/img/phase1.svg`. Commit with `docs: add phase 1 screenshot`.

---

## Phase 2: Alerts, usage and cost, sessions, doctor

**Demo:**
- (1) Ask Claude to "run `false` until it succeeds, max 4 tries". Within a second of the third failure, the alerts panel shows RetryLoop and RepeatedCall.
- (2) The usage panel shows tokens and `≈ $` rising while Claude works.
- (3) Two Claude sessions in the same project can be told apart with `s`.

**Exit criteria:**
- The demo works.
- Plan verification item "Bucle" passes.
- Q7 and Q8 are confirmed against fixtures.
- The coverage gates hold.

Expand this section with writing-plans at the start of the phase.

### Task 2.1: Detectors (Strategy)
**Files:** `src/kingkai/domain/alerts/{base,repeated_call,tool_failure,retry_loop,stall}.py`, `domain/state.py` (add `alerts: Mapping[str, Alert]`), `tests/domain/alerts/test_*.py`
**Interfaces:**
- `Alert(key: str, kind: AlertKind, severity: Literal["info","warning","error"], agent: AgentRef | None, message: str, first_at: datetime, last_at: datetime, count: int)`
- `AlertChanges(raise_: tuple[Alert, ...], clear: tuple[str, ...])`
- `Detector` Protocol `__call__(self, before: SessionState, event: DomainEvent, now: datetime) -> AlertChanges`
- `apply_alerts(state, changes) -> SessionState`
- Add the events `Tick(session_id, now)` and `ReplayCompleted()`, and the state field `replay_done: bool`.

**Key tests:**
- `test_repeated_call_fires_at_threshold_3_in_window_10`, `test_repeated_call_clears_when_window_slides`
- `test_retry_loop_fires_after_3_consecutive_failures_same_tool`, `test_retry_loop_clears_on_success`
- `test_interrupt_failure_not_alerted`
- `test_stall_fires_after_120s_without_hook_activity`, `test_stall_uses_600s_while_tool_in_flight`, `test_stall_suppressed_while_awaiting_permission`, `test_stall_disabled_before_replay_completed`, `test_tick_and_usage_do_not_count_as_activity`
- `test_alert_key_dedupes_and_increments_count`

The thresholds are constructor arguments; the `Config` defaults are in spec §4.4.

### Task 2.2: Transcript usage source
**Files:** `adapters/transcript/{schema,translate}.py`, `adapters/transcript_source.py`, `domain/usage.py`, `tests/adapters/transcript/*`, `tests/domain/test_usage.py`
**Interfaces:**
- `TokenUsage(input: int, output: int, cache_write: int, cache_read: int)` with `__add__`
- `UsageRecorded(session_id, event_id, at, agent, message_id, model, usage)`
- The reducer keeps `usage_by_message: Mapping[str, tuple[AgentRef, str, TokenUsage]]`, last one wins
- `TranscriptSource(session_state_lookup, tailer_factory)` follows `transcript_path` and `<session>/subagents/agent-*.jsonl`

**Key tests:**
- `test_fixture_assistant_line_yields_usage`
- `test_repeated_message_id_last_wins`
- `test_subagent_file_maps_to_agent_id` (Q7)
- `test_usage_deduped_across_main_and_subagent_files` (Q8)
- `test_non_assistant_lines_ignored`
- `test_replay_large_transcript_does_not_block_loop` (Review Focus 4): with a generated 50 MB file, a concurrent 10 ms heartbeat task never sees a gap > 100 ms during replay.

### Task 2.3: Pricing and cost
**Files:** `src/kingkai/assets/pricing.toml`, `adapters/pricing.py`, `domain/usage.py` (`Pricing`, `estimate_cost`), tests
**Interfaces:**
- `Pricing(per_mtok: Mapping[str, ModelPrice])`
- `ModelPrice(input, output, cache_write_5m, cache_write_1h, cache_read: Decimal)` (two cache-write tiers, Spike 0b)
- `estimate_cost(usages, pricing) -> CostEstimate(total: Decimal | None, unknown_models: frozenset[str])`

Fill `pricing.toml` from the official Anthropic pricing page at implementation time, and put the date and URL in a header comment.

**Key tests:** `test_cost_sums_five_token_kinds`, `test_cost_state_line_shown_as_claude_code_estimate`, `test_unknown_model_gives_none_and_lists_model`, `test_user_override_wins`, `test_decimal_no_float_drift`.

### Task 2.4: Alerts panel, usage panel, session switcher, diagnostics footer
**Files:** `ui/widgets/{alerts,usage,sessions}.py`, `ui/presenters.py`, `tests/ui/*`
**Key tests:**
- `test_usage_label_says_api_equivalent`
- `test_alert_rows_sorted_by_severity_then_recency`
- `test_switcher_lists_live_before_idle`
- `test_c_dismisses_alerts_until_refire`
- Snapshots: alerts state at 120×40 and 80×24 (the tabbed layout, spec §6.1)

### Task 2.5: Config file and `doctor`
**Files:** `adapters/config.py` (full `kingkai.toml` parsing with `tomllib`; unknown keys are an error), `cli.py` (`doctor`), tests
**Key tests:** `test_unknown_key_is_error_with_path`, `test_defaults_match_spec`, `test_doctor_reports_missing_shim`, `test_doctor_reports_root_key_mismatch`, `test_doctor_exit_code_nonzero_on_failure`.

### Task 2.6: Supervisor and logging
**Files:** `application/supervisor.py`, `adapters/logging_setup.py`, tests
**Interfaces:** `supervise(name: str, factory: Callable[[], Awaitable[None]], *, on_crash: Callable[[str, BaseException], None], sleep: Sleeper, max_backoff: float = 30.0) -> Awaitable[None]`
**Key tests:** `test_restarts_with_exponential_backoff_capped_30s`, `test_crash_raises_internal_alert`, `test_prompt_text_never_logged` (caplog checks that no prompt text appears).

---

## Phase 3: Click-to-reference for Next.js

**Q-S9 is decided: policy (a)**, layered checks, then type. Task 3.5 switches the typing primitive to bracketed paste only if Spike 0b shows that typed text can trigger a dialog and a paste can't.

**Demo:**
- `kingkai up` in `examples/next-demo` opens tmux with claude on the left and kingkai on the right.
- `npm run dev`. Alt+click the `Button` on the page, and `@src/components/ui/Button.tsx#L<n> ` (or the separator Spike 0b chose) appears in the Claude prompt, **not submitted**.
- The TUI's last-reference bar shows "typed (tmux %N)".
- Alt+click during a permission prompt copies to the clipboard instead.

**Exit criteria:**
- The demo works.
- Every S1–S11 test listed in spec §9 exists and passes.
- The e2e job is green.
- Plan verification items "tmux" and "Seguridad" pass.

### Task 3.1: Reference domain (grammar, parsing, minting)
**Files:** `domain/reference.py`, `tests/domain/test_reference.py`, `tests/domain/fakes.py` (`FakeSourceFiles`)
**Interfaces:** exactly as in spec §3.5. Also:
- `RawReference(file: str, line: int)` (`file` is an absolute `file://` URL or an absolute POSIX path; anything else gets `bad_scheme`)
- `RejectionReason` StrEnum with `control_char, bad_scheme, outside_root, not_a_file, missing, bad_segment, bad_line, too_long`
- `GRAMMAR: re.Pattern[str]`
- the private `_MINT = object()`

**Key tests:** all the S4–S7 domain tests named in spec §9, plus `test_root_with_spaces_renders_relative_path` (Review Focus 2), `test_nfc_normalization`, `test_app_router_segments_allowed`, `test_space_in_path_rejected`.

### Task 3.2: Real `SourceFiles` adapter
**Files:** `adapters/source_files.py`, `tests/adapters/test_source_files.py`
**Key tests:** the real-symlink tests for S4 in spec §9, plus `test_line_count_handles_no_trailing_newline` and `test_files_over_10mb_rejected`.

### Task 3.3: Session file and HTTP ingress (guards, payload, app)
**Files:** `adapters/session_file.py`, `adapters/http/{guards,payload,app}.py`, `tests/adapters/http/*`, `tests/adapters/test_session_file.py`
**Interfaces:**
- `guards.check(request_view: RequestView, policy: GuardPolicy, now: datetime) -> GuardFailure | None`, a pure function that takes the method, host, origin, content type, token header and length
- `payload.decode(body: bytes) -> ClickPayload | GuardFailure`
- `make_app(policy, reference_service, overlay_js: bytes) -> web.Application`
- `serve(app) -> RunningServer(url, close)`, which binds `127.0.0.1:0` with `AppRunner` + `TCPSite`

**Key tests:**
- every S1–S3c and S11 test named in spec §9
- `test_root_with_spaces_renders_relative_path`
- `test_200_body_shape`
- `test_unknown_route_404`
- `test_session_file_removed_on_close`

### Task 3.4: Reference service (validate, then the ordered fallback)
**Files:** `application/reference_service.py`, `tests/application/test_reference_service.py`
**Interfaces:**
- `ReferenceService(root, files, typers: Sequence[PromptTyper], store, fmt: ReferenceFormat, target_pane: str | None)`
- `async submit(raw: RawReference, display: DisplayInfo) -> SubmitResult`, where `SubmitResult = Delivered(text, via) | Rejected(reason)`
- `DeliveryOutcome = Typed | Declined(reason)`
- It records `last_reference` in the store for the TUI.

**Key tests:** `test_first_valid_candidate_wins`, `test_node_modules_frame_skipped_when_outside_root`, `test_permission_request_falls_back_to_clipboard`, `test_uses_session_bound_to_target_pane`, `test_label_selector_page_view_never_typed`, `test_all_typers_decline_returns_shown`.

### Task 3.5: tmux typer, pane inspector, dialog signatures
**Files:** `adapters/tmux.py`, `adapters/tmux_dialogs.py`, `tests/adapters/test_tmux.py`, `tests/integration/test_tmux_real.py`, `tests/integration/byte_recorder.py`
**Interfaces:**
- `TmuxPromptTyper(pane: PaneId, run: AsyncRunner, inspector: PaneInspector, dialogs: Sequence[DialogSignature], new_buffer_name: Callable[[], str])`, which delivers through `load-buffer` and `paste-buffer -p -d`
- `PaneStatus(in_mode: bool, command: str, screen: str)`
- `DialogSignature(name: str, pattern: re.Pattern[str], bottom_lines: int)`. The defaults are `esc_to_cancel` (`Esc to cancel`, bottom 15) and `numbered_menu` (`^\s*❯ \d+\. `), tested against every file in `tests/fixtures/screens/`

**Key tests:**
- all the S8 tests, plus the tmux S9 tests named in spec §9
- `test_declines_when_pane_gone`
- `test_declines_when_command_not_claude_or_node`
- `test_stale_flag_cleared_when_screen_shows_no_dialog_after_1_5s`
- `test_signatures_match_only_dialog_screens`: `permission_prompt.txt` and `trust_dialog.txt` match; idle, working, at_autocomplete, slash_menu and after_esc don't
- `@pytest.mark.integration test_text_arrives_without_newline`
- `test_capture_pane_dialog_detected`

### Task 3.6: Clipboard typers and the platform choice
**Files:** `adapters/clipboard.py`, `tests/adapters/test_clipboard.py`
**Interfaces:**
- `WslClipboard`, `MacClipboard`, `WaylandClipboard`, `X11Clipboard`, each a `PromptTyper` with `name = "clipboard"`
- `detect_clipboard(env, which) -> PromptTyper | None`

**Key tests:**
- `test_wsl_uses_powershell_base64_not_clip_exe`: the argv is checked, and so is the round-trip of the base64 of `"@añó.tsx#L1 "`
- `test_copies_only_rendered_reference` (S7)
- `test_wl_copy_not_awaited_with_pipes`
- `test_no_pane_uses_clipboard_and_reports_it` (Review Focus 5, through `bootstrap` with `pane=None`)

### Task 3.7: Browser overlay (TypeScript)
**Files:** `overlay/{package.json,tsconfig.json,biome.json,src/index.ts,src/source.ts,src/ui.ts,src/api.ts,test/*.test.ts}`, a build script that writes `src/kingkai/assets/overlay.js` (gitignored), the CI job `overlay`, and the hatch-free build step in `ci.yml`
**Interfaces:**
- `resolveCandidates(el: Element, appRoot: string): Promise<Candidate[]>`: the runtime owner stack through `bippy/source` (`getSource(fiber, false)`, `getOwnerStack`), with `about://React/<Env>/` frames resolved via `POST /__nextjs_original-stack-frames` (`line1`/`column1`). Relative results are made absolute with `appRoot`. It returns at most 10 candidates, innermost first (Spike 0a).
- `post(url, token, body): Promise<Result>`
- The shadow-root UI shows the highlight, the label and toasts. Clicks are captured in the capture phase with `preventDefault` and `stopPropagation`.

**Key tests (Vitest):** `text_node_uses_parent_element`, `about_react_frames_resolved_via_next_endpoint` (mocked fetch), `relative_endpoint_paths_made_absolute_with_app_root`, `caps_candidates_at_10`, `no_fiber_shows_cannot_locate`, `builds_v1_body`, `restart_toast_on_403_token_or_network_error`, `esc_cancels_highlight`.

### Task 3.8: `kingkai up`, the Next.js snippet, the e2e test
**Files:** `cli.py` (`up`, `init --next` snippet text in `adapters/snippets.py`), `examples/next-demo/src/app/kingkai-overlay.tsx` (the snippet applied to the demo), `tests/e2e/test_next_click.py`, CI job `e2e`
**Key tests:**
- `test_up_creates_session_with_two_panes_and_records_claude_pane`, run against a fake `AsyncRunner` with the argv asserted
- `test_up_strips_parent_claude_code_env_vars`
- `test_next_snippet_reads_session_file_per_request_and_renders_nothing_when_stale`
- `test_next_snippet_renders_app_root_attribute`
- e2e: `test_four_spike_cases_resolve` (client root, server element, `.map` item, imported `ui/Button`; the expected lines are the ones in `docs/spikes/0a-react-source.md`)
- e2e: `test_alt_click_types_reference_bytes`
- e2e: `test_foreign_origin_page_gets_403`
- e2e: `test_click_after_kingkai_restart_shows_reload_toast`

---

## Phase 4: Django

**Demo:** in `examples/django-demo`, a page rendered from `base.html` plus `{% include "partials/card.html" %}`. Alt+click on the card gives `@templates/partials/card.html#L<n> ` in the prompt, and the TUI shows the view `pages/views.py:<line>`.

**Exit criteria:**
- The demo works.
- Plan verification item "Django" passes.
- The tests pass on Django 5.2 and 6.1.
- Q9 is answered in `docs/spikes/4-django-loader.md`.

### Task 4.0: Mini-spike, Q9 (throwaway, time-boxed)
Compare rewriting in `get_contents` with patching the nodelist, using `examples/django-demo`, with and without django-debug-toolbar. Record the result in `docs/spikes/4-django-loader.md`, and update spec §8.3 and §13.

### Task 4.1: Source-annotating loader
**Files:** `integrations/django/loaders.py`, `tests/integrations/django/test_loader.py`, `examples/django-demo/`
**Key tests:** `test_injects_data_src_after_opening_tag_name`, `test_line_numbers_preserved_exactly`, `test_include_maps_to_included_file`, `test_extends_block_maps_to_child_file`, `test_skips_script_style_comments_doctype_closing`, `test_attribute_with_template_tag_inside_is_safe`, `test_non_html_templates_untouched`, `test_noop_when_debug_false`, `test_works_under_cached_loader`.

### Task 4.2: Middleware (script tag and view location)
**Files:** `integrations/django/middleware.py`, tests
**Key tests:** `test_injects_script_before_body_close_only_for_text_html`, `test_nothing_injected_when_session_file_missing_or_pid_dead`, `test_session_file_cached_by_mtime`, `test_view_meta_for_function_and_class_based_views`, `test_noop_when_debug_false`.

### Task 4.3: `init --django` snippet and e2e
**Key tests:** e2e `test_django_alt_click_types_template_reference`, and `test_init_django_prints_settings_snippet`.

---

## Phase 5: Public polish (v0.1.0)

**Demo:** a stranger follows only the README on a fresh machine (try it in a clean container or a new WSL distro), and gets the live view plus click-to-reference working in under 10 minutes.

**Exit criteria:**
- The README has a GIF recorded on a personal project, such as `~/dev/portfolio-web` or the examples, never an employer project.
- `docs/` has architecture, security and troubleshooting pages.
- The tag `v0.1.0` exists with a GitHub release whose notes are generated from Conventional Commits.
- the private-terms grep (`grep -rniEf ~/.config/kingkai-dev/private-terms.txt .`, patterns kept outside the repo) is clean.
- There is no PyPI upload (that's v2).

### Task 5.1: README, docs and GIF
README sections: what it is, a GIF, install (`uv tool install git+https://github.com/matgarfer499/kingkai`), quickstart (`init`, `up`), framework setup, security model summary (linking to spec §9), limitations and non-goals.

### Task 5.2: Hardening pass
Run `/security-review` and `superpowers:requesting-code-review` over the whole repo. Fix the findings with test-first commits.

### Task 5.3: Release
Add `release-please` config only if it fits in this phase; otherwise tag by hand. `git tag v0.1.0`, then create a GitHub release with notes grouped by commit type.

---

## Self-review notes

- **Spec coverage:**
  - §4 → Tasks 1.2, 1.3, 1.7, 2.1, 2.2.
  - §5 → Tasks 1.4, 1.6, 1.8, 1.9.
  - §6 and §6.1 → Tasks 1.5, 1.9, 2.4, 2.5, 3.8.
  - §7 → Task 2.5.
  - §8 → Tasks 3.1–3.8 and 4.x.
  - §9 S1–S11 → Tasks 1.2, 1.4, 3.1–3.6.
  - §10 → Tasks 1.8 (diagnostics), 2.6.
  - §11 → spread across the tasks, plus the 3.8 and 4.3 e2e tests.
  - §12 → Task 1.1, plus 3.7 (overlay toolchain).
- **Names checked across tasks:** `SessionState`, `reduce`, `DomainEvent`, `NdjsonTailer.lines`, `Store.subscribe`, `SessionService.apply`, `PromptTyper.type_reference`, `ReferenceService.submit`, `Reference.render`.
