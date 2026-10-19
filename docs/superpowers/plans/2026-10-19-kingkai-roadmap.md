# kingkai MVP Implementation Plan (phased roadmap)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ship the kingkai MVP. It is a Textual TUI that shows Claude Code's agents, files, tool calls, alerts and cost live. Alt+clicking an element in a local Next.js or Django app pastes `@path#L<line> ` into the Claude Code prompt and never submits it.

**Architecture:** one asyncio process, in layers:
- `domain`: pure; the reducer, detectors and reference grammar;
- `application`: use cases and ports;
- `adapters`: the hook and transcript anti-corruption layer, tailers, aiohttp, tmux, the clipboard;
- `ui`: a thin Textual layer.

A stdlib-only hook client appends Claude Code hook payloads to a per-session spool file, and kingkai tails it.

**Tech stack:**
- Python ≥ 3.12, with uv and uv_build.
- textual 8.2, aiohttp 3.14, msgspec 0.22, cyclopts 5.2.
- ruff 0.17, mypy 2.4 `--strict`, pytest 8.4.x, hypothesis, import-linter 2.15, prek.
- The overlay: TypeScript 7, esbuild, Biome, Vitest and bippy.

**Spec:** `docs/superpowers/specs/2026-10-19-kingkai-design.md`. Section references like §4.3 point there. **The spec is the only source for rules, values and security test names. This plan points to it and does not copy them.**

**Level of detail:**
- Phase 1 is detailed to the step.
- Phases 2–5 are detailed to the task.
- At the start of each later phase, run superpowers:writing-plans again on that phase's section.

## Global Constraints

Every rule in the spec applies to every task. These are the ones most often relevant while coding:
- **Versions:** the floors and pins in §12; `pytest>=8.4,<9`.
- **Runtime dependencies:** only those in §12. Adding one needs a spec change.
- **Layering:** the import-linter contracts in §11.6, and the conventions in §12.1, including the Textual gotchas, the no-markup rule (S12) and `Clock`-only time.
- **Grammar and delivery:** exactly §8.4.
- **Hook entries and shim:** exactly §4.1.
- **File modes:** §5.1 and §8.1.
- **Commits:** Conventional Commits, with no `Co-Authored-By` or "Generated with" trailers.
- **Public repo:** no employer names, code, URLs or screenshots, and no personal email. Before each push, run the private-terms check:

  ```bash
  grep -rniEf ~/.config/kingkai-dev/private-terms.txt . --exclude-dir=.git   # exit 1 = clean
  ```

  The patterns file lives outside the repo on purpose. Never copy its patterns into a tracked file.

## Review Focus

These are inputs that a person using kingkai will hit and that no task's main tests cover. Each has a test in the task that owns the code.

1. **Two hook processes append to the same spool at the same moment.** No line may tear. → Task 1.4, `test_concurrent_appends_never_tear_lines`.
2. **The project root contains spaces or non-ASCII characters (`~/dev/mi proyecto ñ`).** The spool, the shim and the references must all work. → Task 1.4, `test_project_key_with_spaces_and_unicode`; Task 1.5, `test_shim_quotes_paths_with_spaces`; Task 3.1, `test_root_with_spaces_renders_relative_path`.
3. **`settings.local.json` is invalid JSON, or already holds user hooks.** The installer must never destroy them. → Task 1.5, `test_invalid_json_aborts_without_writing`, `test_preserves_user_hooks_on_same_event`.
4. **A 50 MB transcript or spool exists at startup.** The TUI must stay responsive. → Task 1.6, `test_reads_in_bounded_chunks_and_yields`; Task 2.2, `test_replay_large_transcript_does_not_block_loop`.
5. **`kingkai` runs in a folder with no `.git/` or `.claude/` (or outside tmux).** It must not adopt `$HOME` as the project, and it must work without `--pane`. → Task 1.5, `test_home_claude_dir_not_treated_as_project`; Task 3.6, `test_no_pane_uses_clipboard_and_reports_it`.

---

## Phase 0: Spikes ✓ (done 2026-10-19)

The findings are in `docs/spikes/0a-react-source.md` and `docs/spikes/0b-tmux-typing.md`. The fixtures are in `tests/fixtures/`. The spec reflects both spikes. No spike code is in the repo.

---

## Phase 1: Walking skeleton, the live view

**Demo:**
1. In `examples/next-demo`, run `uv run kingkai init --yes`.
2. Run `claude` in terminal A and `uv run kingkai watch` in terminal B.
3. Ask Claude for a task that launches 2 subagents.
4. The TUI shows the agent tree, the tool timeline and the touched files, all live.
5. Restart `watch`: the same state comes back from the spool.

**Exit criteria:**
- The demo works.
- `uv run pytest`, `uv run mypy`, `uv run ruff check`, `uv run ruff format --check` and `uv run lint-imports` all pass.
- CI is green.
- Branch coverage is ≥ 85 %.
- Every §9 test owned by Phase 1 (S10, and the reducer tests of S9) exists and passes.

### Task 1.1: Project scaffold and toolchain

