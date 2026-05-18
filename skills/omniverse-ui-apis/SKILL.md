---
name: omniverse-ui-apis
description: Use when creating, modifying, inspecting, or reasoning about ovui UI from low-level atomic ovui widgets, including layout, Pixel/Percent/Fraction sizing, model-view widgets, TreeView/stage hierarchy trees, inputs, menus, windows, docking, viewport-like ovrtx panels, styling, or strict UI validation. Use when an agent must rebuild Stage-Browser-like, Property-Inspector-like, or Viewport-like UI from primitives without reusing high-level composite widgets. Do not use for ovwidgets composite-widget application work; use the omniverse-ui-widgets skill instead.
author: "NVIDIA ovui Team <ovui-team@nvidia.com>"
license: "LicenseRef-NVIDIA"
---

# Ovui Atomic UI

Use this skill for raw or atomic ovui UI work. The default mode is atomic construction: build the UI from `ovui` primitives, value models, item models, delegates, windows, dock spaces, image providers, and scene/renderer embedding points. Do not use this skill for ovwidgets composite-widget application work; use `skills/omniverse-ui-widgets/SKILL.md` instead. Do not reuse high-level composite widgets such as `StageWidget`, `StageWindow`, `ViewportWidget`, `PropertyWindow`, `PropertyWidget` subclasses, `LayerWindow`, `LayersTree`, `ContentBrowserWindow`, or `ManagedWindow` unless the user explicitly allows composites. You may inspect those composites as examples of patterns to recreate, but the agent must reimplement equivalent behavior from atomic widgets.

## Required Workflow

1. Identify the surface: layout/window, TreeView/model-view, inputs/menus, viewport/ovrtx, styling, or validation.
2. Read the relevant bundled reference before implementing:
   - `references/layout.md` for lengths, containers, clipping, scroll, nested layout, and docking layout patterns.
   - `references/model-view-tree.md` for value models, item models, delegates, TreeView behavior, and stage hierarchy trees.
   - `references/inputs-windows-viewport.md` for controls, callbacks, menus, drag/drop, keyboard focus, window/docking behavior, ovrtx viewport shells, and QA constraints.
   - `references/recipes.md` for concrete atomic recipes: docked tool window, stage hierarchy tree, and viewport-like panel shell.
3. Search the active repo for current local usage before relying on memory when the API surface may have changed. Prefer real patterns from the local ovui repository and any companion ovrtx checkout the user points at; do not rely on hard-coded absolute paths.
4. Implement with low-level widgets first. Allowed building blocks include:
   - Windows/layout: `ui.Window`, `ui.DockSpace`, `ui.Workspace`, `ui.Frame`, `ui.CollapsableFrame`, `ui.CanvasFrame`, `ui.ScrollingFrame`, `ui.HStack`, `ui.VStack`, `ui.ZStack`, `ui.HGrid`, `ui.VGrid`, `ui.Placer`, `ui.Spacer`, `ui.MenuBar`, `ui.ToolBar`.
   - Drawables / labels: `ui.Rectangle`, `ui.Label`, `ui.Image`, `ui.ImageWithProvider`, `ui.Line`, `ui.Circle`, `ui.Ellipse`, `ui.Triangle`, `ui.FreeShape`, `ui.Plot`, `ui.MarkdownWidget`, `ui.Separator`.
   - Inputs: `ui.Button`, `ui.InvisibleButton`, `ui.ToolButton`, `ui.CheckBox`, `ui.RadioButton`, `ui.RadioCollection`, `ui.StringField`, `ui.StringFieldLimited`, `ui.IntField`, `ui.FloatField`, `ui.IntSlider`, `ui.UIntSlider`, `ui.FloatSlider`, `ui.IntDrag`, `ui.UIntDrag`, `ui.FloatDrag`, `ui.ProgressBar`, `ui.ComboBox`, `ui.ColorWidget`, `ui.MultiFloatField`, `ui.MultiIntField`, `ui.MultiStringField`, `ui.MultiFloatDragField`, `ui.MultiIntDragField`.
   - Item / value model: `ui.AbstractValueModel`, `ui.SimpleStringModel`, `ui.SimpleBoolModel`, `ui.SimpleFloatModel`, `ui.SimpleIntModel`, `ui.SimpleListModel`, `ui.AbstractItem`, `ui.AbstractItemModel`, `ui.AbstractItemDelegate`, `ui.TreeView`.
   - Menus: `ui.Menu`, `ui.MenuItem`.
   - Imaging: `ui.ByteImageProvider`, `ui.RasterImageProvider`.
   - Scene overlays: `omni.ui_scene.scene.SceneView`, `sc.Screen`, gestures.
   - Renderer integration: `ovrtx.Renderer` (and adapters when the user permits one).
