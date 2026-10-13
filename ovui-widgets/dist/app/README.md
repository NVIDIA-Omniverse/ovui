# ovui-widgets-app

`ovui-widgets-app` is the application distribution for the ovui-widgets reference
application. It packages `ovui_widgets.app` and the console entry points used to
run the desktop and headless application.

## What It Provides

- Application startup and adapter-provider selection.
- Component loading for optional `ovui_widgets.components` entry points.
- Menu, file-open, selection, renderer, and frame-loop wiring for the reference
  app.
- Console scripts for `ovui-widgets`, `ovgear`, `ovui-widgets-headless`, and
  `ovgear-headless`.

The app distribution depends on `ovui-data-adapters-common` and resolves the
active backend through the common registry. It does not hard-depend on the
OpenUSD adapter wheel.

## Entry Points

Console scripts declared by the wheel:

```toml
[project.scripts]
ovui-widgets = "ovui_widgets.app.__main__:main_sync"
ovgear = "ovui_widgets.app.__main__:main_sync"
ovui-widgets-headless = "ovui_widgets.app.headless:main"
ovgear-headless = "ovui_widgets.app.headless:main"
```

Optional UI components are loaded from the separate `ovui_widgets.components`
entry-point group by application code.

## Installation

Editable install from the repository:

```bash
python -m pip install -e ovui-widgets/dist/app
```

Wheel build from the repository:

```bash
python -m build ovui-widgets/dist/app
```

The `pyproject.toml` uses `where = ["../.."]` so the wheel sources resolve to
`ovui-widgets/ovui_widgets/app`.

## Dependencies

Runtime dependencies declared by the wheel (in `setup.py`). Each one is pinned
to the version of this wheel, from `VERSION.md`:

- `ovui`
- `ovui-widgets-common[testing]`
- `ovui-widgets-stage`
- `ovui-widgets-layers`
- `ovui-widgets-content`
- `ovui-widgets-property`
- `ovui-widgets-viewport`
- `ovui-data-adapters-common`

The `dev` extra adds pytest, libcst, tomli, and ovui-widgets-content for tests
that use the mock content backend.

## Usage

Run the app with an explicitly selected provider:

```bash
export OVUI_DATA_ADAPTER_PROVIDER=ovstage
python -m ovui_widgets.app path/to/scene.usda
```

Run headless:

```bash
export OVUI_DATA_ADAPTER_PROVIDER=ovstage
python -m ovui_widgets.app.headless --width 1280 --height 720 path/to/scene.usda
```

ovrtx is required by default. Set `OVUI_WIDGETS_REQUIRE_OVRTX=0` only when you
want the existing fallback renderer instead. The selected provider must be
installed and discoverable through `ovui_data_adapters.adapters`.
