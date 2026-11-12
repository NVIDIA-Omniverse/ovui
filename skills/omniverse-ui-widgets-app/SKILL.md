---
name: omniverse-ui-widgets-app
description: |
  Install and run the packaged ovui USD Viewer with ovrtx and either OpenUSD,
  ovstage, or both data adapters. Use when creating a clean virtual
  environment from published wheels, selecting the adapter configuration, or
  launching ovui_widgets.app against a USD file.
license: "Apache-2.0"
metadata:
  python-distribution: ovui-widgets-app
  version: "0.3.1"
---

# ovui-widgets application

## Choose the application workflow

The Windows CMake-generated `ovrtx_ui_app` project is a development-checkout
workflow. Its build target prepares the application packages; do not apply the
manual wheel installation commands below to repair that build-owned
environment.

The following sections describe the packaged-wheel workflow.

## Release packages

The 0.3.1 release contains these 13 first-party distributions. Release
assets are available at <https://github.com/NVIDIA-Omniverse/ovui/releases>.
For a local release build, install from its wheel directory as described below.

| Wheel | Release 0.3.1 |
|---|---|
| `ovui` | One wheel for each platform: Linux x86_64 and Linux aarch64 (`manylinux_2_35`) and Windows x64. CPython 3.12 to 3.15 in one combined wheel; dependency limits below still apply. |
| `ovui-data-adapters-common`, `ovui-data-adapters-services`, `ovui-data-adapters-openusd`, `ovui-data-adapters-ovstage` | Pure Python (`py3-none-any`). |
| `ovui-widgets-common`, `ovui-widgets-content`, `ovui-widgets-stage`, `ovui-widgets-layers`, `ovui-widgets-property`, `ovui-widgets-viewport`, `ovui-widgets-app`, `ovui-widgets-all` | Pure Python (`py3-none-any`). |

PyPI also has the `ovui` wheels of the pre-releases 0.1.0 and 0.1.1 (CPython
3.12 only), but no `ovui-widgets-*` or `ovui-data-adapters-*` package for them.
This skill does not cover them.

These packages come from other projects. ovui does not install or pin them.
Install them from PyPI:

- `ovrtx`, the renderer of the viewport. It has wheels for Linux x86_64, Linux
  aarch64 and Windows x64, and its documentation names Python 3.10 to 3.13. It
  needs an NVIDIA RTX GPU and a driver that ovrtx supports.
- `ovstage`, the native OVStage library that the ovstage provider drives.
- `usd-core`, the OpenUSD Python package (`pxr`). The `standalone` extra of
  `ovui-data-adapters-openusd` installs `usd-core==25.11`.

No other package name is published. PyPI has no `ovwidgets`, `ovui-widgets`,
`ovui-data-adapters` or `ovui-inspector` package. The Inspector skill is in the
`ovui` wheel. A change in the source tree after a release is not in a published
wheel until the next release.

**Python version.** Use CPython 3.12 for the complete packaged viewer. The
0.3.1 native `ovui` wheel supports CPython 3.12 to 3.15, but the pinned
OpenUSD standalone dependency and `ovui-widgets-all` support only 3.12 and
3.13. External renderer/runtime packages have their own Python limits.
Historical 0.2.0 and 0.3.0 native `ovui` wheels have only the `cp312` tag.