5. Keep item objects and value model objects stable. TreeView selection, expansion, column rendering, and cached row widgets depend heavily on object identity.
6. For temporary learning or validation prototypes, create them outside the repo, or remove them before finishing. The final repository change must only contain the requested durable artifact.
7. If this skill lacks information needed to complete the user's task, stop immediately and ask for the skill to be updated. Do not guess missing ovui behavior.
8. For user-like UI QA, follow the strict screenshot-first workflow. Every user action must be preceded and followed by screenshots, interactions must use mouse/keyboard only, and programmatic shortcuts must not replace real UI interaction.

## Atomic Surface Map

- Layout: `Length`, `Pixel`, `Percent`, `Fraction`, `Widget` sizing, `Frame`, `CollapsableFrame`, `ScrollingFrame`, `Stack` variants, `HGrid`/`VGrid`, `Placer`, `Spacer`, clipping (`horizontal_clipping`, `vertical_clipping`, `content_clipping`), content size, and computed geometry.
- Model-view: `AbstractValueModel`, simple value models, `AbstractItemModel`, `AbstractItemDelegate`, `TreeView`, `ComboBox`, `ColorWidget`, and multi-field widgets.
- TreeView: lazy row population, delegate branch/widget building, column widths, selection, expansion, drag/drop, filtering, lazy child loading, manual headers, and stage/layer hierarchy mapping.
- Inputs: buttons, invisible hit targets, tool buttons, check boxes, radio buttons, string/int/float fields, sliders, drags, combo boxes, color widgets, multi-component fields, menus, context menus, tooltips, keyboard focus, mouse callbacks, and drag/drop.
- Windows: `Window`, `DockSpace`, `Workspace`, `DockPreference`, `DockPosition`, `DockPolicy`, dock-id checks, tab strips, modal/non-dock flags, raster policy, window teardown, and layout persistence.
- Viewport-adjacent UI: `ByteImageProvider`, `ImageWithProvider` (with `IwpFillPolicy`), `omni.ui_scene.scene.SceneView`, `sc.Screen`/gestures, ovrtx renderer stepping (`step` + `RenderProductSetOutputs`), camera matrix sync, HUD overlays, toolbar controls, and renderer lifecycle.
- Styling: global `ui.style.default`, `style_type_name_override`, `name=...` state selectors (e.g. `"Stage.VisibilityIcon::hidden"`), `omni.ui.color as cl`, `omni.ui.constant as fl`, cached `RasterImageProvider` usage, and theme reapplication via `ui.set_shade(...)`.

## Non-Negotiable Pitfalls