**Files:**
- Create: `pyproject.toml`, `uv.lock`, `src/kingkai/__init__.py` (`__version__ = "0.0.0"`), `src/kingkai/py.typed`
- Create: empty `__init__.py` in `domain/`, `domain/alerts/`, `application/`, `adapters/`, `adapters/hooks/`, `adapters/transcript/`, `adapters/http/`, `ui/`, `ui/widgets/`, `hook_client/` and `integrations/`
- Create: `tests/__init__.py`, `tests/support/__init__.py`, `tests/test_smoke.py`
- Create: `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `.github/dependabot.yml`, `.importlinter`, `CONTRIBUTING.md`
- Create: `examples/next-demo/` (`npx create-next-app@latest next-demo --ts --app --no-eslint --src-dir --use-npm --yes`) and `examples/next-demo/.claude/.gitkeep`. The empty `.claude/` makes it a project root (§5.2).
- Modify: `.gitignore`. Remove the template's `lib/` and `lib64/` lines, which would hide `src/lib/` in the demo. Add `node_modules/`, `.next/` and `src/kingkai/assets/overlay.js`.

**Interfaces:**
- Produces:
  - the console scripts `kingkai = "kingkai.cli:main"` and `kingkai-hook = "kingkai.hook_client.__main__:main"`;
  - the `dev` dependency group.

- [ ] **Step 1: Write `tests/test_smoke.py`.** `test_version_is_string` asserts `isinstance(kingkai.__version__, str)`.
- [ ] **Step 2: Write `pyproject.toml`:**
  - the build backend is `uv_build>=0.13.1,<0.14`;
  - runtime and extra dependencies come from §12;
  - `[dependency-groups] dev` holds `ruff==0.17.*`, `mypy==2.4.*`, `import-linter==2.15.*`, `pytest>=8.4,<9`, `pytest-asyncio>=1.4`, `pytest-textual-snapshot>=1.1`, `pytest-cov>=7.1`, `hypothesis>=6.170` and `textual-dev>=1.8`;
  - pytest: `asyncio_mode = "auto"`, `addopts = "-ra --strict-markers"`, `markers = ["integration: needs tmux"]`;
  - mypy: `strict = true`, `files = ["src", "tests"]`;
  - ruff: the §12 rule set, `target-version = "py312"`, `line-length = 100`, and per-file ignores for tests (`S101, ANN, PLR2004, FBT, SLF001`);
  - coverage: `branch = true`, `fail_under = 85`.
- [ ] **Step 3: Write `.importlinter`.** It holds the three contracts from §11.6, exactly as named there.
- [ ] **Step 4: Write `.pre-commit-config.yaml`:**
  - `astral-sh/ruff-pre-commit` v0.17.1 (ruff-check with `--fix`, and ruff-format);
  - local hooks for `uv run mypy` and `uv run lint-imports`;
  - `compilerla/conventional-pre-commit` v4.4.0 at `commit-msg`.

  Then run `prek install --hook-type pre-commit --hook-type commit-msg`.
- [ ] **Step 5: Write `ci.yml`.** It has the `check` and `test` jobs from §12. The `test` job:
  - uses the matrix `{ubuntu: [3.12, 3.15], macos: [3.15]}`;
  - on Ubuntu, runs `sudo apt-get install -y tmux` and then `uv run --frozen pytest --cov=kingkai`, including the integration marker;
  - on macOS, adds `-m "not integration"`.

  Pin actions by SHA, with a `# vX.Y.Z` comment.
- [ ] **Step 6: Write `dependabot.yml`.** Ecosystems: `uv` and `github-actions`, weekly, with prefix `build(deps)`. npm is added in Phase 3.
- [ ] **Step 7: Run every check.** `uv sync && uv run pytest && uv run mypy && uv run ruff check && uv run ruff format --check && uv run lint-imports`. Expected: everything passes, and every contract is KEPT.
- [ ] **Step 8: Commit, push and check CI**

```bash
git add -A && git commit -m "build: scaffold uv project with ruff, mypy, pytest, import-linter and ci"
git push   # then check the run in GitHub Actions (gh is not authenticated; use the GitHub MCP or the web UI)
```

### Task 1.2: Domain types and the reducer

**Files:**
- Create: `src/kingkai/domain/ids.py`, `json.py`, `state.py`, `events.py`, `reducer.py`
- Test: `tests/domain/factories.py` (builder functions such as `started(id, agent=MAIN, at=…)`), `tests/domain/test_reducer.py`, `tests/domain/test_reducer_properties.py`

**Interfaces:**
- Produces:
  - `SessionId`, `AgentId`, `ToolUseId`, `EventId`: `NewType(str)`.
  - `JsonValue`: a recursive type alias.
  - `MainAgent()` (a frozen dataclass with `MAIN = MainAgent()`), `SubAgent(agent_id)`, and `AgentRef = MainAgent | SubAgent`.
  - `FileTouch(path: str, kind: Literal["read","write","search"])`.
  - `ToolCall(tool_use_id, agent, tool, summary, input_fingerprint, touches, status: Literal["running","succeeded","failed","abandoned"], started_at: datetime | None, ended_at: datetime | None, duration_ms: int | None, error_summary: str | None)`.
  - `AgentNode(ref, agent_type: str, status: Literal["running","done"], started_at: datetime)`.
  - `SessionState(session_id, agents: Mapping[AgentRef, AgentNode], calls: Mapping[ToolUseId, ToolCall], call_order: tuple[ToolUseId, ...], turn_open: bool, awaiting_permission: Mapping[AgentRef, datetime], ended: bool, started_at: datetime | None, last_activity: datetime | None, seen: frozenset[EventId], tmux_pane: str | None, transcript_path: str | None)`. `SessionState.initial(session_id)` creates the main agent node lazily.
  - The events of §4.2 except `UsageRecorded`, `Tick` and `ReplayCompleted` (those come in Phase 2). All have the base fields `session_id`, `event_id`, `at`.
  - `reduce(state, event) -> SessionState`.

