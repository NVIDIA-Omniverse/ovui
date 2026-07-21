# ovui-data-adapters

Adapter layer that decouples `ovui-widgets` from concrete scene-graph
backends. Four distributions:

- **`ovui-data-adapters-common`** — abstract adapter contracts
  (`StageAdapter`, `TransformAdapter`, `LayerStackAdapter`,
  `PropertyAdapter`, `RendererAdapter`, …), small records, and the shared
  livestream helper. It depends on `numpy`; OpenUSD, ovrtx, ovstream, and GPU
  runtimes remain outside this provider-neutral package boundary.

- **`ovui-data-adapters-services`** — installable package boundary for
  frontend-neutral behavior/state services built above the common adapter
  contracts. The content storage/backend, metadata/classification,
  undo/command/history, selection state/eventing, generic settings/
  observer, layer operation command, transform operation command, and
  content navigation/persistence plus file-operation/internal clipboard
  services live here. Frontend-neutral adapter testing fixtures also live
  here so ovui, Qt, and package tests can share the same deterministic
  service doubles without importing `ovui-widgets`.

- **`ovui-data-adapters-openusd`** — concrete OpenUSD adapters that
  implement the contracts above. Depends on `numpy`; the standalone
  `usd-core==25.11` runtime is available only through the optional
  `[standalone]` extra. Uses `ovrtx` when it is importable from the active
  environment or from an external checkout exposed through `OVRTX_ROOT`.

- **`ovui-data-adapters-ovstage`** — the native OVStage provider. It depends
  only on `ovui-data-adapters-common` and drives the externally supplied
  native `ovstage` runtime directly; it does not import `pxr` or the
  `ovui-data-adapters-openusd` package and does not open or mirror a backing
  `Usd.Stage` (structural and runtime isolation tests enforce that boundary).
  OVStage, OVRTX, and optional OVPhysX remain external runtimes. The target
  runtime does not require separate `ovpopulation` or `ovhierarchy` Python
  packages.

## Layout

```
ovui-data-adapters/
├── dist/
│   ├── common/pyproject.toml      ← ovui-data-adapters-common
│   ├── services/pyproject.toml    ← ovui-data-adapters-services
│   ├── openusd/pyproject.toml     ← ovui-data-adapters-openusd
│   └── ovstage/pyproject.toml     ← ovui-data-adapters-ovstage
└── ovui_data_adapters/            ← unified Python import-package root
    ├── common/                    ← imports as ovui_data_adapters.common
    │   ├── __init__.py
    │   └── adapters.py …
    ├── services/                  ← imports as ovui_data_adapters.services
    │   ├── __init__.py
    │   ├── settings.py             ← generic settings / observer service
    │   ├── selection.py            ← selection state / eventing service
    │   ├── transforms.py           ← transform operation command service
    │   ├── undo.py                 ← undo / command / history service
    │   ├── layers/                 ← layer operation command services
    │   ├── testing/                ← reusable adapter/service test doubles
    │   └── content/                ← content metadata, storage, navigation, operation services
    │       ├── asset_types.py
    │       ├── clipboard.py
    │       ├── file_operations.py
    │       ├── navigation.py
    │       └── backends/
    ├── openusd/                   ← imports as ovui_data_adapters.openusd
    │   ├── __init__.py
    │   └── stage_adapter.py …
    └── ovstage/                   ← imports as ovui_data_adapters.ovstage
        ├── __init__.py
        └── stage_adapter.py …
```

**Why dash-form folder, underscore-form package?** The visible
repository folder is `ovui-data-adapters/` (a project naming
requirement). Python identifiers cannot contain dashes, so the import package
inside is `ovui_data_adapters/`. The distributions
(`ovui-data-adapters-common`, `ovui-data-adapters-services`,
`ovui-data-adapters-openusd`, and `ovui-data-adapters-ovstage`) share
that single import-package root via PEP 420 namespace packages.

## Install

Editable installs use the same `dist/<sub>/pyproject.toml` +
`where = ["../.."]` pattern as `ovui-widgets/dist/`:

```bash
pip install -e ovui-data-adapters/dist/common
pip install -e ovui-data-adapters/dist/services
pip install -e ovui-data-adapters/dist/openusd      # common + numpy; uses an existing pxr runtime
pip install -e ovui-data-adapters/dist/ovstage      # common only; native ovstage/ovrtx runtimes are external
```

In a separate environment intended only for the standalone OpenUSD provider:

```bash
pip install -e 'ovui-data-adapters/dist/openusd[standalone]'
```

`ovrtx` is intentionally not a package dependency of any data-adapter
distribution. Install it separately into the active environment when possible,
or point `OVRTX_ROOT` at an external ovrtx checkout/install root. The OpenUSD
and ovstage renderer paths first try the active environment, then try
`$OVRTX_ROOT/public/python`, `$OVRTX_ROOT/python`, and `$OVRTX_ROOT` before
reporting ovrtx as unavailable.

The OpenUSD `[standalone]` extra belongs only in an environment intended for
the standalone `openusd` provider. The native OVStage provider neither needs
nor uses `pxr`, so the extra is simply unnecessary there.

## OVUI 0.2 native OVStage runtime