- Raw numbers in width/height kwargs are pixels (`ui.Pixel(n)`), not fractions. Default sizing is `ui.Fraction(1)` on unset axes.
- `ui.Fraction` only divides remaining space along a stack's consecutive axis. On the simultaneous axis it behaves like fill against the available span.
- `ui.Percent` uses the current container's available span after spacing, not the whole window or stack length.
- TreeView expansion and selection are keyed by item object identity. Recreate items carelessly and expansion/selection will disappear. Keep a `path_cache: dict[str, AbstractItem]` and reuse items across rebuilds.
- A model structural update must call `_item_changed(item)` (or `_item_changed(None)` for full rebuild); a scalar value change must call `_value_changed()` on the value model. Forgetting these is the most common "the UI does not refresh" bug.
- Delegate-only visual state (selection chrome, rename badge, drop-target overlays) often needs `model._item_changed(item)` or `tree.dirty_widgets()` because value models are not involved.
- Popup `ui.Menu` objects must be retained by Python while shown. Store on `self` and clear when dismissed. Otherwise the popup can close immediately on garbage collection.
- `window.dock_in(target_handle, position, ratio=...)` needs real dock IDs from a rendered target. Create `ui.DockSpace(None)` first, build all panel windows, `await ui.next_frame()` at least once, then fetch handles via `ui.Workspace.get_window(title)` and dock.
- TreeView's built-in `header_visible=True` adds an unreachable ~22 px gap between header and first row. Build a manual header with the same `column_widths` list and keep `header_visible=False`.
- The standalone `ovui` TreeView also reserves a ~20 px strip at the top of its body. To hide it, nest `TreeView` inside `ui.Frame` (with clipping) and `ui.Placer(offset_y=-20, stable_size=True)`. This is the reference stage-widget pattern (`stage_widget.py:215-249`).
- Dynamic viewport windows should use `raster_policy=ui.RasterPolicy.NEVER` or explicit raster invalidation to avoid stale/frozen content.
- `ovrtx.Renderer()` must be constructed before the first `pxr.Usd.Stage.Open` in the same process, and `OVRTX_SKIP_USD_CHECK=1` must be set before `import ovrtx`. In environments where a user-site `pxr` from `usd-core` collides with ovrtx's bundled USD, launch with `PYTHONNOUSERSITE=1`, an isolated `PYTHONPATH` covering only the needed ovui and ovrtx checkouts, and a temporary numpy site if needed.
- `ByteImageProvider.set_bytes_data_from_gpu(ptr, [w, h])` requires the CUDA mapping to remain entered for the synchronous call. Always close the mapping immediately afterward.
- Never use high-level composite widgets (`StageWidget`, `StageWindow`, `ViewportWidget`, `PropertyWindow`, `PropertyWidget` subclasses, `LayerWindow`, `ManagedWindow`, etc.) to satisfy an "atomic widgets only" request unless the user explicitly changes that requirement. Reading them for patterns is allowed; importing them is not.

## When the skill is insufficient

If the user's task needs ovui behavior not covered by this skill or its references, **stop and ask Victor to update the skill**. Do not guess API names, do not pattern-match against unrelated repos. Concrete examples of gaps that justify pausing:

- The exercise needs a widget the skill does not list (e.g. a graph editor, undo/redo integration, or a non-trivial gesture).
- The viewport exercise needs ovrtx behavior beyond `step` + `LdrColor` + camera xform/intrinsics.
- The stage-widget exercise needs USD adapter behavior not covered by `ovui_data_adapters`.
- Styling needs theme tokens not exposed via `omni.ui.color`/`omni.ui.constant`.

Report the gap to the user, then ask. The skill is meant to be extended over time.

## Validation loops this skill must support

This skill will be exercised by two fresh-Codex sessions. Future sessions should treat the prompts below as expected validation traffic.

1. **Viewport prototype exercise.** A fresh agent will be asked to build a temporary viewport-like panel (image provider + scene overlay + toolbar + HUD + ovrtx renderer step loop) outside the repo, then delete it. Goal: confirm that `references/inputs-windows-viewport.md` and `references/recipes.md#viewport-like-panel-shell-with-ovrtx` are sufficient.
2. **Stage-widget prototype exercise.** A fresh agent will be asked to build a temporary stage hierarchy tree (model + delegate + TreeView + selection + expansion persistence + filter + rename) outside the repo, then delete it. Goal: confirm that `references/model-view-tree.md` and `references/recipes.md#stage-hierarchy-tree-from-atomic-treeview` are sufficient.

Both exercises must NOT import `StageWidget`, `StageWindow`, `ViewportWidget`, `PropertyWindow`, `LayerWindow`, `ContentBrowserWindow`, `ManagedWindow`, or any other high-level composite. They must follow the strict QA loop (screenshot → analyze → mouse/keyboard via ovui methods → screenshot → analyze). Any gap surfaced during these exercises should be reported back so this skill can be updated.
