# ovui_widgets_physx_controls

`ovui_widgets_physx_controls` is an optional ovui-widgets component packaged by the
`ovui-data-adapters-ovstage` wheel. It contributes Physics menu items for
ovstage-backed sessions that expose provider-owned physics controls.

## What It Provides

- A `register(app)` function used by the ovui-widgets component loader.
- A `Physics > Enable PhysX` menu item.
- A `Physics > Play Simulation` / stop-style menu item whose label
  and enabled state come from the active provider session.

The component is guarded: if the ovui-widgets menu subsystem is not importable, the
registration returns without failing headless imports.

## Entry Point

The component is registered by `ovui-data-adapters/dist/ovstage/pyproject.toml`:

```toml
[project.entry-points."ovui_widgets.components"]
ovstage_physics_controls = "ovui_widgets_physx_controls:register"
```

There is no separate wheel for this package in the current repository. It is
included in the ovstage adapter wheel.

## Dependencies

Runtime expectations:

- `ovui_widgets.app.menu_bar` for menu contribution registration.
- An active application adapter session with a `physics_controls` object.

The component calls methods such as `toggle_enabled`, `toggle_playing`,
`enable_label`, `play_label`, and `can_toggle_playing` on that controls object
when present.

## Usage

Install the ovstage adapter wheel and launch the app with the ovstage provider:

```bash
export OVUI_DATA_ADAPTER_PROVIDER=ovstage
python -m ovui_widgets.app path/to/scene.usda
```

When the app loads component entry points, the Physics menu contribution is
registered automatically. If the active provider does not expose physics
controls, the menu action reports the provider error through the app's module
load failure reporting path.