- [ ] **Step 1: Write the failing tests** in `test_reducer.py`:
  - `test_started_then_succeeded_marks_call_succeeded` (status, `duration_ms`, `call_order`)
  - `test_succeeded_before_started_converges`
  - `test_duplicate_event_id_is_noop`
  - `test_tool_call_from_unseen_subagent_creates_node_with_its_type`
  - `test_untyped_subagent_stop_for_unseen_agent_ignored`: covers both `agent_type=None` and `""` (auxiliary agents)
  - `test_subagent_start_stop_lifecycle`
  - `test_running_calls_abandoned_on_next_turn_started`
  - `test_running_calls_abandoned_on_session_end`
  - `test_system_turn_kind_is_preserved`
  - the four reducer tests listed for S9 in spec §9, with exactly those names
  - `test_last_activity_tracks_hook_events`
- [ ] **Step 2: Run them.** `uv run pytest tests/domain/test_reducer.py -v` must FAIL, because the module doesn't exist yet.
- [ ] **Step 3: Implement the types and `reduce`.** `reduce` dispatches with `match` to one private `_apply_<event>` function per event type.
- [ ] **Step 4: Write the property tests:**
  - `test_tool_call_state_independent_of_interleaving`: 1–6 calls, interleavings generated by hypothesis; compares `calls` and the set of touches;
  - `test_reduce_idempotent`.
- [ ] **Step 5: Run them.** `uv run pytest tests/domain -v` must PASS.
- [ ] **Step 6: Commit:** `feat(domain): add session state reducer with tool-call correlation`.

### Task 1.3: File touches and fingerprints

**Files:**
- Create: `src/kingkai/domain/tools.py`
- Test: `tests/domain/test_tools.py`

**Interfaces:**
- Produces:
  - `touches_for(tool: str, tool_input: Mapping[str, JsonValue]) -> tuple[FileTouch, ...]`, following the rules in §4.2;
  - `fingerprint(tool_input) -> str`: SHA-256 hex of `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`.

- [ ] **Step 1: Write parametrized failing tests:**
  - Read gives read; Edit, MultiEdit and Write give write; NotebookEdit with `notebook_path` gives write.
  - Grep with a `path` gives search; Grep without one, Glob and Bash give `()`.
  - A path given as a `$sha256` dict gives `()`.
  - `test_fingerprint_key_order_insensitive`.
  - `test_fingerprint_differs_on_value_change`.
- [ ] **Step 2: Run them.** They must FAIL. **Step 3:** implement, using a dict from tool name to `(field, kind)`. **Step 4:** they must PASS.
- [ ] **Step 5: Commit:** `feat(domain): extract file touches and input fingerprints from tool calls`.

### Task 1.4: Hook client and the spool-line test helper

**Files:**
- Create: `src/kingkai/hook_client/__main__.py`, `shrink.py`, `envelope.py`, `spool.py`
- Create: `tests/support/spool.py`
- Test: `tests/hook_client/test_shrink.py`, `test_envelope.py`, `test_spool.py`, `test_main.py`

**Interfaces:**
- Produces:
  - `shrink(payload: dict[str, object]) -> dict[str, object]`: cuts top-level fields first, then hashes recursively, as in §5.1.
  - `envelope(payload, *, event_id: str, at: datetime, pane: str | None) -> dict[str, object]`.
  - `project_key(root: str) -> str`.
  - `spool_path(state_dir: Path, root: str, session_id: str) -> Path | None`.
  - `append_line(path: Path, line: bytes) -> None`, which creates directories with mode 0700 and the file with mode 0600, and writes under `flock`.
  - `main(stdin: BinaryIO = sys.stdin.buffer, env: Mapping[str, str] = os.environ, now: Callable[[], datetime] = …, new_id: Callable[[], str] = lambda: uuid4().hex) -> int`.
  - `tests/support/spool.py`:
    - `as_spool_line(payload: dict[str, object], n: int, *, pane: str | None = None) -> bytes`: runs the real `shrink` and `envelope` with `event_id=f"{n:032x}"` and `at = 2026-10-19T00:00:00Z + n seconds`;
    - `fixture_spool(name: str) -> list[bytes]`: loads `tests/fixtures/hooks/<name>` (`.json` or `.ndjson`) and converts each payload.

- [ ] **Step 1: Write the failing tests:**
  - `test_shrink.py`:
    - `test_long_string_becomes_digest`
    - `test_top_level_prompt_cut_to_80`
    - `test_nested_prompt_is_hashed_not_cut`: `tool_input.prompt` of 600 characters becomes `$sha256`, and two prompts that share an 80-character prefix get different digests
    - `test_error_cut_to_200`
    - `test_all_strings_bounded`†
    - `test_equal_inputs_equal_output`†
  - `test_envelope.py`: `test_adds_kk_with_v_id_at_pane`.
  - `test_spool.py`:
    - the S10 spool tests named in §9
    - `test_concurrent_appends_never_tear_lines`: 8 processes × 200 lines × 3 000 bytes
    - `test_project_key_with_spaces_and_unicode`
  - `test_main.py`:
    - the S10 `test_main.py` tests named in §9
    - `test_writes_enveloped_line_for_fixture`: feed `tests/fixtures/hooks/pre_tool_use_main.json` through stdin and check the spool line equals `as_spool_line(payload, n)` when the ids are injected
