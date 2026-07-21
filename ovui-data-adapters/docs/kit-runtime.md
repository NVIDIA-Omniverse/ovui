<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: LicenseRef-NvidiaProprietary
-->

# OVUI 0.2 native OVStage / OVRTX Kit runtime

The `ovstage` provider uses one Kit rendering build for two connected roles:

- OVStage owns the runtime stage lifecycle and renderer-facing committed
  ordinals. The OVUI adapters drive OVStage natively through its own
  `ovstage.Stage` API.
- OVRTX attaches to OVStage in native BORROW mode and provides pixels, output
  mapping, and picking without owning or replicating scene data.

This is a native OVStage pipeline. The earlier hybrid USD-to-OVStage bridge —
resolving a backing `Usd.Stage` through `ovstage_get_usd_stage_id` and Kit's
`UsdUtils.StageCache` and reusing the OpenUSD adapters for persistent
authoring — is retired. The provider does not import `pxr` or the
`ovui-data-adapters-openusd` package and does not open or mirror a backing USD
stage; structural and runtime isolation tests enforce that boundary.

## Native capability boundary

The native provider deliberately fails closed instead of falling back to an
OpenUSD path. With the `ovstage` provider selected:

- **Unavailable:** durable new-document creation (`create_stage`) and
  save/export (`export_stage`) raise; every layer-stack/composition operation
  (edit targets, save/save-as, sublayer create/insert/remove/move/replace,
  reload, mute, lock, prim-spec access, snapshots) reports an unsupported
  capability; clearing authored property values is unsupported because it
  needs default-value resolution.
- **Supported:** scene open/replace through the native runtime, prim creation
  and deletion, property and transform authoring with undo/redo, rendering,
  picking, and the optional physics controls.

Use the standalone `openusd` provider for the persistence and composition
workflows above.

## Current validation status

This guide defines the required build and runtime contract. Hosted CI builds
and clean-installs the package stack; that proves wheel metadata, dependency
resolution, and imports. It does not load Kit, OVStage, OVRTX, or a GPU.