**Same release for all packages.** From 0.3.0, each first-party package requires
the other first-party packages at the same version, so pip installs a matched
set. The 0.2.0 packages accept any version (`>=0.1.0`) of the others. See
[Release 0.2.0](#release-020).

## Create the environment

Use a separate virtual environment for each configuration. Make it with
Python 3.12:

```bash
python -m venv .venv
```

Activate `.venv`, upgrade pip, and install exactly one of these configurations.

**ovrtx and ovstage for a release.** ovui does not install or pin `ovrtx` and
`ovstage`. The historical 0.2.0 and 0.3.0 recipes use the `ovrtx` and `ovstage`
that were on PyPI when those releases were published. Later `ovrtx` and `ovstage` releases
can change their interfaces and their data layout. Thus a command for a
published release gives pip the option `--uploaded-prior-to` with a time just
after PyPI got the packages of that release, and before the next `ovrtx` and
`ovstage` releases. pip then uses only the packages that were on PyPI at that
time, so it installs the `ovrtx` and `ovstage` of that release. The option
needs a current pip; the first line of each command block upgrades pip. Each
command below says the release that it is for.

### OpenUSD + ovrtx

This command installs 0.3.1 with `ovrtx`. Add `--find-links /path/to/wheels`
when installing a local release build:

```bash
python -m pip install --upgrade pip
python -m pip install "ovui-widgets-app==0.3.1" "ovui-data-adapters-openusd[standalone]==0.3.1" ovrtx
```

The public 0.3.1 distribution presents the viewport on the normal UI tick;
it does not include an optional native frame-pacing provider.

The viewer of the historical 0.3.0 wheels renders with newer `ovrtx` releases. Their native
frame pacing was built against the interfaces of the `ovrtx` of the 0.3.0
release, and it runs only with an `ovrtx` that has these interfaces. With a
later `ovrtx`, the app writes a `NativeFramePacing` line that says that the
ovrtx runtime does not match the interfaces that native frame pacing was built
against, and it shows the viewport without native frame pacing. For the 0.3.0
wheels with native frame pacing, install the `ovrtx` of the 0.3.0 release:

```bash
python -m pip install --upgrade pip
python -m pip install --uploaded-prior-to 2026-10-14T00:00:00Z "ovui-widgets-app==0.3.0" "ovui-data-adapters-openusd[standalone]==0.3.0" ovrtx
```

The `standalone` extra installs the supported `usd-core==25.11`. If
the environment already provides a compatible `pxr` runtime instead, install
the plain `ovui-data-adapters-openusd` wheel and do not add the `standalone`
extra on top of it. `usd-core==25.11` has wheels for Python 3.8 to 3.13, and
none for Python 3.14 and 3.15. The 0.3.1 native UI wheel supports Python 3.12 to 3.15, but on Python 3.14
and 3.15 use the OVStage provider or a matching `pxr` from the environment,
subject to those external runtimes' Python support (see **Python version** above).

#### Linux AArch64

PyPI has no Linux AArch64 wheel and no source distribution of
`usd-core==25.11`, the version that the `standalone` extra pins, so the extra
cannot be installed on Linux ARM. Some newer `usd-core` releases have Linux
AArch64 wheels, but the `standalone` extra does not install them. For full
compatibility, build or provide a matched OpenUSD runtime. Otherwise,
`usd-exchange` may be useful when limited USD support is better than none, but
its selected, older module set and different native ABI are not drop-in
compatible; required APIs such as `UsdRender` may be absent. Verify the task's
required modules and behavior, and keep exactly one `pxr`/OpenUSD provider in
the environment rather than co-installing providers.

### ovstage + ovrtx (native OVStage)

The ovstage provider reads the stage data that `ovstage` gives in its data
layout. The 0.3.0 wheels can read only the layout of the `ovstage` of the 0.3.0
release. The `ovstage` and `ovrtx` releases that came after 0.3.0 use a newer
layout. With them, the 0.3.0 provider opens and renders the stage, but the
start camera is zoomed in on the objects and a selected prim gets no move
gizmo.

For the 0.3.0 wheels, install the `ovstage` and `ovrtx` of the 0.3.0 release:

```bash
python -m pip install --upgrade pip
python -m pip install --uploaded-prior-to 2026-10-14T00:00:00Z "ovui-widgets-app==0.3.0" "ovui-data-adapters-ovstage==0.3.0" ovstage ovrtx
```

With this command, the 0.3.0 provider opens and renders the stage with the
correct start camera, a selected prim gets the move gizmo, and selection and
transform values are correct.

The 0.3.1 provider reads both data layouts. Install a compatible `ovstage`
and `ovrtx` pair. To install wheels that you built, add
`--find-links /path/to/wheels`.

```bash
python -m pip install --upgrade pip
python -m pip install "ovui-widgets-app==0.3.1" "ovui-data-adapters-ovstage==0.3.1" "ovstage>=0.2.1" ovrtx
```

A Kit rendering build can also supply `ovstage` and `ovrtx`, through the active
environment or `OVSTAGE_ROOT` / `OVRTX_ROOT`. The guide for that build is in the
source repository at `ovui-data-adapters/docs/kit-runtime.md` and requires
access to the Kit rendering tree. For release 0.2.0, that guide requires one
matched Kit/OVStage/OVRTX build for this provider. The PyPI wheels of `ovstage`
and `ovrtx` were not checked with the 0.2.0 provider.

Do not install the OpenUSD adapter or `usd-core` (`pxr`) in this environment
unless you also want the separate `openusd` provider. The public project entry
point is <https://github.com/NVIDIA-Omniverse/ovui>.

**Platform validation boundary:** the current native OVStage end-to-end
validation (open/edit/render/pick/drag/shutdown) is **Linux**. Windows
native end-to-end validation is incomplete/unproven — do not infer Windows
support for the native provider from the generic launch commands below.

### Both adapters + ovrtx

For the 0.3.0 wheels, with the `ovstage` and `ovrtx` of the 0.3.0 release:

```bash
python -m pip install --upgrade pip
python -m pip install --uploaded-prior-to 2026-10-14T00:00:00Z "ovui-widgets-app==0.3.0" "ovui-data-adapters-openusd[standalone]==0.3.0" "ovui-data-adapters-ovstage==0.3.0" ovstage ovrtx
```

For 0.3.1, including locally built wheels supplied with `--find-links`:

```bash
python -m pip install --upgrade pip
python -m pip install "ovui-widgets-app==0.3.1" "ovui-data-adapters-openusd[standalone]==0.3.1" "ovui-data-adapters-ovstage==0.3.1" "ovstage>=0.2.1" ovrtx
```

The OpenUSD provider uses the `standalone` extra's `usd-core` runtime as
above; the native OVStage provider uses the `ovstage` and `ovrtx` described in
the previous section.

### Release 0.2.0

The 0.2.0 packages accept any version of the other first-party packages.
`pip install "ovui-widgets-app==0.2.0"` alone installs the newest first-party
libraries with it. With the 0.3.0 libraries, the app then stops at start with
`TypeError: float() argument must be a string or a real number, not 'NoneType'`.
Pin every first-party package, and install the `ovrtx` of the 0.2.0 release:

```bash
python -m pip install --upgrade pip
python -m pip install --uploaded-prior-to 2026-07-28T00:00:00Z "ovui==0.2.0" "ovui-widgets-app==0.2.0" "ovui-widgets-common==0.2.0" "ovui-widgets-stage==0.2.0" "ovui-widgets-layers==0.2.0" "ovui-widgets-content==0.2.0" "ovui-widgets-property==0.2.0" "ovui-widgets-viewport==0.2.0" "ovui-data-adapters-common==0.2.0" "ovui-data-adapters-services==0.2.0" "ovui-data-adapters-openusd[standalone]==0.2.0" ovrtx
```

A later `ovrtx` can fail with the 0.2.0 wheels. With the `ovrtx` that came
after 0.3.0, the 0.2.0 viewport shows no rendered image.

## Run

The launch commands are the same for 0.2.0, 0.3.0 and 0.3.1:

| Use | Command |
|---|---|
| Canonical launch | `python -m ovui_widgets.app path/to/scene.usd` |
| Console script | `ovui-widgets path/to/scene.usd` |
| Compatibility alias of `ovui-widgets` | `ovgear path/to/scene.usd` |
| From Python | `from ovui_widgets.app.application import Application`, then `Application().run(usd_path="path/to/scene.usd")` |

The scene path is optional. Without it, the app opens an empty stage. The
wheels also have the console scripts `ovui-widgets-headless` and its alias
`ovgear-headless`.

No published release has an `ovwidgets` module or command, and there is no
alias for that name. `python -m ovwidgets.app` stops with
`ModuleNotFoundError: No module named 'ovwidgets'`. In imports, write
`ovui_widgets` in place of `ovwidgets`.

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