- [ ] **Step 2: Run them.** They must FAIL.
- [ ] **Step 3: Implement.** `main` catches `BaseException` except `KeyboardInterrupt`, with a comment explaining the S10 reason.
- [ ] **Step 4: Run** `uv run pytest tests/hook_client -v && uv run lint-imports`. They must PASS, with `hook-client-stdlib-only` KEPT.
- [ ] **Step 5: Measure import time.** Run `python -X importtime -m kingkai.hook_client < tests/fixtures/hooks/pre_tool_use_main.json 2>&1 | tail -1`. It must be under 50 ms; record the figure in the commit body.
- [ ] **Step 6: Commit:** `feat(hook-client): append shrunk, enveloped hook payloads to per-session spool`.

### Task 1.5: Project root, settings installer, shim, `init` and `uninstall`

**Files:**
- Create: `src/kingkai/adapters/project.py`, `settings_installer.py`, `src/kingkai/cli.py`
- Test: `tests/adapters/test_project.py`, `test_settings_installer.py`, `tests/adapters/golden/installed.json`, `tests/test_cli.py`

**Interfaces:**
- Produces:
  - `HOOK_EVENTS: tuple[str, ...]`: the 11 events of §4.1, in table order.
  - `install(settings: Mapping[str, JsonValue], shim: str) -> dict[str, JsonValue]` and `uninstall(...)`. Both are pure.
  - `write_shim(path: Path, python: str) -> None`: the two-line shim from §4.1, with `PY` quoted via `shlex.quote`, mode 0755.
  - `find_project_root(start: Path, home: Path) -> Path`: it looks for `.git/` or `.claude/` while walking up, never returns `home` or anything above it, and falls back to `start`.
  - `ensure_locally_ignored(root: Path, rel: str, run: Runner) -> Literal["ignored", "added", "not-git"]`, where `Runner` is a Protocol: `__call__(argv: Sequence[str]) -> CompletedProcess[str]`.
  - The cyclopts `app` with `init(*, yes=False, next=False, django=False, root: Path | None = None)` and `uninstall(*, root=None)`, plus `main(argv=None) -> int`. `--next` and `--django` print "available in Phase 3/4" for now.

- [ ] **Step 1: Write the failing tests:**
  - installer:
    - `test_install_adds_all_events_async`: matches the golden file
    - `test_install_idempotent`
    - `test_preserves_user_hooks_on_same_event`
    - `test_preserves_unrelated_keys`
    - `test_uninstall_removes_only_ours`
  - shim:
    - the two S10 shim tests named in §9, which run the shim with a real `sh`
    - `test_shim_quotes_paths_with_spaces`
  - project root:
    - `test_find_project_root_walks_up_to_git`
    - `test_find_project_root_stops_at_nearest_claude_dir`
    - `test_home_claude_dir_not_treated_as_project`
    - `test_falls_back_to_start`
  - CLI:
    - `test_invalid_json_aborts_without_writing`: exit code 2, and the file bytes are unchanged
    - `test_init_creates_kingkai_dir_with_star_gitignore`
    - `test_init_requires_yes_when_not_a_tty`
    - `test_init_adds_settings_local_to_git_exclude_when_not_ignored`
- [ ] **Step 2: Run them.** They must FAIL. **Step 3:** implement; the diff preview uses `difflib.unified_diff`. **Step 4:** they must PASS.
- [ ] **Step 5: Try it by hand.** In `examples/next-demo`, run `uv run kingkai init --yes`, then `cat .claude/settings.local.json` and `git check-ignore .claude/settings.local.json`. Expected: the 11 hooks, and the file reported as ignored.
- [ ] **Step 6: Commit:** `feat(cli): install and remove hooks in settings.local.json via a stable shim`.

### Task 1.6: NDJSON tailer

**Files:**
- Create: `src/kingkai/application/ports.py` (`Clock`, `Sleeper`, `EventSource`), `src/kingkai/adapters/tail.py`
- Test: `tests/adapters/test_tail.py`, `tests/support/fakes.py` (`FakeSleeper`, `FakeClock`)

**Interfaces:**
- Produces:
  - `TailedLine(path: Path, offset: int, data: bytes)`.
  - `NdjsonTailer(path, *, poll_interval: float, sleep: Sleeper, chunk_size: int = 65536)`, with `lines() -> AsyncIterator[TailedLine]` and `at_eof() -> bool`.

- [ ] **Step 1: Write the failing tests:**
  - `test_yields_complete_lines_only`, including offsets
  - `test_truncation_restarts_from_zero`
  - `test_inode_change_restarts_from_zero`
  - `test_missing_file_waits`
  - `test_reads_in_bounded_chunks_and_yields`: a 5 MB file awaits `sleep(0)` at least 5 MB / 64 KiB times
- [ ] **Step 2: They must FAIL. Step 3: implement. Step 4: they must PASS.**
- [ ] **Step 5: Commit:** `feat(adapters): add offset-tracking ndjson tailer`.

### Task 1.7: Hook schema and translation (anti-corruption layer)

**Files:**
- Create: `src/kingkai/adapters/hooks/schema.py`, `translate.py`, `scripts/scrub_fixtures.py`
- Test: `tests/adapters/hooks/test_translate.py`, `tests/scripts/test_scrub_fixtures.py`

**Interfaces:**
- Consumes: the events from Task 1.2; `touches_for` and `fingerprint` from Task 1.3; `fixture_spool` from Task 1.4.
- Produces:
  - one `msgspec.Struct` per payload kind, tagged by `hook_event_name`, each with `kk: Envelope = msgspec.field(name="_kk")`;
  - `decode_line(data: bytes) -> HookPayload | None`. It returns `None` on any decode or validation error, **including a missing `_kk`**;
  - `to_domain(p: HookPayload) -> DomainEvent | None`:
    - `None` for ignored events;
    - `TurnStarted.kind = "system"` when `prompt` starts with `<task-notification>`;
    - `agent_type` passed through as given, including `""`;
    - `summary` built as described in §4.2;
  - `scripts/scrub_fixtures.py`, which wraps the scrubbing from Spike 0b: path, UUID and account-key rewriting and status-line removal.