The OVStage provider drives the native OVStage runtime directly, with a single
scene owner and no OpenUSD layer in between:

1. The provider opens the scene through the native `ovstage.Stage` API. There
   is no backing `Usd.Stage`, stage-cache resolution, or OpenUSD-adapter reuse;
   the retired hybrid USD-to-OVStage bridge does not exist in this release.
2. Native stage, property, transform, selection, and renderer adapters read
   and author through OVStage's own APIs; accepted edits, undo, and redo
   commit new OVStage ordinals. Adapter authoring integrates with the
   application's undo manager.
3. OVRTX attaches to OVStage in native BORROW mode, renders committed
   ordinals, and handles outputs and picks. It receives no OVRTX data writes
   or replicated scene, and the provider never falls back to a substitute
   renderer (`OVUI_WIDGETS_REQUIRE_OVRTX=0` is not honored for `ovstage`).
4. Durable workflows that need default-value resolution or USD composition are
   deliberately unavailable natively: new-document creation, save/export,
   layer-stack and composition operations, and clearing authored values raise
   or report unsupported capabilities instead of silently degrading. Use the
   standalone `openusd` provider for those workflows. Prim create/delete,
   property and transform authoring, rendering, picking, and undo are
   supported natively.

Use the full Kit rendering build for the native libraries. The matching Kit
`python.sh` is the canonical native adapter-test host; the runnable USD Viewer
uses this checkout's standalone ovui build in a clean Python 3.12 environment
because Kit's extension `omni.ui` does not expose `ui.init`. Select the
provider with `OVUI_DATA_ADAPTER_PROVIDER=ovstage`. The complete portable
environment, build, run, and test commands are in the
[Kit-integrated runtime guide](docs/kit-runtime.md).

## Services package boundary

`ovui_data_adapters.services` is the pip-installable package for reusable
frontend-neutral behavior and state orchestration. It sits above
`ovui_data_adapters.common` adapter contracts and below `ovui-widgets` UI,
application runtime, and toolkit integration.

Moved services:

- content backend contracts and local filesystem backend
- content asset metadata/classification
- undo/command/history, including cancellation and null-manager behavior
- selection state, snapshots, eventing, bus, and subscription lifetime
- layer operation command service
- transform operation command service
- generic settings store and observer foundation
- content navigation/persistence state for recent files and bookmarks
- content duplicate-name/file-operation policy and internal clipboard state
- frontend-neutral adapter/service testing fixtures

Old `ovui-widgets` import paths remain compatibility shims or wrappers where
they carried app-owned defaults or singleton policy. Consumers should prefer
the canonical `ovui_data_adapters.services` imports for new frontend-neutral
code, while existing ovui-widgets callers continue to work.

Intentionally not moved in this migration:

- viewport camera/render behavior: left in `ovui-widgets` because the condition
  gate for a neutral clock/renderer protocol was not satisfied
- livestream/control-plane behavior: held by owner decision and the
  hard no-livestream-edit rule; `MessageDispatcher` was not moved
- snap/manipulator policy: remains in `ovui-widgets` as interaction/tool policy
- widgets, delegates, view models, app event loop, status display, OS dialogs,
  native browser/clipboard integration, ovstream transport, renderer payloads,
  and other UI/runtime glue

## Sdist support — intentionally absent

The `dist/<sub>/pyproject.toml` + `where = ["../.."]` pattern
supports editable installs and in-tree wheel builds, but **NOT**
sdist publishing: setuptools cannot package source two levels above
the project root in a self-contained tarball. The
`ovui-widgets/tests/test_data_adapters_install.py` test enforces that
editable installs work; sdist regenerate is unsupported by design.
If sdist publishing is ever needed, restructure to co-located
pyprojects (`ovui-data-adapters/<sub>/pyproject.toml` next to
source with `where = ["."]`).

## Install checks

The `Build App Wheelhouse` pull-request workflow builds the common, OpenUSD,
and `ovui-widgets-all` wheels. It then creates clean environments for the common
livestream import and the standalone OpenUSD aggregate install. Those hosted
checks cover package metadata, dependency resolution, and installed-wheel
imports only; they do not run Kit, OVStage, OVRTX, or GPU rendering.

For local adapter packaging checks, run
`ovui-widgets/tests/test_data_adapters_install.py`; it verifies editable installs
of the runtime-neutral common and services distributions in a fresh venv. The
provider-registration tests separately verify OpenUSD/OVStage dependency and
entry-point metadata. The OpenUSD adapter requires `numpy`;
`usd-core==25.11` is confined to its optional `[standalone]` extra. The OVStage
wheel depends only on the common adapter contracts and expects the external
native OVStage and OVRTX runtimes to be supplied outside of pip. The common
adapter also declares `numpy` because its shipped livestream helper imports it
directly; `ovstream` remains a lazy, externally supplied feature runtime.

The native OVStage provider has a separate, fail-closed runtime contract. A
matching runtime must expose callable `ovstage.Stage` and the public OVRTX
Python BORROW methods listed in the
[Kit-integrated runtime guide](docs/kit-runtime.md); startup preflight names
the exact missing module or API. Package CI does not test that native
contract. The guide's separately recorded GPU evidence does not broaden hosted
CI coverage.
