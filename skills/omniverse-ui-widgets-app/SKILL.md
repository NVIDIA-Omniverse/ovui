---
name: omniverse-ui-widgets-app
description: |
  Install and run the packaged ovui USD Viewer with ovrtx and either OpenUSD,
  ovstage, or both data adapters. Use when creating a clean virtual
  environment from published wheels, selecting the adapter configuration, or
  launching ovui_widgets.app against a USD file.
license: "LicenseRef-NVIDIA"
metadata:
  python-distribution: ovui-widgets-app
  version: "0.2.0"
---

# ovui-widgets application

Use a separate virtual environment for each configuration. **Availability:**
as of this writing only the `ovui` core wheel is published on public PyPI;
the `ovui-widgets-*` and `ovui-data-adapters-*` 0.2 distributions are not
yet on the public index, and no complete public 0.2 wheel channel exists
yet. The 0.2 release wheel set is attached to release pages on the
access-restricted development repository (17 wheels; it
has no standalone `ovui-inspector` distribution because the Inspector skill
is embedded in each `ovui` application wheel); the public repository's
releases currently carry only 0.1.x
assets. If you have access to those wheels — a restricted release download,
a CI wheelhouse artifact, or a wheelhouse built from source — add
`--find-links /path/to/wheels` to the `pip install` commands below; the
commands work verbatim against PyPI once the packages are published.
Sources are at <https://github.com/NVIDIA-Omniverse/ovui>.

## Create the environment

```bash
python -m venv .venv
```

Activate `.venv`, upgrade pip, and install exactly one of these configurations.

### OpenUSD + ovrtx

```bash
python -m pip install --upgrade pip
python -m pip install ovui-widgets-app "ovui-data-adapters-openusd[standalone]" ovrtx
```

The `standalone` extra installs the supported `usd-core==25.11` runtime. If
the environment already provides a compatible `pxr` runtime instead, install
the plain `ovui-data-adapters-openusd` wheel and do not add the `standalone`
extra on top of it.

#### Linux AArch64

PyPI publishes neither a Linux AArch64 `usd-core` wheel nor a source
distribution, so it cannot provide `usd-core` on Linux ARM. For full
compatibility, build or provide a matched OpenUSD runtime. Otherwise,
`usd-exchange` may be useful when limited USD support is better than none, but
its selected, older module set and different native ABI are not drop-in
compatible; required APIs such as `UsdRender` may be absent. Verify the task's
required modules and behavior, and keep exactly one `pxr`/OpenUSD provider in
the environment rather than co-installing providers.

### ovstage + ovrtx (native OVStage)

```bash
python -m pip install --upgrade pip
python -m pip install ovui-widgets-app ovui-data-adapters-ovstage
```

The native `ovstage` and `ovrtx` runtimes are not independently selected
wheels: the supported runtime is one matched Kit/OVStage/OVRTX rendering
build, importable from the active environment or resolved through
`OVSTAGE_ROOT` / `OVRTX_ROOT`. Independently mixed runtime wheels can select
an incompatible ABI, which the provider's startup preflight rejects. There
is currently **no public step-by-step recipe** for building the matched
cohort: the detailed Kit runtime guide lives in the source repository at
`ovui-data-adapters/docs/kit-runtime.md` and requires access to the Kit
rendering tree. Without that access, use the OpenUSD provider configuration
instead. The public project entry point is
<https://github.com/NVIDIA-Omniverse/ovui>. Do not install the OpenUSD
adapter or an OpenUSD runtime in this environment unless you also want the
separate `openusd` provider.

**Platform validation boundary:** the current native OVStage end-to-end
validation (open/edit/render/pick/drag/shutdown) is **Linux**. Windows
native end-to-end validation is incomplete/unproven — do not infer Windows
support for the native provider from the generic launch commands below.

### Both adapters + ovrtx

```bash
python -m pip install --upgrade pip
python -m pip install ovui-widgets-app "ovui-data-adapters-openusd[standalone]" ovui-data-adapters-ovstage
```

The OpenUSD provider uses the `standalone` extra's `usd-core` runtime as
above; the native OVStage provider additionally requires the matched
Kit/OVStage/OVRTX rendering build described in the previous section.

## Run

```bash
python -m ovui_widgets.app path/to/scene.usd
```

With one adapter installed, the app selects it automatically. With both
installed, OpenUSD is the default. Select ovstage explicitly only when both are
installed:

```cmd
set OVUI_DATA_ADAPTER_PROVIDER=ovstage
python -m ovui_widgets.app path\to\scene.usd
```

```bash
OVUI_DATA_ADAPTER_PROVIDER=ovstage python -m ovui_widgets.app path/to/scene.usd
```

Run `python -m pip check`, open a real USD file, and treat a missing, mock, or
fallback ovrtx renderer as a failure.