Native-provider GPU validation is recorded in the integration work for the
native port and its follow-ups (PRs #100, #110, #113): the full application
ran with no OpenUSD distribution installed, and held-drag/present-overlap
performance was measured on real ovstage + ovrtx runtimes. The Linux GPU smoke
in §7 exercises open/render/pick/drag/shutdown for the current provider.

> **Historical note:** an earlier revision of this guide recorded a Linux GPU
> validation of the retired hybrid bridge (OVRTX 0.4 / OVStage 0.1 with the
> `ovstage_get_usd_stage_id` backing-stage accessor). That record applies to
> the retired architecture only and does not describe this release. Native
> end-to-end validation on Windows has not been completed.

## 1. Define portable checkout and build variables

Set these two variables to your checkouts before using the commands below:

```bash
: "${REPO_ROOT:?Set REPO_ROOT to the ovui checkout}"
: "${KIT_ROOT:?Set KIT_ROOT to the omniverse-kit checkout}"

export KIT_PLATFORM="${KIT_PLATFORM:-linux-x86_64}"
export BUILD_CONFIG=release
export RENDERING_ROOT="$KIT_ROOT/rendering"
export RENDERING_BUILD="$RENDERING_ROOT/_build/$KIT_PLATFORM/$BUILD_CONFIG"
export KIT_BUILD="$KIT_ROOT/kit/_build/$KIT_PLATFORM/$BUILD_CONFIG"
export KIT_PYTHON="$KIT_BUILD/python.sh"
export OVSTAGE_ROOT="$RENDERING_ROOT/ovstage"
export OVRTX_ROOT="$RENDERING_ROOT/ovrtx"
```

The examples are Linux-oriented. Keep the same variable contract and substitute
the corresponding platform build directory and Kit launcher on another host.
[`ovui-widgets/WINDOWS-BUILD-OVSTAGE.md`](../../ovui-widgets/WINDOWS-BUILD-OVSTAGE.md)
covers the existing Windows ovui/loader mechanics, but it does not yet reproduce
this OVUI 0.2 native recipe end to end.

## 2. Build the complete Kit rendering tree

Build all of `rendering`; an `ovstage`-only or `ovrtx-dynamic`-only build is not
a usable application runtime:

```bash
cd "$RENDERING_ROOT"
./repo.sh build --devfull -r --no-docker
```

The full build supplies `libovstage`, `libovrtx-dynamic`, the usdrt population
plugin, RTX and sensor libraries, MDL resources, and the matching public Python
packages. Partial builds commonly fail later with
`usdrt::population::IUtils` or `Failed to create HydraEngine` errors.

Verify the expected roots before launching:

```bash
test -x "$KIT_PYTHON"
test -d "$OVSTAGE_ROOT/public/python/ovstage"
test -d "$OVRTX_ROOT/public/python/ovrtx"
test -d "$RENDERING_BUILD/plugins"
```

## 3. Configure the process before Python starts

Native library order is a process-start property. Configure it in the shell;
changing `LD_LIBRARY_PATH` after Python has loaded a native runtime library is
too late.

```bash
export OVSTAGE_BUILD_DIR="$RENDERING_BUILD"
export OVSTAGE_LIBRARY_PATH_HINT="$RENDERING_BUILD"
export OVRTX_BIN_DIR="$RENDERING_BUILD"
export OVRTX_LIBRARY_PATH_HINT="$RENDERING_BUILD"

# The provider needs only the native runtime's own library directories; the
# validated native application run used exactly the ovstage and ovrtx library
# directories with no OpenUSD installation and no Kit omni.usd.libs entry.
export LD_LIBRARY_PATH="$RENDERING_BUILD:$RENDERING_BUILD/plugins:$RENDERING_BUILD/plugins/usdrt:$RENDERING_BUILD/plugins/rtx${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Make the two runtime bindings and the adapter/widget source packages explicit.
# The standalone ovui package is installed into OVUI_PYTHON in §5 instead of
# being injected into Kit Python through this shared path.
export PYTHONPATH="$OVSTAGE_ROOT/public/python:$OVRTX_ROOT/public/python:$REPO_ROOT/ovui-data-adapters:$REPO_ROOT/ovui-widgets${PYTHONPATH:+:$PYTHONPATH}"

export PATH="$RENDERING_BUILD${PATH:+:$PATH}"
export OVUI_DATA_ADAPTER_PROVIDER=ovstage
export OVUI_WIDGETS_REQUIRE_OVRTX=1
export OVRTX_SKIP_USD_CHECK=1
```

Use the Kit launcher as the canonical Python executable:

```bash
"$KIT_PYTHON" -c 'import ovrtx, ovstage; print(ovrtx.__file__); print(ovstage.__file__)'
```

The paths must resolve under the selected Kit checkout/build. A standalone
`ovstage` or OVRTX wheel earlier on `sys.path` can silently select a different
ABI before provider preflight runs.

Import OVRTX first as shown. It performs the process-global renderer/plugin
bootstrap. Version metadata on a development OVRTX build can lag its actual
API surface; treat the concrete import paths, BORROW symbols, and the
provider's startup preflight as authoritative rather than the Python version
string alone.

### Supported native-runtime contract

OVUI 0.2 supports one matched full Kit rendering cohort, not independently
mixed OVStage and OVRTX wheels. A build is compatible only when it exposes all
of these exact APIs:

- callable `ovstage.Stage`;
- callable `ovrtx.RendererConfig` and callable `ovrtx.Renderer`;
- callable `ovrtx.Renderer.attach_ovstage`,
  `ovrtx.Renderer.detach_ovstage`, and
  `ovrtx.Renderer.step`, with an `ordinal` keyword while attached.

BORROW is the supported attachment mode. The current default-BORROW ovrtx API
needs no `AttachMode` type, so the preflight does not require one; when an
ovrtx build does expose `ovrtx.AttachMode.BORROW`, the provider passes that
explicit mode to `ovrtx.RendererConfig`.

The provider's startup preflight verifies the required modules and APIs and
fails with a structured error naming the exact missing capability. The
selected `ovstage` provider cannot run without BORROW rendering:
`OVUI_WIDGETS_REQUIRE_OVRTX=0` does not enable a read-only path, scene
replication, or a substitute renderer. Select a different provider if a
renderer-less session is required.

Kit `python.sh` is canonical for native-runtime validation and adapter tests.
It also exposes Kit's extension form of `omni.ui`, which has no standalone
`ui.init` lifecycle. It therefore cannot directly launch
`python -m ovui_widgets.app`. Build this checkout's standalone ovui into a clean
Python 3.12 environment for the application and smoke, as shown in §5; both
interpreters use the same Kit native-library and public-runtime paths above.

## 4. Native data and authoring flow

```text
USD file
   │
   │ native scene open (ovstage.Stage)
   ▼
OVStage-owned native scene
   │
   │ native stage / property / transform / selection adapters
   │ (accepted edit, undo, or redo)
   ▼
committed OVStage ordinal
   │
   │ Renderer.step(..., ordinal=...)
   ▼
OVRTX BORROW: rendering, outputs, and picks only
```

The boundary is deliberate:

1. The provider session opens the scene through the native `ovstage.Stage`
   API and owns its lifetime, replacement, and cleanup. No `pxr` stage exists
   in the process on the provider's account.
2. Native adapters author prim creation/deletion and property/transform values
   through OVStage's own APIs; each accepted mutation, undo, and redo commits
   a new OVStage ordinal that the renderer consumes.
3. Renderer-only presentation content (private viewport camera,
   RenderProduct/RenderVar wiring, fallback lighting) stays provider-owned and
   is never part of the user's durable scene data.
4. OVRTX is created early, configured for BORROW attachment (passing
   `ovrtx.AttachMode.BORROW` only when the build exposes it), attached
   once with `Renderer.attach_ovstage(stage)`, and stepped with
   `Renderer.step(..., ordinal=scene.current_ordinal)`. A renderer is not
   detached and reattached to the same or a replacement stage: detach is
   terminal cleanup for that renderer instance, and a document replacement
   constructs a fresh renderer.
5. OVRTX data APIs remain prohibited: no OVRTX `write_attribute`, stage reset,
   USD-reference mutation, prim query, or scene replication is used.
6. Shutdown detaches OVRTX and then destroys the native OVStage scene; the
   provider retains the scene/session chain until disposal is proven.

The durable workflows listed in **Native capability boundary** above
(document creation, save/export, layer-stack/composition operations, clearing
authored values) intentionally raise or report unsupported capabilities in
this flow.

## 5. Build standalone ovui and install the adapter packages

Create or select a Python 3.12 environment for the standalone USD Viewer:

```bash
: "${PYTHON_BIN:?Set PYTHON_BIN to a Python 3.12 interpreter}"
: "${TRIAL_ROOT:?Set TRIAL_ROOT to a writable development directory}"
export OVUI_VENV="$TRIAL_ROOT/ovui-kit-runtime"

"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
"$PYTHON_BIN" -m venv "$OVUI_VENV"
export OVUI_PYTHON="$OVUI_VENV/bin/python"
"$OVUI_PYTHON" -m pip install -U pip setuptools wheel
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/common"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/services"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/ovstage"
```

The native provider does not require the OpenUSD adapter package. Install
`ovui-data-adapters/dist/openusd` in addition only when the same environment
should also offer the standalone `openusd` provider; use its `[standalone]`
extra only in an environment intended for that provider.

`ovui-data-adapters-ovstage` contributes the optional Physics menu through
installed entry-point metadata; a source-only `PYTHONPATH` entry does not
register `ovui_widgets.components` entry points.

Verify the component entry point before treating a run as a full parity run:

```bash
"$OVUI_PYTHON" - <<'PY'
from importlib.metadata import entry_points

names = {entry.name for entry in entry_points(group="ovui_widgets.components")}
required = {"ovstage_physics_controls"}
assert required <= names, (required - names, names)
print(sorted(names))
PY
```

The ovui build has additional system prerequisites documented in
[`ovui/README.md`](../../ovui/README.md).

Verify that the application interpreter resolves this checkout's standalone UI
surface rather than Kit's extension module:

```bash
"$OVUI_PYTHON" -c 'import omni.ui as ui; print(ui.__file__); assert callable(ui.init)'
```

## 6. Run the application or focused tests

Launch from the repository with a scene selected by the caller:

```bash
: "${SCENE_PATH:?Set SCENE_PATH to a USD scene}"
cd "$REPO_ROOT"
"$OVUI_PYTHON" -m ovui_widgets.app "$SCENE_PATH"
```

To enable the legacy windowed viewport stream, keep `OMNIUI_HEADLESS` unset and
set the common livestream switch before launch:

```bash
export OVGEAR_LIVESTREAM=1
"$OVUI_PYTHON" -m ovui_widgets.app "$SCENE_PATH"
```

The renderer shares its CUDA mapping with UI zero-copy when enabled and uses a
single stream-plus-device-to-host operation otherwise. The provider-neutral
full-UI headless export requires **both** headless mode and the livestream
switch — `python -m ovui_widgets.app.headless` sets `OMNIUI_HEADLESS=1` but
does not stream by itself:

```bash
export OVGEAR_LIVESTREAM=1
"$OVUI_PYTHON" -m ovui_widgets.app.headless "$SCENE_PATH"
```

Run the complete OVStage adapter suites with the same process environment.
There are two test trees, and they must run as **separate pytest processes**:
several native contract tests assert on clean process import state (for
example, that `pxr` and `ovrtx` were never imported), so combining both trees
in one interpreter contaminates those assertions and fails tests that pass in
their own process.

```bash
cd "$REPO_ROOT"
# Integration/provider tree.
"$KIT_PYTHON" -m pytest -q ovui-data-adapters/tests/ovstage
# Package-local native contract tree (isolation, exact capability,
# unsupported-action, lifecycle, and native authoring contracts) — run in its
# own interpreter.
"$KIT_PYTHON" -m pytest -q ovui-data-adapters/ovui_data_adapters/ovstage/tests
```

GPU/display-dependent rendering behavior is additionally covered by the smoke
below; do not interpret a skipped native-runtime marker as feature evidence.

## 7. Render, pick, and drag smoke

The smoke drives real UI input and captures screenshots/state. On a display-less
Linux host, run the standalone application interpreter under Xvfb:

```bash
: "${EVIDENCE_ROOT:?Set EVIDENCE_ROOT to a writable evidence directory}"
cd "$REPO_ROOT"
xvfb-run -a "$OVUI_PYTHON" -c '
import runpy
import sys

import ovrtx  # Publish OVRTX schema paths before the native runtime initializes.

script = sys.argv[1]
sys.argv = sys.argv[1:]
runpy.run_path(script, run_name="__main__")
' ovui-widgets/scripts/kit_ovstage_smoke.py \
  --out-dir "$EVIDENCE_ROOT"
```

The pre-import matches the validated process order: OVRTX publishes its plugin
paths before the adapter loads the native runtime. The smoke then verifies
that the configured OVRTX source wins when it constructs the native renderer.

The first `Renderer.step(..., ordinal=...)` can spend several minutes compiling
and caching shaders. The smoke defaults to a 300-second first-frame timeout; a
warm second process should be much faster.

This is focused Linux GPU evidence; it does not replace the package-only hosted
CI checks or establish Windows support.

## 8. Known runtime limits

- Durable new-document creation, save/export, layer-stack and composition
  operations, and clearing authored property values are unavailable with the
  native provider (see **Native capability boundary**); the standalone
  `openusd` provider covers those workflows.
- Logical selection and picking work, but the borrowed scene may not show a
  visible outline around selected objects.
- Point-cloud catalogs, requests, and structured errors are implemented, but a
  real point payload is not yet claimed for the selected runtime; radar remains
  disabled when its required resources are unavailable.
- Physics controls require a matching `ovphysx` runtime, imported lazily when
  physics is enabled. Without it, enabling physics reports a structured error
  and does not enter a partial running state.
- OVRTX's current picking contract uses CUDA-visible GPU 0. A source-product
  policy and end-to-end result for multi-GPU systems remain open.
- Public render settings are authored in USD scenes by other tools. Private
  camera, product, RenderVar, and runtime settings do not yet have a defined
  persistence owner.
- Windows package installation is separate from native runtime support. The
  complete native open/edit/render/pick/drag/shutdown flow has not been
  validated on Windows.

The hosted package checks do not close any of these native runtime limits.

## 9. Troubleshooting

| Symptom | Cause / action |
| --- | --- |
| Startup fails with `Please install ovstage.` or a preflight error naming a module/API | The native runtime is not importable or does not expose the required API. Fix the environment or `OVSTAGE_ROOT`/`OVRTX_ROOT` resolution; the provider does not fall back. |
| `could not acquire usdrt::population::IUtils` | The rendering build is partial or libraries/plugins were loaded by the wrong framework instance. Build all of `rendering` and preserve early OVRTX bootstrap. |
| `Failed to create HydraEngine` or missing MDL resources | The rendering build is incomplete or OVRTX initialized too late. Use the full build and application entrypoint. |
| Wrong `ovstage` or `ovrtx` path | Remove stale wheels/checkouts from the environment and rerun the import check in §3. |
| `RendererConfig`, `Renderer`, `attach_ovstage`, `detach_ovstage`, or attached `step(..., ordinal=...)` is missing | An incompatible OVRTX package was selected. There is no replication fallback. |
| A save/export/layer operation reports unsupported | Expected: the native provider does not implement those durable workflows. Use the standalone `openusd` provider. |
| Selection works but no outline is visible | The selected ovrtx build does not expose the renderer-owned outline-membership API (attach-capable ovrtx 0.4 provides it). Selection still synchronizes; the outline degrades honestly. Do not work around it with an OVRTX data write. |
| First frame appears hung | Shader compilation is cold. Allow at least 120 seconds or use the smoke's 300-second timeout. |

The provider never falls back to OVRTX scene replication or an OpenUSD stage.
Runtime mismatches are startup errors because continuing would render a scene
the adapters cannot faithfully author.
