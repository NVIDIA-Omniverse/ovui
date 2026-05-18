---
name: omniverse-ui-inspector
version: "0.1.0"
description: |
  Use this skill when the user asks to inspect, screenshot, automate, click,
  type into, or drive a running ovui/ovwidgets application through the
  ovui-inspect FastAPI inspector. The skill provides an importable
  `ovuiinspect` module, an `ovui-inspect` CLI, and a screenshot-first
  mouse/keyboard workflow for controlling ovui apps launched with PYTHONPATH.
author: "NVIDIA ovui Team <ovui-team@nvidia.com>"
license: "LicenseRef-NVIDIA"
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# ovui Inspector

Drive standalone ovui applications through the `ovui-inspect` FastAPI server.

## Quick Start

The tracked skill root in this repository is `skills/omniverse-ui-inspector`. Refer to
it from any clone with the repo-relative path; do not bake in machine-specific
absolute paths.

Launch the app with the skill root on `PYTHONPATH`. Set `OVUI_REPO` (or any
equivalent variable) to the local checkout of the ovui repository:

```bash
PYTHONPATH="${OVUI_REPO}/skills/omniverse-ui-inspector:${PYTHONPATH:-}" \
  python -m ovwidgets.app.headless --width 1280 --height 720
```

For a windowed app, use:

```bash
PYTHONPATH="${OVUI_REPO}/skills/omniverse-ui-inspector:${PYTHONPATH:-}" \
  python -m ovwidgets.app
```

The app imports `ovuiinspect` during startup. Importing the module starts a
localhost FastAPI server in a background thread and the app drains inspector
input actions on the ovui frame loop.

When using Codex or another command runner, keep the app command alive as a
managed long-running foreground session, or launch it with an explicit
detached-process wrapper that records the exact PID. Do not run the app through
a command invocation that has a default timeout and then continue sending
inspector commands after that invocation exits. If the app process is killed by
the runner, follow-up keyboard commands will fail with connection refused even
though the key is supported.

Defaults:

- Host: `127.0.0.1`
- Port: `9910`
- Override with `OVUIINSPECT_HOST` and `OVUIINSPECT_PORT`
- Python execution endpoint disabled by default; enable with `OVUIINSPECT_ENABLE_EXECUTE=1`

## Interface Priority

1. `skills/omniverse-ui-inspector/scripts/ovui-inspect <command>` from the repo root is the preferred CLI.
2. `python skills/omniverse-ui-inspector/scripts/ovui-inspect.py <command>` is equivalent.
3. Raw HTTP against `http://127.0.0.1:9910` is for debugging.

Always wait for health after launch. Use the repo-relative path from the
current working directory or prefix it with the local repo root variable:

```bash
skills/omniverse-ui-inspector/scripts/ovui-inspect wait --timeout 60
skills/omniverse-ui-inspector/scripts/ovui-inspect health
```

For automated QA, also record the listening PID before the first UI action and
check it again if a command reports connection refused:

```bash
ss -tlnp sport = :9910
ps -p <exact-pid> -o pid,stat,cmd
```

## Screenshot-First Workflow

Use the same loop as Kit Inspector, corrected for ovui:

1. Take a screenshot.
2. Inspect the screenshot and identify the target coordinate.
3. Perform one mouse or keyboard action.
4. Take another screenshot and verify what changed.
5. Repeat.

Do not guess coordinates. Do not batch a full workflow between screenshots.

```bash
scripts/ovui-inspect screenshot --out proof/01_before.png
scripts/ovui-inspect move 240 32
scripts/ovui-inspect screenshot --out proof/02_hover.png
scripts/ovui-inspect click 240 32
scripts/ovui-inspect screenshot --out proof/03_after_click.png
```

## Command Reference

Core commands:

- `health` / `status`: check server, app attachment, queue depth, and execute setting.
- `wait --timeout 60`: wait until `/health` responds.
- `screenshot --out file.png`: capture the full ovui framebuffer.
- `move X Y`: move the injected ovui cursor.
- `click X Y [--button left|right|middle] [--double]`: click in screenshot coordinates.
- `drag X1 Y1 X2 Y2 [--button left|right|middle] [--duration SEC] [--steps N]`: drag over frame-stepped positions. `--duration` is converted to movement samples by the server; `--steps` is the exact sample count and wins when both are provided.
- `scroll up|down|left|right [--amount N] [--x X --y Y]`: scroll at the current or specified position.
- `type "text"`: send text input to the focused widget.
- `press KEY [--modifiers ctrl,shift]`: send Enter, Escape, Tab, arrows, Delete, letters, digits, or F-keys.
- `combo "CTRL+A"`: convenience wrapper around key press with modifiers.
- `execute "code"`: run Python on the ovui frame loop only when `OVUIINSPECT_ENABLE_EXECUTE=1`.
- `shutdown`: request `Application.request_exit()`.

Read `references/api-endpoints.md` for raw HTTP paths and payloads.

CLI commands exit `0` only when the HTTP request succeeds and the inspector
response does not report `success: false`. HTTP errors, validation failures,
disabled execute, timeouts, and connection failures exit nonzero while still
printing the JSON error payload.

## Operational Rules

- Bind to localhost unless the user explicitly asks for a remote bind.
- Prefer mouse and keyboard commands over `/execute`; use `/execute` only for setup tasks that cannot reasonably be done through the visible UI.
- If `/execute` is required, relaunch the app with `OVUIINSPECT_ENABLE_EXECUTE=1` and keep the code snippet small and auditable.
- If FastAPI or uvicorn is missing, `ovuiinspect` logs the startup error and leaves the ovui app running without inspector endpoints.
- If a command times out, take `status`, inspect the app log, then retry a smaller single action.

## Known Limits

- The first version covers full-application screenshots, mouse input, keyboard input, optional Python execution, and clean shutdown.
- It does not expose widget-tree inspection, named-window capture, menu-path clicking, dialog helpers, logs, or streaming execution yet.
- ovui input is injected through ovui's in-process APIs, not OS-level tools. This is correct for app UI QA, but native OS dialogs may need a different method.
- `combo` sends modifier key events through the same key-injection path as
  `press`. Visible shortcut effects still depend on the target widget's real
  keyboard focus. In the Stage filter, the headless remote text fallback appends
  printable text directly to the filter model, so do not use Ctrl+A plus `type`
  as proof that selected text replacement works there.