- [ ] **Step 1: Write the failing tests:**
  - one test per hook fixture, asserting the exact domain event, for example `test_pre_tool_use_subagent_fixture` with the agent, `agent_type`, touches and summary
  - `test_full_run_replays_to_expected_tree`: `fixture_spool("session_full_run.ndjson")` → decode → reduce gives 2 visible subagents (both `general-purpose`), 3 failed `Bash` calls, no auxiliary agents, and `ended`
  - `test_task_notification_prompt_is_system_turn`
  - `test_unknown_event_returns_none`
  - `test_unknown_fields_ignored`
  - `test_missing_kk_returns_none`
  - `test_garbage_bytes_return_none`
  - `test_scrub_removes_home_paths_and_account_keys`
- [ ] **Step 2: They must FAIL. Step 3: implement. Step 4: they must PASS.**
- [ ] **Step 5: Commit:** `feat(adapters): translate claude code hook payloads into domain events`.

### Task 1.8: Store, SessionService and spool discovery

**Files:**
- Create: `src/kingkai/application/store.py`, `session_service.py`, `src/kingkai/adapters/spool_source.py`, `clock.py`
- Test: `tests/application/test_store.py`, `test_session_service.py`, `tests/adapters/test_spool_source.py`

**Interfaces:**
- Consumes: `NdjsonTailer`, `decode_line`, `to_domain` and `reduce`.
- Produces:
  - `Diagnostics` with `record(reason: str) -> None` and `skipped: Mapping[str, int]`.
  - `Store` with:
    - `get(session_id)`, `sessions()` and `put(state)`;
    - `subscribe(cb: Callable[[SessionState], None]) -> Callable[[], None]`, which returns an unsubscribe function;
    - a `diagnostics: Diagnostics` attribute.
  - `SessionService(store, sources: Sequence[EventSource])` with `async run()` and `apply(event)`. `apply` is synchronous so tests can call it directly.
  - `SpoolDirectory(dir: Path, *, scan_interval: float, sleep: Sleeper, now: Callable[[], datetime], tailer_factory: Callable[[Path], NdjsonTailer], on_skip: Callable[[str], None])`, implementing `EventSource`.
  - `SystemClock`.

- [ ] **Step 1: Write the failing tests:**
  - `test_apply_routes_by_session_and_notifies_subscribers`
  - `test_unsubscribe_stops_notifications`
  - `test_run_drains_all_sources`
  - `test_discovers_new_spool_file_after_start`
  - `test_ignores_files_older_than_24h`
  - `test_undecodable_line_reported_via_on_skip`
- [ ] **Step 2: They must FAIL. Step 3: implement. Step 4: they must PASS.**
- [ ] **Step 5: Commit:** `feat(application): add store and session service fed by spool discovery`.

### Task 1.9: Presenters and view models

**Files:**
- Create: `src/kingkai/ui/presenters.py`
- Test: `tests/ui/test_presenters.py`

**Interfaces:**
- Produces:
  - `AgentRowVM(depth: int, label: str, status_icon: str)`. The label is `"main"` for the main agent and `f"{agent_type} {agent_id[:6]}"` for subagents. The icon is `●` when running and `✓` when done.
  - `TimelineRowVM(time: str, agent: str, tool: str, summary: str, status_icon: str, duration: str)`:
    - `time` is `HH:MM:SS` in local time;
    - `agent` is `main`, or the first 6 characters of the agent id;
    - `status_icon` is `●`, `✓`, `✗` or `⊘` (abandoned);
    - `duration` is `12ms`, `2.1s` or empty.
  - `FileRowVM(kind: Literal["R","W","S"], path: str, count: int)`.
  - `ScreenVM(title: str, agents: tuple[AgentRowVM, ...], timeline: tuple[TimelineRowVM, ...], files: tuple[FileRowVM, ...], footer: str)`:
    - the timeline keeps the last 200 calls, newest last;
    - the title includes `live`, `idle` (no activity for over 30 min) or `ended`;
    - the footer shows the skipped-line counts.
  - `present(state: SessionState | None, now: datetime, *, root: Path, skipped: Mapping[str, int]) -> ScreenVM`.
  - `pick_session(sessions: Sequence[SessionState], pane: str | None) -> SessionState | None`, which applies the rule in §5.2.

- [ ] **Step 1: Write the failing tests:**
  - `test_tree_nests_subagents_under_main`
  - `test_timeline_newest_last_capped_200`
  - `test_abandoned_call_icon`
  - `test_files_aggregate_and_write_wins_over_read`
  - `test_paths_relative_to_root_when_inside`
  - `test_idle_derived_from_last_activity`
  - `test_pick_session_prefers_pane_binding_then_newest`
  - `test_empty_state_renders_placeholder`
- [ ] **Step 2: They must FAIL. Step 3: implement. Step 4: they must PASS.**
- [ ] **Step 5: Commit:** `feat(ui): add pure presenters for agents, timeline and files`.

### Task 1.10: Textual app, bootstrap and `watch`

