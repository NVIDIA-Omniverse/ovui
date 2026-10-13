# ovui-data-adapters-openusd

`ovui-data-adapters-openusd` is the concrete OpenUSD data-adapter wheel. It
implements the existing OpenUSD-backed stage, property, layer, transform, and
renderer adapter behavior behind the common adapter registry.

## What It Provides

- OpenUSD provider registration in `ovui_data_adapters.openusd.register`.
- Concrete factories for OpenUSD-backed adapters.
- OpenUSD scene and authoring behavior for applications that select the
  `openusd` provider.

## Entry Points

The wheel registers one adapter provider entry point:

```toml
[project.entry-points."ovui_data_adapters.adapters"]
openusd = "ovui_data_adapters.openusd.register:register"
```

The application discovers this entry point through
`ovui_data_adapters.common.discover_adapter_modules`.

## Installation

Editable install from the repository:

```bash
python -m pip install -e ovui-data-adapters/dist/openusd
```

This plain install requires a compatible `pxr` runtime to already be available,
as it is in Kit or a custom OpenUSD environment.

For a separate standalone-OpenUSD environment that does not use Kit OVStage:

```bash
python -m pip install -e 'ovui-data-adapters/dist/openusd[standalone]'
```

Wheel build from the repository:

```bash
python -m pip install build
python -m build --wheel ovui-data-adapters/dist/openusd
```

The `pyproject.toml` uses `where = ["../.."]` so the wheel sources resolve to
`ovui-data-adapters/ovui_data_adapters/openusd`.

## Dependencies

Runtime dependencies declared by the wheel (in `setup.py`):

- `ovui-data-adapters-common`, pinned to the version of this wheel
- `numpy>=1.20`

The optional `standalone` extra installs `usd-core==25.11`; the optional
`livestream` extra installs `ovstream`. Do not install the standalone extra in
the OVUI 0.2 hybrid OVStage runtime: Kit supplies the matching `pxr` stage cache
used to recover OVStage's exact backing stage.

`ovrtx` is optional and external to the package metadata. The renderer first
uses `ovrtx` from the active environment when it is importable. If it is not
importable there, it tries an external install pointed to by `OVRTX_ROOT`,
checking `$OVRTX_ROOT/public/python`, `$OVRTX_ROOT/python`, and then
`$OVRTX_ROOT`.

## Usage

Select the OpenUSD provider explicitly:

```bash
export OVUI_DATA_ADAPTER_PROVIDER=openusd
python -m ovui_widgets.app path/to/scene.usd
```

If no provider is selected, the application uses the common registry selection
rules. Deployments that do not want the OpenUSD provider can omit this wheel or
remove its `ovui_data_adapters.adapters` entry point.
