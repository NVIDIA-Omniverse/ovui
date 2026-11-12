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
  `[standalone]` extra. That usd-core release has wheels for Python 3.8 to
  3.13 and none for Python 3.14 or 3.15, so on Python 3.14 and 3.15 the extra
  cannot be installed: use the OVStage provider or a `pxr` from the
  environment (usd-core 26.11 has Python
  3.14 wheels, but this adapter is not validated with it). Uses `ovrtx` when it is importable from the active
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
repository folder is `ovui-data-adapters/` (a project naming requirement).
Python identifiers cannot contain dashes, so the import package
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

## ovrtx and ovstage compatibility

ovui does not install ovrtx or ovstage and does not pin them. Install the
ones you want into the same environment. Existing users do not need to
upgrade. The ovstage adapter reads both tensor layouts, so earlier ovstage
releases keep working. In one layout the components of a vector or matrix are
reported in the data type (DLPack lanes). In the other they are reported in
the trailing dimensions of the shape.

The adapter tests marked `requires_ovstage` read real stages and show the
values with the layout of the installed release. They do not check native
frame pacing. The first render in a fresh process can take over a minute while
the renderer starts.

The public distribution presents the viewport on the normal UI tick.
Optional native frame-pacing providers are not included. The renderer hook
interfaces remain available for separately supplied compatible providers.

## ovrtx Carb settings and MaterialX deduplication

`ovrtx.RendererConfig` has no field for a generic Carb setting. Some plugin
settings are read when the plugin starts, so they must be set before the first
renderer exists. Set the environment variable `OVUI_OVRTX_CARB_SETTINGS`. Both
renderer adapters (OpenUSD and ovstage) apply it through the ovrtx extension
`ovrtx.settings.apply_settings` right before they create an `ovrtx.Renderer`. When
the renderer library is not loaded yet, they load it with the config of that
renderer. Without the variable, the adapters change nothing.

```bash
export OVUI_OVRTX_CARB_SETTINGS='/persistent/app/material/materialx/disableDeduplication=true'
```

Entries are `/path/to/key=value`. Separate entries with new lines or semicolons.
A value is passed to Carb unchanged. An entry that is not valid, or a setting
that ovrtx rejects, stops the renderer from starting and names the setting. A
host application can call
`ovui_data_adapters.common.ovrtx_carb_settings.apply_carb_settings(ovrtx, tokens, config)`
itself, before it creates a renderer. For USD Workbench, set the variable in the
environment of the app (in a container: `docker run -e OVUI_OVRTX_CARB_SETTINGS=...`).

By default ovrtx generates one MaterialX MDL module for all materials that have the
same cache key. The cache key is a sum over node types and connection names. Two
graphs with the same node types and connection names but other wiring get one
module, and one of the two materials then fails and shows an error color.
`disableDeduplication=true` gives each material its own module and prevents
this. Each material then compiles its own module, which takes more time when the
shader cache is cold, so the adapters do not set it by default. An ovrtx that does not apply this setting
ignores it; the adapters then log a warning. The real-renderer test is
`tests/openusd/test_materialx_identity_real_renderer.py`.

The MaterialX plugin keeps its generated modules in a cache folder. When ovrtx has
no cache root, it tries a `cache` folder next to the executable (for Python, often
`/usr/bin/cache`), logs `Unable to create directory`, and uses a temporary folder.
This does not depend on `disableDeduplication`. To give it a writable folder, add
`/persistent/app/material/materialx/tempDirectory=<writable folder>` to the
variable. The plugin then keeps that folder when the app ends.

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
3. OVRTX attaches to OVStage in `AttachMode.BORROW`, renders committed
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

Native Kit renderer startup is stage-scale safe: type discovery copies only
path/type/schema metadata, catalog and render-setting values use exact owner
queries, and initial camera framing batches only fixed primitive dimensions,
authored extents, and Fabric transforms. It never materializes the general
all-property compatibility cache or reads Mesh point arrays for startup
framing; a Mesh without a usable extent is omitted from that framing pass.

Native consumers that share the provider-owned scene use a deliberately small
public boundary:

- `open_scene_from_file(..., population_domains=...)` can restrict initial
  population to explicit OVStage domains. Omitting the argument preserves the
  provider's normal population entry-point selection.
- `OvstageScene.native_stage` returns the live native Stage only while the
  scene is open. It is the exact mutable borrowed `Stage`, not a copy,
  read-only facade, or backing-USD proxy. Direct native topology commits
  (including raw create and delete operations) are supported: advance the
  native floor after committing, then let the scheduled change stream poll or
  call `OvstageChangeStream.poll()` explicitly before expecting the adapter or
  Stage Tree to reflect the topology change. A recoverable scheduled-poll
  failure preserves the delivered watermark and re-arms polling, so the next
  scheduled poll retries the missed committed change. Value-only native writes
  do not produce a topology `RESYNC`. A consumer that borrows it must release
  its native borrower before scene shutdown.
