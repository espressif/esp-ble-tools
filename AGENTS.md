# AGENTS.md

Agent guidance for ESP BLE Tools — a collection of host-side utilities
(`github.com/espressif/esp-ble-tools`) that support ESP BLE development,
debugging, validation, and log capture. Tools live under `components/`, each
self-contained with its own source, docs, tests, and packaging scripts.

This repository is public. Treat every committed file, commit message, and PR
description as publishable text: nothing that is only meant for internal use
belongs in them.

## Components

| Component | Path | Purpose |
| --- | --- | --- |
| BLE Log Console | `components/ble_log_console/` | Python/Textual terminal UI that receives, displays, and saves ESP BLE log data over UART, SPI Bridge, or USB Output. |

Add a new tool as its own `components/<tool>/` directory with its own
`pyproject.toml`, docs, tests, and packaging.

## BLE Log Console

Paths in this section are relative to `components/ble_log_console/`, and the
commands below run from there, unless stated otherwise.

### Commands

```bash
./install.sh            # one-time: install uv and sync deps (uv sync --all-extras)
./run.sh                # run the TUI; forwards every argument to console.py
uv run pytest           # full test suite
uv run pytest tests/test_stats.py -v   # targeted selection
./build.sh              # build the standalone PyInstaller executable
```

Windows equivalents are `install.bat`, `run.bat`, and `build.bat`. The direct
entry point is `console.py`, a click CLI (`uv run python console.py --help`)
with the `ports` and `ls` subcommands.

### Verification

A Python change is not finished until the relevant tests and Ruff pass. From
`components/ble_log_console/` run `uv run pytest` (narrowest relevant selection
first is fine), then run Ruff from the repository root over the whole component.
There is no CI lint gate, so this local run is the whole gate:

```bash
uv tool run ruff@0.16.9 format --check components/ble_log_console
uv tool run ruff@0.16.9 check components/ble_log_console
```

Use `format` without `--check` only when you intend to reformat. Config is root
`ruff.toml`: 120 columns, double quotes, `py311`, Markdown excluded, ruff
defaults plus `INP`. It deliberately covers the component's root scripts and
`docs/**`, so do not narrow the paths. Ruff output drifts between releases — use
`0.16.9` when re-formatting. Report any check you did not run or that failed.

### Architecture

- `console.py` parses arguments and starts `src/app.py` `BLELogApp`, a Textual
  `App`. Widgets and screens live in `src/frontend/`.
- `src/backend/models.py` is the primary home for shared domain records
  (dataclasses, enums) and the `textual.message.Message` types exchanged with
  the frontend. Worker and pipeline contracts live with their owners instead —
  `WriterConfig` in `src/backend/io/`, `CapturePipelineResult` in
  `src/backend/pipeline/controller.py`, `AggregatorSnapshot` in
  `src/backend/analysis/` — and the frontend imports them directly.
- Capture runs as separate processes. `src/backend/pipeline/controller.py`
  spawns a reader/writer process (`src/backend/io/`) and an aggregator process
  (`src/backend/analysis/`), wired by queues. The device handle is opened and
  owned by the I/O process; only config and serializable data cross the process
  boundary — never a `TransportReader` or an open handle. The parent does build
  one unopened reader to read `bitrate_config` (`CapturePipeline.start`), so that
  call is expected, not a violation.
- Transports use a provider registry: `src/backend/support/transport/` holds one
  module per backend (`uart`, `spi_usb_bridge`, `usb_output`), each exposing a
  `PROVIDER` (`TransportProvider`) and a `TransportReader` for the byte stream.
- Frame decoding is delegated to `ble_log_frame_decoder` (`esp-blfd==0.4.0`);
  `src/backend/analysis/parser.py` maps console checksum modes onto the decoder.
  Do not re-implement frame parsing.
- Recording statistics live in `src/backend/support/stats/`; the final quality
  verdict is built by `build_capture_report()` in
  `src/frontend/capture_report.py`.

### Data-safety invariants

Keep these when touching the pipeline, the writer, or the report:

- Raw preservation is authoritative. A block reaches the parser only after the
  writer accepted it, so the recording survives a lagging parser. A full parser
  queue may drop parse input, but the gap must be counted and surfaced — never
  silently ignored.
