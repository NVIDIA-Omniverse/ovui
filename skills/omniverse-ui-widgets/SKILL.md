---
name: omniverse-ui-widgets
description: |
  Use this skill when a user asks to create or validate a disposable
  standalone ovui/ovui-widgets application from the existing widget set. The
  application source should live outside the repo unless the user explicitly
  asks to productize it. The skill gives exact imports, runtime environment,
  ovrtx proof requirements, widget wiring, menu/file-open wiring, and
  screenshot-first QA expectations. Do not use this skill for raw `omni.ui`
  atomic widget construction; use the omniverse-ui-apis skill instead.
author: "NVIDIA ovui Team <ovui-team@nvidia.com>"
license: "LicenseRef-NVIDIA"
metadata:
  python-distribution: ovui-widgets-app
  version: "0.2.0"
---

# ovui-widgets

This skill is an operational recipe for creating temporary standalone
ovui-widgets applications that reuse the repo's existing widgets. The application
is disposable; the skill quality is the deliverable. It is for composite
ovui-widgets apps, not raw atomic `omni.ui` construction.

## Non-Negotiable Scope

Create only an application layer. Do not implement a new viewport, Stage
Browser, Property Inspector, renderer, USD adapter, file picker, or selection
system.

Disposable trial code belongs outside the repo. Pick any writable scratch
root the host allows and point `$TRIAL_ROOT` at it before running the recipe;
the trial source lives there, for example:

```text
$TRIAL_ROOT/
  trial_app.py
  evidence/
  logs/
```

Do not add `ovui-widgets/ovui_widgets/apps/**`, do not add package discovery for a
trial app, do not add app-step tests, and do not add shape flags to
`python -m ovui_widgets.app`. These are rejected shortcuts:

- `python -m ovui_widgets.app --viewport-only`
- `python -m ovui_widgets.app --viewport-stage`
- `python -m ovui_widgets.app --viewport-stage-property`
- `ApplicationComposition.viewport_only()`
- `ApplicationComposition.viewport_stage()`
- `ApplicationComposition.viewport_stage_property()`

## Required Workflow

1. Read `references/source-map.md` for the exact imports and the public API
   surface (`ViewportWidget`, `StageWindow`, `PropertyWindow`, `SelectionBus`,
   service singletons, USD adapters, file importer) before importing
   anything. Reuse these classes; do not recreate them.
2. Read `references/runtime-environment.md` for the portable shell-env recipe
   (env vars, PYTHONPATH composition, USD fixture, `$PYTHON_BIN` check) and
   the real-ovrtx requirements (renderer construction order, fail-fast
   helper, rejected log strings, proof markers).
3. Read `references/app-skeleton.md` for the minimal `TrialApp` class
   skeleton and the `run` / `run_async` initialization pattern, including
   `write_split_ini()` placement, optional `ovuiinspect` attach and drain,
   and the frame rendering helper. Implement the app at
   `$TRIAL_ROOT/trial_app.py`.
4. Read `references/usd-and-dataflow.md` for the USD open and wiring recipe
   (`_wire_open_stage`, standalone docking sequence, the cumulative exercise
   configurations and CLI entrypoint) and for the full selection and
   dataflow wiring across Stage, Viewport, and Property surfaces
   (Stage -> Viewport -> Property, Viewport pick -> Stage -> Property,
   Viewport manipulation -> Property -> renderer, Property edit -> Viewport).
5. Read `references/menu-and-qa.md` for the Exercise 4 menu bar and File >
   Open dialog wiring, and for the screenshot-first QA flow with
   `ovui-inspect` (launch command, polling, per-exercise proof
   requirements).
6. Implement the disposable app under `$TRIAL_ROOT`, never under the repo.
   Compose only the surfaces the exercise calls for; do not invent new
   composites.
7. If this skill lacks information needed to complete the user's task,
   stop immediately and ask for the skill to be updated. Do not guess
   missing ovui-widgets behavior.