- `ovui_data_adapters.ovstage.OvstageRendererAdapter` is the public renderer
  integration export. Its ordinary `load_stage()` / `shutdown()` lifecycle
  retains the scene owner until OVRTX has detached.

These seams expose no `pxr` object and do not restore the retired hybrid
backing-USD bridge.

Use the full Kit rendering build for the native libraries. The matching Kit
`python.sh` is the canonical native adapter-test host; the runnable USD Viewer
uses this checkout's standalone ovui build in a clean Python 3.12 environment
because Kit's extension `omni.ui` does not expose `ui.init`. Select the
provider with `OVUI_DATA_ADAPTER_PROVIDER=ovstage`. The complete portable
environment, build, run, and test commands are in the
[Kit-integrated runtime guide](docs/kit-runtime.md).

### Progressive native viewport quality

`OvstageRendererAdapter(..., viewport_quality=0)` now defaults to progressive
presentation on its generated private viewport RenderProduct. It authors
`custom int omni:rtx:quality = 0` before attachment, so resets (including initial
selection-outline activation and resizing) do not request synchronous initial
quality accumulation. Subsequent frames still refine toward the existing
sampling target; total samples, samples per iteration, minimum samples, Eco
mode, and selection/reset behavior are unchanged. This is a private viewport
default, not a global OVRTX setting or a change to the OpenUSD provider.

For a capture that needs the native full initial-quality budget before returning
its first frame, use `OvstageRendererAdapter(..., viewport_quality=100)`. The same
keyword is available on `create_renderer_adapter()` and the OVStage provider
session's `create_renderer()`. Values must be plain Python `int` values from
0 through 100 (not `bool` or integer subclasses). Intermediate values are passed
through to OVRTX; their native behavior is not separately qualified here.
Headless interactive applications keep the progressive default; headless alone
does not imply a one-shot capture.

Only the generated viewport product receives this initial opinion, including
when its private root is relocated to avoid a scene collision. Authored render
products retain their own quality. Switching products, changing render modes,
and resizing do not reapply this default or overwrite later explicit setting
edits. Other products requested in the same render step may still require a
quality wait. This removes the viewport's initial-quality wait, not all possible
GPU, shader, allocation, or readback stalls; `100` likewise does not promise
identical pixels across runtimes.

The generated product's quality descriptor advertises this adapter instance's
configured `viewport_quality` as its default. Resetting that render setting
restores the configured value through the existing undoable authoring path,
rather than deleting the column and falling back to the renderer's native
quality of `100`. Returning to the configured value is reported as unmodified;
later edits remain visible as overrides. This applies only to the exact private
product, including relocated roots. Quality on authored products and all other
settings retain their existing reset semantics. This setting reset is distinct
from a renderer reset or the application's simulation Reset.

### Selection-outline activation reset

The activation reset below still happens; progressive viewport quality removes
only the synchronous quality warm-up that used to follow it.

On native OVRTX 0.5 or newer, the OVStage adapter retains one activation reset
after the first successfully applied non-empty selection. `load_stage()` arms
this activation without directly resetting the renderer. Once the outline
pass is active, completed dedicated membership writes update the outline on
the next `step` / `step_with_stage` without another membership reset, including
replacement, clear, and reselect. This preserves render history for subsequent
selection changes; the first selection can still incur renderer-reset latency.
Resolution-change resets remain unchanged, and resizing while no outline
membership is applied re-arms activation for the next non-empty selection,
which can incur that latency again. The membership-reset gate uses the loaded
native library's `Renderer.version`, not the Python package version. Older or
unknown native versions and legacy transports, including reserved-attribute
writes, retain their existing compatibility reset behavior. Failed membership
writes remain retryable. Native pixel validation must check first selection
in a fresh cube/sphere scene before any camera movement, then replacement,
clear/reselect, and clear → resize → select. Also cover select A → pan → wheel
zoom → select B, with only B outlined afterward; callback timings alone do
not establish outline visibility.

The native-only widget regression
`ovui-widgets/tests/test_native_selection_outline_integration.py` launches a
fresh full-HD viewer, waits idle, and checks first selection, clear, and
reselection pixels with no camera motion. Run it from the monorepo root with
`python -m pytest -c ovui-widgets/pyproject.toml ovui-widgets/tests/test_native_selection_outline_integration.py -q`
on a configured native Vulkan/OVStage/OVRTX host. Hosted adapter CI excludes
these native runtime markers; it does not provide this pixel coverage.

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
- livestream/control-plane behavior: held by the owner's decision
  to preserve the livestream implementation; `MessageDispatcher` was not moved
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