- Shutdown finalization, save-failure reporting, and incomplete-parse reporting
  are part of the contract. Cover a change to them with a regression test.

### Testing

- pytest with `testpaths = ["tests"]`. `conftest.py` prepends the component root
  to `sys.path`, so tests import `src.*` and reuse `tests/helpers.py`
  (`build_frame`, `snapshot_payload`, `xor_checksum`).
- Gherkin BDD is required for user-visible behavior, not optional coverage:
  `tests/features/*.feature` is Chinese (`# language: zh-CN`), bound in
  `tests/test_*_bdd.py`. Add or update a scenario when user-visible behavior
  changes, and update its binding in the same change only when a new step or
  observation path is needed. Never weaken a scenario because unit tests already
  cover it. A binding observes behavior through the public path; it does not
  recompute the expected value from the implementation.
- Tests stub transports and ports and never open a real device. PTY-based tests
  use `pytest.importorskip("pty")` and are POSIX-only.

### Hardware and devices

Unless the user explicitly authorizes it, do not open a physical serial or USB
port, reset or flash a device, run the baud-rate probe
(`docs/skills/ble-log-intake/scripts/probe_uart_baudrates.py`), or change system
permissions — `console.py` can install a udev rule and needs root to do it.
Opening a port can reset a board through DTR/RTS. Verify with stubs, recorded
captures, and PTY ports; a PTY is virtual and is the intended substitute.

### Conventions

- New or modified Python files start with the two-line SPDX header
  (`SPDX-FileCopyrightText: 2026 Espressif Systems (Shanghai) CO LTD` /
  `SPDX-License-Identifier: Apache-2.0`). Three tracked test modules lack it
  today — `test_build_exe.py`, `test_capture_lifecycle.py`,
  `test_capture_report.py`; add the header when you touch them, but do not run a
  repo-wide backfill as an unrelated task.
- Write new or modified Python code in English — comments, docstrings, log
  messages, identifiers, and CLI output. Customer-facing text belongs in
  `src/i18n.py` (`tr()`); the catalog and Chinese BDD step strings are the
  deliberate exceptions. Existing inline literals (for example in
  `src/frontend/capture_report.py`) are known debt — migrate them when you touch
  that code, not in an unrelated change.
- Commit messages follow `type(scope): statement` — type is one of `feat`,
  `fix`, `docs`, `refactor`, `build`, `test`, `chore`, `release`; scope is
  `ble_log_console` for console changes; the statement is a lowercase imperative
  clause.
- `CONTEXT.md` fixes project vocabulary (e.g. Recording, not Capture). Follow it
  in names, docs, and UI text.

### Packaging and releases

- `build.sh` / `build.bat` run `build_exe.py`, which packages `console.py` with
  PyInstaller. It depends on the `ble_log_frame_decoder._native` hidden import
  and the entry point's `multiprocessing.freeze_support()`; keep both when
  changing dependencies or the entry point.
- After a successful build, `build_exe.py` writes `VERSION` and syncs
  `pyproject.toml`, both READMEs, and both User Guides to the built version
  (`--bump-patch` / `--version`). Treat those as one version set and do not edit
  the version by hand.
- Tagging, releasing, and uploading artifacts need explicit user authorization.

### Documentation

- `README.md` is English canonical with a `README_CN.md` mirror. Guides live in
  `docs/`: `Config-Guide-{EN,CN}.md` and `Console-User-Guide-{EN,CN}.md`.
  `docs/skills/ble-log-intake/` is the shipped customer intake skill.
- Update maintained docs in place; keep the language versions in sync when
  behavior changes. Do not add dated plans or ADR files.

## Boundaries

- Keep root-level agent instructions current; put tool-specific detail in the
  component it belongs to instead of duplicating it here.
- Do not add repository-local agent settings, hooks, or plugins. `AGENTS.md` is
  the single source of agent instructions.
- Never commit, amend, rebase, push, or open a pull request unless the user
  explicitly asks.
- Worktrees share `.git/hooks`, `.git/config`, and `git stash`: do not use
  `git stash`, avoid `git config` writes, and clean up with `git worktree remove`
  rather than `rm -rf`.
- Do not read, print, modify, or commit secrets or machine-local files unless the
  user explicitly asks.