8. For user-like UI QA, follow the strict screenshot-first workflow. Every
   user action must be preceded and followed by screenshots, interactions
   must use mouse/keyboard only via `ovui-inspect`, and programmatic
   shortcuts must not replace real UI interaction.

## Reference Files

- `references/source-map.md` - exact imports and required calls for the
  existing ovui-widgets classes the trial must reuse.
- `references/runtime-environment.md` - portable shell environment
  (`$REPO`, `$USD_INSTALL`, `$OVRTX_ROOT`, `$TRIAL_ROOT`, `$EVIDENCE_ROOT`,
  `$USD_FIXTURE`, `$PYTHON_BIN`, `$PYTHONPATH`, `$LD_LIBRARY_PATH`) and the
  real-ovrtx fail-fast requirements.
- `references/app-skeleton.md` - the `TrialApp` class skeleton, the
  `run` / `run_async` initialization pattern, ovuiinspect attach/drain, and
  the frame rendering helper.
- `references/usd-and-dataflow.md` - USD open and wiring recipe, standalone
  docking sequence, exercise configurations and CLI, plus selection and
  dataflow wiring across Stage, Viewport, and Property surfaces.
- `references/menu-and-qa.md` - Exercise 4 menu bar with File > Open and
  the screenshot-first QA flow with `ovui-inspect`.

## Cumulative Exercises

The app should run one of these cumulative configurations (full code lives in
`references/usd-and-dataflow.md`):

- Exercise 1: `include_stage=False, include_property=False, include_menu=False`
- Exercise 2: `include_stage=True, include_property=False, include_menu=False`
- Exercise 3: `include_stage=True, include_property=True, include_menu=False`
- Exercise 4: `include_stage=True, include_property=True, include_menu=True`

Each exercise must end with a proof screenshot driven by `ovui-inspect`. The
per-exercise proof requirements are in `references/menu-and-qa.md`.

## Fail-Fast Checklist

Stop and fix the skill or environment before claiming success if any item is
false:

- The disposable app source lives under `$TRIAL_ROOT`, not under the repo.
- No `ovui-widgets/ovui_widgets/apps/**` package was created.
- No full `ovui_widgets.app` launcher shape flags were added.
- `ViewportWidget` is imported and reused; no new viewport implementation
  exists.
- `StageWindow`, `PropertyWindow`, and `SelectionBus` are reused when needed.
- The renderer is `OvRtxRendererAdapter`; `MockRendererAdapter` is not used.
- `OVUI_WIDGETS_REQUIRE_OVRTX=1` is set and fallback/mock/black screenshots abort.
- `simple_scene.usda` is open, and `/World/Cube` or another stable prim is
  selected in every final exercise screenshot.
- Selection works Stage -> viewport -> Property and viewport -> Stage ->
  Property.
- Viewport manipulation updates Property.
- Property editing updates the viewport.
- File > Open uses `FileImporterHelper` or `FilePickerDialog` and routes
  accepted paths through the same `open_usd(path)` path.
- Screenshots exist under `$EVIDENCE_ROOT` for exercises 1 through 4.
- The final repo status is not polluted by disposable app files.

## When The Skill Is Insufficient

If the user's task needs ovui-widgets behavior not covered by this skill or its
references, stop and ask for the skill to be updated. Do not guess API names,
do not pattern-match against unrelated repos. Concrete examples of gaps that
justify pausing:

- The exercise needs a widget the source map does not list (for example, a
  layer panel or a content browser composition the source map does not name).
- The renderer behavior beyond `OvRtxRendererAdapter` (custom passes, alternate
  AOVs) is required.
- The USD adapter behavior beyond `UsdStageAdapter`, `UsdPropertyAdapter`,
  `UsdTransformAdapter` is required.
- The QA loop needs an `ovui-inspect` capability the inspector skill does not
  document.

Report the gap to the user, then ask. The skill is meant to be extended
over time.
