<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: LicenseRef-NvidiaProprietary
-->

# OVUI 0.2 temporary Kit development runtime

This is the checkout-oriented companion to
[`kit-runtime.md`](./kit-runtime.md). The canonical guide defines the native
OVStage → OVRTX BORROW architecture, its capability boundary, and the
troubleshooting table. This page concentrates on building and launching
directly from an evolving `omniverse-kit` tree without installing the native
runtime system-wide. Commands below are Bash/Linux recipes. The existing
[`ovui-widgets/WINDOWS-BUILD-OVSTAGE.md`](../../ovui-widgets/WINDOWS-BUILD-OVSTAGE.md)
covers Windows ovui/loader mechanics, but it does not yet reproduce this OVUI
0.2 native recipe end to end.

> **Validation boundary:** These commands reproduce the development setup.
> Read **Current validation status** in [`kit-runtime.md`](./kit-runtime.md)
> before selecting a revision. Hosted CI remains package-only, and Windows
> native validation has not been completed.

## 1. Build and path contract

Define checkout paths once:

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

Build the complete rendering tree:

```bash
cd "$RENDERING_ROOT"
./repo.sh build --devfull -r --no-docker
```

Building only `ovstage` or `ovrtx-dynamic` omits runtime plugins and resources
used by population, Hydra, sensors, and MDL. A complete build is a prerequisite,
not an optional validation lane.

## 2. Development shell

Configure native and Python resolution before launching the process:

```bash
export OVSTAGE_BUILD_DIR="$RENDERING_BUILD"
export OVSTAGE_LIBRARY_PATH_HINT="$RENDERING_BUILD"
export OVRTX_BIN_DIR="$RENDERING_BUILD"
export OVRTX_LIBRARY_PATH_HINT="$RENDERING_BUILD"

# The provider needs only the native runtime's own library directories; the
# validated native application run used exactly the ovstage and ovrtx library
# directories with no OpenUSD installation and no Kit omni.usd.libs entry.
export LD_LIBRARY_PATH="$RENDERING_BUILD:$RENDERING_BUILD/plugins:$RENDERING_BUILD/plugins/usdrt:$RENDERING_BUILD/plugins/rtx${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export PATH="$RENDERING_BUILD${PATH:+:$PATH}"

# Explicit runtime bindings plus the adapter and widget source roots. The
# standalone ovui package is installed into OVUI_PYTHON below.
export PYTHONPATH="$OVSTAGE_ROOT/public/python:$OVRTX_ROOT/public/python:$REPO_ROOT/ovui-data-adapters:$REPO_ROOT/ovui-widgets${PYTHONPATH:+:$PYTHONPATH}"

export OVUI_DATA_ADAPTER_PROVIDER=ovstage
export OVUI_WIDGETS_REQUIRE_OVRTX=1
export OVRTX_SKIP_USD_CHECK=1
```

Use the matching Kit launcher for native-runtime validation and adapter tests:

```bash
"$KIT_PYTHON" -c 'import ovrtx, ovstage; print(ovrtx.__file__); print(ovstage.__file__)'
```

Both modules must come from the selected Kit checkout/build; a stale wheel or
checkout earlier on `sys.path` can silently select a different ABI before
provider preflight runs.
Kit `python.sh` exposes Kit's extension form of `omni.ui`, which does not have
the standalone `ui.init` lifecycle required by `python -m ovui_widgets.app`.
Use the clean standalone application interpreter created below for the USD
Viewer and render/pick/drag smoke.

## 3. Install the adapter packages

The OVStage adapter package is natively isolated: it depends only on
`ovui-data-adapters-common`, drives the native `ovstage` runtime directly, and
never imports `pxr` or the `ovui-data-adapters-openusd` package (isolation
tests enforce this). It does not ask OVRTX or a second USD stage to fill
authoring gaps; durable workflows the native runtime cannot express —
new-document creation, save/export, layer-stack/composition operations, and
clearing authored values — fail closed instead (see the capability boundary in
[`kit-runtime.md`](./kit-runtime.md)).

Install the adapter packages into the Kit test host:

```bash
"$KIT_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/common"
"$KIT_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/services"
"$KIT_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/ovstage"
```

The Kit interpreter above is the native test host. Build this checkout's
standalone ovui and install the same adapter distributions into a separate
Python 3.12 environment for the application:

```bash
: "${PYTHON_BIN:?Set PYTHON_BIN to a Python 3.12 interpreter}"
: "${TRIAL_ROOT:?Set TRIAL_ROOT to a writable development directory}"
export OVUI_VENV="$TRIAL_ROOT/ovui-kit-dev-runtime"

"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
"$PYTHON_BIN" -m venv "$OVUI_VENV"
export OVUI_PYTHON="$OVUI_VENV/bin/python"
"$OVUI_PYTHON" -m pip install -U pip setuptools wheel
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/common"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/services"
"$OVUI_PYTHON" -m pip install -e "$REPO_ROOT/ovui-data-adapters/dist/ovstage"
"$OVUI_PYTHON" -c 'import omni.ui as ui; print(ui.__file__); assert callable(ui.init)'
```