**Files:**
- Create: `src/kingkai/ui/app.py`, `ui/widgets/agent_tree.py`, `ui/widgets/timeline.py`, `ui/widgets/files.py`, `ui/app.tcss`, `src/kingkai/adapters/config.py` (minimal), `src/kingkai/bootstrap.py`
- Modify: `src/kingkai/cli.py`, adding `watch(*, root=None, pane=None)`
- Test: `tests/ui/test_app.py`, `tests/ui/test_widgets.py`, `tests/ui/test_snapshots.py`, `tests/test_bootstrap.py`

**Interfaces:**
- Consumes: `Store`, `SessionService`, `present` and `pick_session`.
- Produces:
  - `Config(root: Path, state_dir: Path, pane: str | None)`, frozen. It grows in Phase 2.
  - `KingkaiApp(App[None])` with `__init__(store, service, clock, root, pane)`. Its bindings are `s` (next session), `q` and `ctrl+q`.
  - `build_app(config) -> KingkaiApp`.

- [ ] **Step 1: Write the failing tests:**
  - `test_events_reach_widgets`: apply 3 events, `await pilot.pause()`, and the timeline `DataTable.row_count == 3`
  - `test_renders_at_most_once_per_tick`: 50 events in one tick cause ≤ 1 render, counted with a render counter on the app
  - `test_s_cycles_sessions_and_stops_autofollow`
  - `test_display_strings_rendered_without_markup` (S12)
  - snapshots: `test_snapshot_empty` and `test_snapshot_two_subagents` at 120×40
  - `test_build_app_wires_spool_dir_for_project_key`
- [ ] **Step 2: They must FAIL.**
- [ ] **Step 3: Implement.**
  - The store callback sets a dirty flag, and `set_interval(0.1)` renders when it is set (§5.3).
  - The service runs as `@work(exclusive=True, group="service")`.
  - Widgets are built in `__init__` and yielded in `compose`, and every data string goes in as `Text`.
- [ ] **Step 4: Generate the snapshots.** Run `uv run pytest tests/ui --snapshot-update`, inspect the SVGs, then run `uv run pytest tests/ui -v`. It must PASS.
- [ ] **Step 5: Commit:** `feat(ui): show live agent tree, timeline and files in the textual app`.

### Task 1.11: Phase 1 demo check

- [ ] **Step 1:** Run the Phase 1 demo. Prompt: "Use two subagents in parallel: one reads package.json, the other lists the files in src/app. Then summarize."
- [ ] **Step 2: Expected result:**
  - The tree shows main plus 2 `general-purpose` subagents.
  - The timeline shows Read and Bash/Glob calls attributed to the right agent.
  - The files panel shows `package.json` (R).
- [ ] **Step 3:** Quit and restart `watch`. Expected: the same state is rebuilt by replay.
- [ ] **Step 4:** Fix every problem with a failing test first, committing each as `fix(<scope>): …`.

---

## Phase 2: Alerts, usage and cost, doctor

**Demo:**
- Ask Claude to "run `ls does-not-exist` three times". The alerts show RetryLoop and RepeatedCall within about a second of the third failure.
- Usage and `≈ $` rise while Claude works.
- An 80-column terminal shows the tabbed layout.

**Exit criteria:**
- The demo works.
- The §4.4 and §4.5 behaviour is covered by tests.
- The coverage gate holds.

### Task 2.1: Detectors
**Files:**
- `domain/alerts/{base,repeated_call,tool_failure,retry_loop,stall}.py`
- add `alerts: Mapping[str, Alert]` and `replay_done` to `SessionState`
- add the `Tick` and `ReplayCompleted` events
- `tests/domain/alerts/*`

**Interfaces:**
- `Alert(key, kind, severity, agent, message, first_at, last_at, count)`
- `AlertChanges(raise_: tuple[Alert, ...], clear: tuple[str, ...])`
- `Detector.__call__(before, event, now) -> AlertChanges`
- `apply_alerts(state, changes)`
- `SessionService` gains `detectors: Sequence[Detector]` and a 1 s tick worker.

**Key tests:** each detector's fire and clear conditions from §4.4, including:
- `test_stall_uses_600s_while_call_running`
- `test_stall_suppressed_while_dialog_flag_set`
- `test_stall_disabled_before_replay_completed`
- `test_tick_and_usage_do_not_count_as_activity`
- `test_interrupt_failure_not_alerted`
- `test_full_run_fixture_raises_retry_loop_and_repeated_call`

### Task 2.2: Transcript usage source
**Files:** `adapters/transcript/{schema,translate}.py`, `adapters/transcript_source.py`, `domain/usage.py` (`TokenUsage`), tests

**Interfaces:**
- `TokenUsage(input, output, cache_write_5m, cache_write_1h, cache_read)`, with `__add__`
- `UsageRecorded` as in §4.2
- the reducer adds `usage_by_message: Mapping[str, tuple[AgentRef, str, TokenUsage]]`, last value wins
- `TranscriptSource` follows each session's `transcript_path` and `subagents/agent-*.jsonl`

**Key tests:**
- `test_fixture_assistant_lines_yield_usage_with_cache_tiers`
- `test_repeated_message_id_last_wins`
- `test_subagent_file_maps_to_agent_id`
- `test_non_assistant_lines_ignored`
- `test_cost_state_line_parsed_when_present`
- `test_replay_large_transcript_does_not_block_loop`: 50 MB, with a 10 ms heartbeat that never stalls more than 100 ms

### Task 2.3: Pricing and cost
**Files:** `assets/pricing.toml` (filled from the official Anthropic pricing page, with the URL and date in a comment), `adapters/pricing.py`, `domain/usage.py` (`ModelPrice`, `Pricing`, `estimate_cost`), tests

