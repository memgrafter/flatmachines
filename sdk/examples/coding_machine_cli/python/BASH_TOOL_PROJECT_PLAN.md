# Project Plan: Generalize the bash tool in tool_use_cli

## 1) Overview

Goal: make the current `tool_bash` more general, robust, and secure so it can run commands in varied environments (sourced venvs, different shells, login/interactive modes, env overrides, exec-style commands, optional PTY) while preserving truncation/tempfile behavior.

Deliverable: an updated `tool_bash` implementation, unit/integration tests, examples, docs, and CI that validate behavior and preserve backwards compatibility by default.

## 2) Scope

In scope:
- Add features: shell choice, login/interactive flags, file sourcing, env overrides, list-style (no shell) execution, stdin support, cwd override, longer timeouts.
- Keep existing output truncation and tempfile behavior.
- Add unit + integration tests, examples in README, and API doc.

Out of scope:
- Full PTY/TTY emulation (optional extension).
- Remote execution or sandboxing beyond environment controls.

## 3) Requirements

Functional:
- Accept args: `command` (str | list), `shell` (str), `login` (bool), `interactive` (bool), `source` (list[str]), `env` (dict), `timeout` (int), `cwd` (path), `input` (str).
- For str command: run via chosen shell with optional flags and source files before command.
- For list command: run without shell (safer).
- Merge env overrides into `os.environ` for the subprocess.
- Return stdout+stderr, include exit code info if non-zero, and set `is_error` accordingly.
- Preserve truncation (tail) and write full output to tempfile when truncated.

Non-functional:
- Secure defaults: do not source files unless explicitly requested.
- Clear error messages on timeout/exception.
- Backwards compatible default behavior (same semantics when only command+timeout given).

## 4) Design / API

Tool args (dictionary):
- `command`: str | list — command string (runs under shell) or list of args (exec).
- `shell`: str — path to shell executable (default `bash`).
- `login`: bool — pass `-l` to shell (default `False`).
- `interactive`: bool — pass `-i` to shell (default `False`).
- `source`: list[str] — files to `source` before executing (paths resolved relative to cwd).
- `env`: dict — environment variables to set/override for subprocess.
- `timeout`: int — seconds (default `30`).
- `cwd`: str — working directory (default `working_dir`).
- `input`: str — stdin text for subprocess.

Behavior:
- When `command` is list: `subprocess.run(list(...), env=merged_env, cwd=cwd, input=input, timeout=timeout)`.
- When `command` is str: construct a script that sources each `source` file (if any) then runs the `command` (joined with `&&`), run shell with flags `[shell, -l? -i?, -c, script]`.
- Resolve source paths: expanduser and if not absolute, join with cwd.
- Use same truncation/tempfile code path as current `tool_bash`.
- Return `ToolResult(content=output, is_error=(returncode!=0))` with same message format.

## 5) Implementation tasks (suggested order)

- T1: Add design note & test plan to README/docs.
- T2: Implement new `tool_bash` function in `src/tool_use_cli/tools.py`:
  - Add imports: `shlex`, `Path` (if not present).
  - Implement env merging and path resolution for sources.
  - Handle command types (list vs str).
  - Reuse existing truncation/_truncate_tail and tempfile handling.
  - Keep original error messages for timeouts and exceptions.
- T3: Update `CLIToolProvider` docs string to list new args.
- T4: Add unit tests:
  - Test exec-list command (`["echo", "hi"]`) returns `hi`.
  - Test str command behavior with shell features.
  - Test `source` behavior: create temp script that exports a var and verify it is visible after sourcing.
  - Test `env` override behavior (`env={"FOO":"baz"}`).
  - Test `cwd` override (run `ls` in temp dir).
  - Test timeout behavior.
  - Test truncation: generate large output to verify tempfile created and message contains path.
- T5: Add integration examples in README:
  - Example: run.sh under repo venv:
    `{"command":"./run.sh --local", "source":[".venv/bin/activate"], "cwd":"/path/to/repo", "timeout":300}`
  - Example: exec-style git command.
- T6: Add CI jobs:
  - Run unit tests under pytest in project’s test matrix.
  - Linting (black/flake8/isort) and optional type check (mypy).
- T7: Security review & docs:
  - Add note in README about risk of sourcing arbitrary files and recommended safeguards.

## 6) Testing & QA

- Unit tests for each argument and failure mode.
- Integration tests:
  - Use a temporary project directory to simulate typical scenarios (repo with `.venv` and `run.sh` using `uv`).
  - Confirm `run.sh` can be executed using `source` + `cwd` combination.
- Manual tests:
  - Test `run.sh` scenario that initially failed from agent: verify it works when sourcing `.venv/activate`.

Acceptance criteria:
- All unit tests pass.
- Integration tests demonstrate `run.sh` can succeed in a fresh subprocess when using `source` + `cwd`.
- Backwards-compatibility: previous simple calls (`{"command": "ls -la"}`) behave the same as before.
- README updated with examples and warnings.

## 7) Timeline & estimates (single dev)

- Design + planning: 0.5 day
- Implementation (T2,T3): 1 day
- Unit tests (T4): 0.5–1 day
- Integration tests + examples (T5): 0.5 day
- CI + linting (T6): 0.5 day
- Docs + security notes (T7): 0.25 day
- Buffer + review: 0.25–0.5 day

Total: ~4 working days (can be compressed to 2–3 days for a small change if tests are light).

## 8) Risks & mitigations

- Risk: Sourcing user files opens security risk. Mitigation: default to not sourcing; require explicit `source` list via tool args and warn in docs.
- Risk: Shell startup behavior varies across environments (login vs interactive). Mitigation: expose `login`/`interactive` flags and include examples; avoid trying to implicitly reproduce an interactive shell.
- Risk: `run.sh` relies on non-portable helpers (`uv`). Mitigation: show alternative in README: call venv python/pip directly or edit `run.sh` to remove `uv`.
- Risk: behavior differences between shells (bash vs zsh). Mitigation: allow selecting shell path; document differences.

## 9) Git / release plan

- Branch: `feature/generalize-bash-tool`
- PR checklist:
  - Implementation compiles / lints
  - Unit tests pass locally
  - Integration tests added
  - README updated with examples
  - Security notes added
- Merge and release patch with changelog entry.

## 10) Acceptance criteria (summary)

- New args supported and documented.
- Existing default behavior preserved.
- Tests demonstrate venv activation + run.sh scenario works via `source` + `cwd`.
- README contains examples and security warning.

## 11) Optional extensions (post-MVP)

- Add PTY support (pexpect) for truly interactive commands.
- Provide convenience wrapper to run common patterns (activate `.venv` then run script).
- Add higher-level helper functions in hooks to automatically detect `.venv` and set `source` for `run.sh` runs (opt-in).
- Add telemetry/logging for long-running commands.

---

*Generated by assistant on request.*