Add `ovui-data-adapters/dist/openusd` only when the same environment should
also offer the standalone `openusd` provider; its `[standalone]` extra belongs
only in an environment intended for that provider. The native OVStage provider
neither needs nor uses `pxr`.

## 4. Development data flow

1. The provider session opens the source file through the native
   `ovstage.Stage` API and owns the scene's lifetime, replacement, and
   cleanup. No `pxr` stage exists in the process on the provider's account.
2. Native stage, property, transform, and selection adapters read and author
   through OVStage's own APIs. Every successful command, undo, and redo
   commits a new OVStage ordinal that the renderer consumes.
3. Renderer-only presentation data (private viewport camera,
   RenderProduct/RenderVar wiring, fallback lighting) remains provider-owned
   and never becomes part of the user's durable scene data.
4. OVRTX is initialized early, attaches in native BORROW mode (the public
   `ovrtx.AttachMode.BORROW` symbol is passed only when a build exposes it;
   current runtimes default to BORROW), and renders the committed ordinal with
   `step(..., ordinal=...)`. It does not receive a USD file, a replicated
   scene, or any OVRTX data writes.
5. Shutdown detaches OVRTX before native OVStage destruction; the provider
   retains the scene/session chain until disposal is proven.

Durable new-document creation, save/export, layer-stack/composition
operations, and clearing authored values are unavailable in this flow by
design; the standalone `openusd` provider covers those workflows.

## 5. Run and verify

Launch a caller-selected scene:

```bash
: "${SCENE_PATH:?Set SCENE_PATH to a USD scene}"
cd "$REPO_ROOT"
"$OVUI_PYTHON" -m ovui_widgets.app "$SCENE_PATH"
```

Run all OVStage adapter tests from the same shell — both the
integration/provider tree and the package-local native contract tree. Run the
two trees as **separate pytest processes**: several native contract tests
assert on clean process import state (for example, that `pxr` and `ovrtx`
were never imported), so a combined invocation contaminates those assertions.

```bash
cd "$REPO_ROOT"
"$KIT_PYTHON" -m pytest -q ovui-data-adapters/tests/ovstage
"$KIT_PYTHON" -m pytest -q ovui-data-adapters/ovui_data_adapters/ovstage/tests
```

Run the real pick/drag smoke under Xvfb when no display is available:

```bash
: "${EVIDENCE_ROOT:?Set EVIDENCE_ROOT to a writable evidence directory}"
cd "$REPO_ROOT"
xvfb-run -a "$OVUI_PYTHON" ovui-widgets/scripts/kit_ovstage_smoke.py \
  --out-dir "$EVIDENCE_ROOT"
```

The first OVRTX frame can compile shaders for several minutes. Keep the smoke's
300-second first-frame timeout for a cold build.

## 6. Temporary dev bundle

If a build must be copied to another machine, preserve these relative pieces:

```text
rendering/ovstage/public/python/ovstage
rendering/ovrtx/public/python/ovrtx
rendering/_build/<platform>/<config>/
kit/_build/<platform>/<config>/python.sh
```

The native libraries, plugins, and Kit launcher are one matched runtime.
Copying only the two Python packages is insufficient.

## 7. Common development failures

| Symptom | Cause / fix |
| --- | --- |
| Startup fails with `Please install ovstage.` or a preflight error naming a module/API | The native runtime is not importable or lacks the required API. Fix the environment or `OVSTAGE_ROOT`/`OVRTX_ROOT` resolution and rerun the import check in §2; there is no fallback. |
| `usdrt::population::IUtils` or Hydra creation failure | The rendering build is partial or native load order is wrong. Run the full build and reuse the documented shell. |
| A save/export/layer operation reports unsupported | Expected: the native provider does not implement those durable workflows. Use the standalone `openusd` provider. |
| OVRTX rejects a scene write/query/repopulation call | Expected in BORROW mode. Scene-data work belongs on the native OVStage adapter path; do not add a replication fallback. The parameterless renderer `reset()` remains allowed only to invalidate presentation state after an OVStage-owned resolution change. |
| Wrong module version/path | A stale wheel or checkout shadowed the explicit public Python roots. Inspect the module paths in §2. |
| Selection is logical but the outline is absent | The selected ovrtx build does not expose the renderer-owned outline-membership API (attach-capable ovrtx 0.4 provides it); selection still synchronizes and the outline degrades honestly. Do not compensate with an OVRTX data API. |

For full architecture and troubleshooting details, return to
[`kit-runtime.md`](./kit-runtime.md).