**Interfaces:**
- `ModelPrice(input, output, cache_write_5m, cache_write_1h, cache_read: Decimal)`
- `estimate_cost(usages, pricing) -> CostEstimate(total: Decimal | None, unknown_models: frozenset[str])`

**Key tests:** `test_cost_sums_five_token_kinds`, `test_unknown_model_gives_none_and_lists_model`, `test_user_override_wins`, `test_decimal_no_float_drift`.

### Task 2.4: Alerts and usage panels, the tabbed layout, help
**Files:** `ui/widgets/{alerts,usage}.py`, `ui/presenters.py`, the help screen, tests

**Key tests:**
- `test_usage_label_says_api_equivalent`
- `test_claude_code_estimate_shown_when_present`
- `test_alert_rows_sorted_by_severity_then_recency`
- `test_c_dismisses_alerts_until_refire`
- `test_help_mentions_auxiliary_usage_not_counted`
- snapshots: the alerts state at 120×40 and the tabbed layout at 80×24

### Task 2.5: Config file and `doctor`
**Files:** `adapters/config.py` (§7, using `tomllib`; unknown keys are an error), `cli.py` (`doctor`), tests

**Key tests:**
- `test_unknown_key_is_error_with_path`
- `test_defaults_match_spec`
- `test_bind_host_key_rejected` (S1)
- `test_doctor_reports_broken_shim`
- `test_doctor_reports_root_key_mismatch`
- `test_doctor_exit_code_nonzero_on_failure`

### Task 2.6: Supervisor and logging
**Files:** `application/supervisor.py`, `adapters/logging_setup.py`, tests

**Interfaces:** `supervise(name, factory, *, on_crash, sleep, max_backoff=30.0) -> Awaitable[None]`

**Key tests:** `test_restarts_with_exponential_backoff_capped_30s`, `test_crash_raises_internal_alert`, `test_prompt_text_never_logged`.

---

## Phase 3: Click-to-reference for Next.js

**Demo:**
- `kingkai up` in `examples/next-demo` opens tmux with claude and kingkai side by side.
- With `npm run dev` running, Alt+click the Button: `@src/components/ui/Button.tsx#L<n> ` appears in the Claude prompt, **not submitted**, and the TUI says "typed (tmux %N)".
- Alt+click while a permission dialog is open: the reference goes to the clipboard instead.

**Exit criteria:**
- The demo works.
- Every S1–S9, S11 and S12 test in spec §9 exists and passes.
- The `overlay` and `e2e` CI jobs are green.

### Task 3.1: Reference domain
**Files:** `domain/reference.py`, `tests/domain/test_reference.py`, `tests/support/fakes.py` (`FakeSourceFiles`), `tests/architecture/test_reference_minting.py`

**Interfaces:**
- as in §3.5;
- `RawReference(file: str, line: int)`;
- the `RejectionReason` values `control_char, bad_scheme, too_long, outside_root, excluded_dir, not_a_file, missing, bad_segment, bad_line`;
- `GRAMMAR` as in §8.4.

**Key tests:** the S4–S7 domain and architecture tests in §9, plus `test_root_with_spaces_renders_relative_path`, `test_app_router_segments_allowed` and `test_space_in_path_rejected`.

### Task 3.2: Real `SourceFiles`
**Files:** `adapters/source_files.py`, tests

**Key tests:** the real-symlink tests for S4 in §9, plus `test_line_count_handles_no_trailing_newline` and `test_files_over_10mb_rejected`.

### Task 3.3: Session file and HTTP ingress
**Files:** `adapters/session_file.py`, `adapters/http/{guards,payload,app}.py`, tests

**Interfaces:**
- `guards.check(view: RequestView, policy: GuardPolicy, now) -> GuardFailure | None`, a pure function
- `payload.decode(body) -> ClickPayload | GuardFailure`
- `make_app(policy, reference_service, overlay_js) -> web.Application`
- `serve(app) -> RunningServer(url, close)`

**Key tests:** the S1, S2, S3, S3a–c, S6 payload and S11 tests in §9, plus `test_200_body_shape`, `test_unknown_route_404` and `test_session_file_removed_on_close`.

### Task 3.4: Reference service
**Files:** `application/reference_service.py`, tests

**Interfaces:**
- `ReferenceService(root, files, typers, store, clock, target_pane, dialog_grace=timedelta(seconds=10))`
- `async submit(kind, candidates, display) -> Delivered(text, via) | Rejected(reason)`
- it records `last_reference` for the TUI

**Key tests:** the S5, S7 and S9 `test_reference_service.py` tests in §9, plus `test_all_typers_decline_returns_shown`.

### Task 3.5: tmux typer
**Files:** `adapters/tmux.py`, `tests/adapters/test_tmux.py`, `tests/integration/test_tmux_real.py`, `tests/integration/byte_recorder.py`

**Interfaces:**
- `TmuxPromptTyper(pane, run: AsyncRunner, signatures: Sequence[DialogSignature] = DEFAULT_SIGNATURES, new_buffer: Callable[[], str])`
- the pane checks and screen checks are private methods built on `run`
- `DialogSignature(name, pattern: re.Pattern[str], bottom_lines: int)`

**Key tests:** the S8 and tmux S9 tests in §9, plus `test_declines_when_pane_gone`.

### Task 3.6: Clipboard
**Files:** `adapters/clipboard.py`, tests

