# AGENTS.md - AI Agent Guide for ovui

This file gives AI coding agents the minimum context needed to work effectively in this repository. Use it as a starting map, then go to `skills/` for task-level implementation guidance.

## What This Repo Is

`ovui` is a Python UI framework, a library of ready-made app widgets, and a runnable reference application for building scene, viewport, and data tools. The repository ships:

- a Python-facing UI layer (`ovui`, imported in Python as `omni.ui` and `omni.ui_scene`)
- a library of composable app widgets (`ovui-widgets/` - stage browser, property inspector, content browser, viewport, composition view)
- data adapters that connect those widgets to OpenUSD or custom backends (`ovui-data-adapters/`)
- a screenshot-first inspector pipeline that lets people and AI coding agents drive the running UI through the same screenshot-action loop

Primary use case: building polished, consistent scene, viewport, and data tools on top of OpenUSD and ovrtx.

## Start Here

- Read `README.md` for top-level product context.
- Read `docs/architecture.html` (a TOC + iframe shell) and the per-section pages under `docs/architecture/section-01.html` ... `docs/architecture/section-11.html` for the architectural overview, the UI layer, the scene tools, ovui-widgets, adapters, the application, and the inspector pipeline.
- Read `skills/omniverse-ui-apis/SKILL.md`, `skills/omniverse-ui-widgets/SKILL.md`, `skills/omniverse-ui-styling/SKILL.md`, and `skills/omniverse-ui-inspector/SKILL.md` to understand the repo's agent-facing skill surfaces before starting task-level work.

## Repo Layout (High-Level)

- `ovui/` - Python UI framework source (the `omni.ui` and `omni.ui_scene` Python packages, C++ bindings, examples, headless mode, standalone runtime, markdown widget, and screenshots).
- `ovui-widgets/` - app widget library and the runnable reference application (`USD Viewer`), including stage browser, property inspector, content browser, viewport, composition view, common services, and the menu/file-open wiring.
- `ovui-data-adapters/` - OpenUSD-backed adapters (stage, property, transform, renderer) plus session authoring and livestream tap.
- `docs/architecture.html` and `docs/architecture/` - per-section architectural documentation (11 sections from project overview through the inspector pipeline) plus shared styles.
- `skills/` - Task-oriented agent skills (`SKILL.md` plus `references/` per skill).
- `README.md`, `CHANGELOG.md`, `LIVESTREAM.md`, `VERSION.md` - top-level product and process documentation.

## Common Workflows

### Run the reference application (USD Viewer)

The runnable application lives at `ovui-widgets/ovui_widgets/app/application.py` and is launched as a Python module:

```
python -m ovui_widgets.app
```

Headless mode (offscreen rendering) is available via `python -m ovui_widgets.app.headless`.

### Build atomic ovui UI

Use `omni.ui` primitives (windows, frames, stacks, fields, sliders, menus, value models, TreeView, scene overlays). See `skills/omniverse-ui-apis/SKILL.md` and its references for layout, model-view, inputs/windows/viewport, and concrete recipes.

### Compose a disposable ovui-widgets app

Create a temporary standalone application that reuses the existing widgets without re-implementing the viewport, stage browser, property inspector, or renderer. See `skills/omniverse-ui-widgets/SKILL.md` and its references; the disposable trial source must live outside the repo (under `$TRIAL_ROOT`).

### Drive a running app through an AI coding agent

The repository ships a Claude Code-compatible inspector skill that exposes a localhost FastAPI server and a CLI (`ovui-inspect`) for screenshot, mouse, keyboard, and frame-loop drain operations. See `skills/omniverse-ui-inspector/SKILL.md` and its references for the API endpoints, the coordinate system, and the strict screenshot-action-screenshot QA loop.

## Use Skills for Task-Specific Work

When a request maps to a known ovui workflow, go directly to the relevant skill in `skills/`:

- Atomic ovui construction (windows, layouts, TreeView, model-view, inputs, menus, viewport-like ovrtx panels, styling, strict UI validation) -> `skills/omniverse-ui-apis/SKILL.md`
  - `skills/omniverse-ui-apis/references/layout.md` - lengths, containers, clipping, scroll, nested layout, docking layout patterns.
  - `skills/omniverse-ui-apis/references/model-view-tree.md` - value models, item models, delegates, TreeView behavior, stage hierarchy trees.
  - `skills/omniverse-ui-apis/references/inputs-windows-viewport.md` - controls, callbacks, menus, drag/drop, keyboard focus, window/docking behavior, ovrtx viewport shells, QA constraints.
  - `skills/omniverse-ui-apis/references/recipes.md` - concrete atomic recipes (docked tool window, stage hierarchy tree, viewport-like panel shell with ovrtx).
