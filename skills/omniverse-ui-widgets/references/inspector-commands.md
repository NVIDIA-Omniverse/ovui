# Inspector commands contributed by ovui-widgets

The Inspector skill defines how an application contributes typed commands
(`get_inspector_commands()`, `GET /commands`, `ovui-inspect call`); see its
[application-commands](../../omniverse-ui-inspector/references/application-commands.md)
reference. This page covers the providers ovui-widgets ships and how a host
wires them. Contributed commands need `pydantic`, which the Inspector skill's
requirements install; the widgets themselves do not import it until a provider
is built.

## Finding the installed Inspector

Installed hosts can use `ovui_widgets.common.inspector_runtime.inspector_runtime`
as a context manager to discover the installed `omniverse-ui-inspector` skill
provider. Keep the context alive for the host lifetime, including command-provider
construction; an explicit importable `ovuiinspect` still takes precedence. This
does not enable Inspector automatically in applications that treat it as optional.

## Shared viewport vocabulary

`ovui_widgets.viewport.inspector.ViewportInspector` contributes these commands:

| Command | Behavior |
|---|---|
| `viewport_list` | Current visible surfaces, camera and tool snapshots |
| `selection_get` | The shared SelectionBus paths |
| `camera_list` | Authored camera paths; free Perspective/Ortho modes remain UI state |
| `camera_set` | Bind an existing authored camera |
| `viewport_frame` | Frame explicit paths or selection; empty selection frames the scene |
| `viewport_tool` | Stock selection/move/rotate/scale mode |
| `viewport_pick` | GPU pick from current full-application pixels and apply selection mode |

Provide surface and selection accessors rather than a new scene model:

```python
from ovui_widgets.viewport.inspector import ViewportInspector

def get_inspector_commands(self):
    return ViewportInspector(
        lambda: {"primary": self.viewport},
        lambda: self.selection_bus,
    ).commands()
```

The standard USD Viewer already does this. Hosts that maintain render products
can provide `camera_setter(path, view_id)` to keep surface and product bindings
in agreement. Typed picking rejects pixels outside the viewport or in its
letterbox and cancels abandoned renderer requests. It does not guarantee that a
historical screenshot is still current; recapture after scene/camera/layout changes.

The public `ViewportSurface.apply_pick_selection`, `map_pick_to_render_ndc`,
`handle_navigation_key` and `set_transform_manipulator_visible` seams reuse the
existing selection, aspect-fit mapping, navigation and gizmo stack for hosts that
ground a capture or forward native input without a window.

## Shared media provider

`ovui_widgets.app.media_inspector.media_commands(service_getter)` registers six
lazy commands: stream and recording start/status/stop. The shared `Media` service
requires an owner that supplies visible surfaces, product/renderer binding,
settling, artifact location, per-frame export/input hooks and a cheap
`get_media_frame_state()` receipt for each recorded frame. `ReferenceMediaHost`
adapts the ordinary USD Viewer. Media owns the process-level ovstream SDK across
streams; its taps are created with `manage_sdk=False` and never shut the SDK down
themselves. Install the `media` extra of `ovui-widgets-app` for streaming.

```bash
ovui-inspect call stream_start --arguments '{"source":"viewport","view_id":"primary","protocol":"rtsp","signal_port":49100,"media_port":47998}'
ovui-inspect call stream_status
ovui-inspect call stream_stop
ovui-inspect call stream_start --arguments '{"source":"application","protocol":"webrtc"}'
```

`source=viewport` streams a named RTX RenderProduct's CUDA texture, without UI;
the tap is bound by product identity, so another visible camera cannot change its
source, and it follows the product to whichever GPU renders it. `source=application`
streams ovui's composed Vulkan/CUDA framebuffer; recordings currently use it too.
One stream per process: stop before changing source or layout. Remote input is
only supported for an application stream. Stream stop is idempotent and does not
stop an active recording. `stream_status` reports copy failures as `ERROR`;
validate receiver decoding separately from server state.