**Interfaces:**
- `ClipboardCommand(name, argv: Callable[[str], list[str]], stdin: Callable[[str], bytes | None], wait: bool)`
- `ClipboardTyper(command, run)`
- `detect_clipboard(env, which) -> ClipboardTyper | None`

**Key tests:**
- `test_wsl_row_uses_powershell_base64`: round-trips `"@añó.tsx#L1 "`
- `test_copies_only_rendered_reference` (S7)
- `test_wl_copy_not_awaited_with_pipes`
- `test_no_pane_uses_clipboard_and_reports_it`

### Task 3.7: Browser overlay
**Files:** `overlay/{package.json,tsconfig.json,biome.json,src/{index,resolve,ui,api}.ts,test/*.test.ts}`, plus the CI `overlay` job and the npm Dependabot entry

**Interfaces:**
- `resolveCandidates(el: Element, appRoot: string): Promise<Candidate[]>`, which follows §8.2 (`bippy/source`, `getSource(fiber, false)`, the Next endpoint with `line1`/`column1`)
- `post(url, token, body): Promise<Result>`
- the shadow-root UI

**Key tests:**
- `text_node_uses_parent_element`
- `about_react_frames_resolved_via_next_endpoint`
- `relative_endpoint_paths_made_absolute_with_app_root`
- `caps_candidates_at_10`
- `no_fiber_shows_cannot_locate`
- `restart_toast_on_403_or_network_error`
- `esc_cancels_highlight`

### Task 3.8: `kingkai up`, the Next snippet, e2e
**Files:** `cli.py` (`up`, `init --next`), `adapters/snippets.py`, `examples/next-demo/src/app/kingkai-overlay.tsx`, the four Spike 0a components in the demo, `tests/e2e/test_next_click.py`, the CI `e2e` job

**Key tests:**
- `test_up_creates_two_panes_and_records_claude_pane`, using a fake runner and asserting the argv
- `test_up_strips_parent_claude_code_env_vars`
- `test_next_snippet_renders_nothing_when_session_file_stale`
- `test_next_snippet_renders_app_root_attribute`
- e2e: `test_four_spike_cases_resolve`, `test_alt_click_pastes_exact_bytes`

---

## Phase 4: Django

**Demo:** in `examples/django-demo`, Alt+click a card rendered from `{% include "partials/card.html" %}`. That gives `@templates/partials/card.html#L<n> `, and the TUI shows the view as `pages/views.py:<line>`.

**Exit criteria:**
- The demo works.
- The tests pass on Django 5.2 and 6.1.
- Q9 is answered in `docs/spikes/4-django-loader.md`, and the spec is updated.

- **Task 4.0: Q9 mini-spike** (throwaway, time-boxed). Write the findings doc and update §8.3.
- **Task 4.1: Source-annotating loader.**
  - Files: `integrations/django/loaders.py`, `examples/django-demo/`, tests.
  - Key tests: `test_injects_data_src_after_opening_tag_name`, `test_line_numbers_preserved_exactly`, `test_include_maps_to_included_file`, `test_extends_block_maps_to_child_file`, `test_skips_script_style_comments_doctype_closing`, `test_attribute_with_template_tag_inside_is_safe`, `test_non_html_templates_untouched`, `test_noop_when_debug_false`, `test_works_under_cached_loader`.
- **Task 4.2: Middleware.**
  - Key tests: `test_injects_script_before_body_close_only_for_text_html`, `test_nothing_injected_when_session_file_missing_or_pid_dead`, `test_session_file_cached_by_mtime`, `test_view_meta_for_function_and_class_based_views`, `test_noop_when_debug_false`.
- **Task 4.3: `init --django` and e2e.**
  - Key tests: `test_init_django_prints_settings_snippet`, and e2e `test_django_alt_click_pastes_template_reference`.

---

## Phase 5: Public polish (v0.1.0)

**Demo:** a stranger follows only the README on a fresh machine (a clean container or a new WSL distro) and has both features working in under 10 minutes.

**Exit criteria:**
- The README has a GIF and screenshots recorded on `examples/` or a personal project.
- `docs/` covers architecture, security and troubleshooting.
- `v0.1.0` is tagged, with a GitHub release whose notes are grouped by commit type.
- The private-terms check is clean.

- **Task 5.1: README, docs, GIF and screenshots.** Cover install (`uv tool install git+https://github.com/matgarfer499/kingkai`), quickstart, framework setup, the security summary and the limitations.
- **Task 5.2: Hardening.** Run `/security-review` and superpowers:requesting-code-review on the whole repo, and fix findings test-first.
- **Task 5.3: Release.** Tag `v0.1.0` and create the GitHub release.

---

## Self-review notes

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| §4 | 1.2, 1.3, 1.7, 2.1, 2.2 |
| §5 | 1.4, 1.6, 1.8, 1.10 |
| §6 and §6.1 | 1.5, 1.10, 2.4, 2.5, 3.8 |
| §7 | 2.5 |
| §8 | 3.x, 4.x |
| §9 | S10 → 1.4 and 1.5; S9 reducer tests → 1.2; S12 → 1.10; S1 config test → 2.5; the rest → 3.1–3.6 |
| §10 | 1.8, 2.6 |
| §11 | across all tasks, plus 3.8 and 4.3 |
| §12 | 1.1, 3.7 |

**Names used across tasks:** `SessionState`, `reduce`, `as_spool_line`, `fixture_spool`, `NdjsonTailer.lines`, `Store.subscribe`, `Diagnostics.record`, `SessionService.apply`, `present`, `pick_session`, `PromptTyper.type_reference`, `ReferenceService.submit`, `Reference.render`.