- Composing a disposable standalone ovui-widgets application (reusing the existing viewport, stage browser, property inspector, file open dialog, and selection bus, with real ovrtx rendering and screenshot-first QA) -> `skills/omniverse-ui-widgets/SKILL.md`
  - `skills/omniverse-ui-widgets/references/source-map.md` - exact imports and required calls for the existing ovui-widgets classes the trial must reuse.
  - `skills/omniverse-ui-widgets/references/runtime-environment.md` - portable shell environment (env vars, `PYTHONPATH`, USD fixture, `$PYTHON_BIN` check) and real-ovrtx fail-fast requirements.
  - `skills/omniverse-ui-widgets/references/app-skeleton.md` - the `TrialApp` class skeleton, the `run`/`run_async` initialization, ovuiinspect attach/drain, frame rendering.
  - `skills/omniverse-ui-widgets/references/usd-and-dataflow.md` - USD open and wiring recipe, standalone docking sequence, exercise configurations and CLI, plus selection and dataflow wiring across Stage, Viewport, and Property.
  - `skills/omniverse-ui-widgets/references/menu-and-qa.md` - menu bar with File > Open and the screenshot-first QA flow with `ovui-inspect`.
- Styling ovui or ovui-widgets surfaces (palettes, colour/float/icon constants, shades, style selectors, `style_type_name_override`, widget `name` variants, `ui.style.default`, style hierarchy, the centralised style module, and styling reviews) -> `skills/omniverse-ui-styling/SKILL.md`
  - `skills/omniverse-ui-styling/references/target-architecture.md` - the target style schema every surface must follow.
  - `skills/omniverse-ui-styling/references/style-mechanics.md` - selector grammar, cascading, stores, shades, `style_type_name_override`, `name`, and `ui.style.default`.
  - `skills/omniverse-ui-styling/references/naming-constants.md` - colour, float, URL, and icon constant naming rules and the recommended scheme.
  - `skills/omniverse-ui-styling/references/naming-selectors.md` - `style_type_name_override` and widget `name` naming rules and the recommended scheme.
  - `skills/omniverse-ui-styling/references/style-hierarchy.md` - the six levels of the style dictionary and the selector resolution order.
  - `skills/omniverse-ui-styling/references/centralized-style-module.md` - centralised style module layout and the design of `palette.py`, `constants.py`, and `urls.py`.
  - `skills/omniverse-ui-styling/references/global-styles-and-startup.md` - the `GLOBAL_STYLES` dictionary, the assignment to `ui.style.default`, and theme subscription on startup.
  - `skills/omniverse-ui-styling/references/developer-guide.md` - recipes for standard-looking and custom-looking surfaces, and for adding constants, selectors, or per-surface styles.
- Inspecting, screenshotting, or driving a running ovui/ovui-widgets application via the `ovui-inspect` FastAPI inspector -> `skills/omniverse-ui-inspector/SKILL.md`
  - `skills/omniverse-ui-inspector/references/api-endpoints.md` - inspector HTTP endpoints (`screenshot`, `move`, `click`, `drag`, `type`, `press`, `combo`, `wait`, `health`, `execute`).
  - `skills/omniverse-ui-inspector/references/coordinate-system.md` - the coordinate model used by inspector commands and screenshots.
  - `skills/omniverse-ui-inspector/ovuiinspect/` - the importable Python module that runs the inspector server inside the running app.
  - `skills/omniverse-ui-inspector/scripts/` - the `ovui-inspect` CLI entrypoint that issues commands against the server.

If multiple skills seem relevant for an end-to-end agent task that generates a tool and drives it, start with `skills/omniverse-ui-widgets/SKILL.md` for composition, layer in `skills/omniverse-ui-apis/SKILL.md` for atomic surfaces, use `skills/omniverse-ui-styling/SKILL.md` for styling decisions, and use `skills/omniverse-ui-inspector/SKILL.md` for the screenshot-action-screenshot QA loop.

## Agent Expectations

- Prefer small, targeted edits over broad refactors unless requested.
- Keep skills and architecture documents in sync with API behavior changes; if a workflow changes, update the relevant `SKILL.md` and its `references/` files.
- Do not introduce host-specific absolute paths in skills or architecture documents. Use environment variables (`$REPO`, `$TRIAL_ROOT`, `$EVIDENCE_ROOT`, `$OVRTX_ROOT`, `$USD_INSTALL`, `$PYTHON_BIN`, etc.) or repository-relative paths so the repo stays portable across hosts.
- Use the framework name `ovui` in prose. Keep `omni.ui` only where it names actual Python code: literal `import omni.ui` statements, dotted module paths (`omni.ui.scene`, `omni.ui.testing`, `omni.ui._ui`, `omni.ui_scene`), and import-as patterns (`omni.ui.color as cl`, `omni.ui.constant as fl`).
- For user-like UI QA, follow the strict screenshot-first workflow in `skills/omniverse-ui-inspector/SKILL.md`: every user action is preceded and followed by a screenshot, interactions use mouse/keyboard through `ovui-inspect`, and programmatic shortcuts must not replace real UI interaction.
- Preserve licensing headers and proprietary notices where present.

## Notes

- The runnable application title is `USD Viewer`. Internal module names (`ovui-widgets`, `ovui`, `ovui_data_adapters`) and Python import paths (`omni.ui`, `omni.ui_scene`) are separate from the user-visible application title.
- Disposable trial applications produced by an agent must live outside the repository tree. Use `$TRIAL_ROOT` for the scratch directory; the trial source is not part of the repo deliverable.
- The repository is organized so a project can take the amount that matches the tool's goal: run the full application, use one or more app widgets, replace a data adapter, build directly from the Python UI layer, or let an AI coding agent generate the next tool by reusing ovui-widgets through the skills above.