## Shutdown ordering

Detach Inspector before releasing media, adapters, USD stages or native renderer
resources. `detach_application(app)` cancels pending commands and returns their
tasks; await them with `ovui_widgets.common.inspector_runtime.await_inspector_tasks`,
which protects command cleanup from repeated host cancellation. The ordinary Viewer
follows this ordering, and its synchronous shutdown refuses to release resources
while detached tasks are still pending; let the application loop finish first.

## `/state` payload — the USD Viewer snapshot

`ovui-inspect state` calls the attached application's `get_inspector_state()`
on the ovui frame loop and returns whatever that method produces. The endpoint
itself is generic and documented in
`omniverse-ui-inspector/references/api-endpoints.md`; the payload below is this
application's, implemented in `ovui_widgets/app/inspector_state.py`.

The state request is marshalled onto the ovui frame loop and calls the attached
application's `get_inspector_state()` method. It returns a JSON-safe snapshot
under the `state` key. The USD Viewer snapshot includes the selected paths,
undo/redo edge, renderer ownership data, the active provider's scene state
(native OVStage for the `ovstage` provider; the `usd` section carries data
only when the OpenUSD provider is selected), the provider-neutral adapter and
UI views, and an explicit consistency (`parity`) result across the views that
exist.

The `parity` object identifies its authority explicitly:

- `parity.baseline` names the authoritative scene view the adapter/UI
  hierarchy was compared against — `"usd"` when the USD view is available,
  `"ovstage"` for a native-only session, or `null` when no authoritative view
  exists.
- `parity.comparable` is `false` — and `parity.ok` is always `false`, with
  `parity.indeterminate_reason` set — when neither view exists; parity is
  indeterminate, never affirmed. Any adapter/UI hierarchy present in that
  state is surfaced in `parity.unverified_adapter_paths` instead of being
  silently discarded.
- `parity.adapter_matches_baseline` is the provider-neutral comparison result
  that feeds `parity.ok`.
- `parity.topology` compares the adapter/UI hierarchy against the
  authoritative baseline: with `baseline: "usd"`, prim types and user-child
  ordering are checked against the USD view (and against the native view when
  one also exists); with `baseline: "ovstage"`, adapter prim types and child
  ordering — including the pseudo-root's ordered top-level children, captured
  through the native root query convention — are checked against the native
  scene's own records for every shared path, so equal-path type drift,
  child-order drift, and root-order drift fail rather than passing vacuously.
  In native mode the result also carries the child-enumeration authority
  state: `topology.child_topology_available` is `false` and
  `topology.authority_errors` lists the exact failures when native child
  enumeration is absent, throws, returns malformed/non-iterable output, or
  yields semantically invalid child paths (relative, empty, root,
  non-canonical, wrong direct parent, or duplicates — including mixed
  valid/invalid lists), and `topology.matches` (and therefore `parity.ok`)
  is then always `false` — enumeration failure is never converted into an
  empty child list, and enumerated children unknown to the adapter surface
  as drift rather than being discarded. User-facing versus provider-owned
  native content is decided by the production OVStage adapter's own
  scene-specific ownership rule (scene-registered presentation roots plus
  the authored-`/Render` exception, exposed in
  `topology`-adjacent `child_topology.presentation_roots` and per-prim
  `user_facing` flags): renderer-owned presentation content hidden by the
  adapter is not drift, while user-facing content — including user-authored
  `/Render` — missing from the adapter is. Mismatch records name the
  baseline side (`usd` or `ovstage`) next to the `adapter` side.
- **Deprecated:** `parity.adapter_matches_usd` and
  `parity.ovstage_matches_expected_usd` keep their original USD-baseline
  meaning and are `null` (not applicable) whenever no USD view exists — for
  example for the native `ovstage` provider. Consumers must not treat `null`
  as a match; migrate to `parity.baseline` + `parity.adapter_matches_baseline`.
