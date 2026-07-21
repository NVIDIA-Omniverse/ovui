# ovui-inspect API Quick Reference

Base URL: `http://127.0.0.1:9910`

## Health

```text
GET /health
GET /status
```

Both return JSON with `status`, `version`, `app_attached`, `queue_depth`,
`state_enabled`, `execute_enabled`, and recent error fields.

## Read-only application state

```text
GET /state?timeout=5
```

This QA-only endpoint is disabled by default. Launch the application with
`OVUIINSPECT_ENABLE_STATE=1` to enable it; otherwise it returns HTTP 403.
Its payload can contain open file paths, layer/property values, and interaction
geometry, so do not enable it for an ordinary Inspector session.

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

This endpoint is read-only;
it must not replace mouse or keyboard actions in a QA scenario. A workflow
that chooses action coordinates from this state is state-guided UI evidence,
not strict screenshot-first evidence. Strict runs may use state after an action
to verify its semantic result.

If a CLI or HTTP client reports connection refused, the FastAPI inspector is no
longer reachable. Verify that the ovui app process is still running and that
the recorded PID is still listening on the configured port before treating the
next input command as a keyboard or mouse failure.

## Correlated checkpoint

```text
POST /checkpoint?timeout=5&fmt=png
```

A checkpoint is state-bearing and has the same
`OVUIINSPECT_ENABLE_STATE=1` requirement as `/state`; it returns HTTP 403 by
default. Ordinary `/screenshot` capture remains available without this opt-in.

A checkpoint freezes the application's read-only Inspector state and registers
one screenshot request during the same queued UI-thread operation. The response
contains that frozen `state` plus a `screenshot` object with:

- `request`: the request ID, exact output path, and status observed immediately
  after registration;
- `result`: the terminal request-scoped status, extent, format, and byte count;
- `image_base64`, `mime_type`, and `bytes`: the exact captured image.

The state is not recaptured while the screenshot completes, and each checkpoint
uses a unique output path. Use this endpoint when evidence needs to establish
which screenshot request was registered beside a particular state snapshot.
Like `/state`, it is read-only and must not replace mouse or keyboard actions;
it does not make state-derived targeting screenshot-first.

## Capture

```text
GET  /screenshot?timeout=5&fmt=png
POST /screenshot?fmt=png&timeout=5
GET  /capture/application.png?timeout=5
GET  /capture/application.jpg?timeout=5
POST /capture/application?fmt=png&timeout=5
```

The `GET` routes return image bytes. `/screenshot` is a full-application
capture alias and returns PNG by default; pass `fmt=jpg` for JPEG. The `POST`
routes return `image_base64`, `mime_type`, and byte count.

Inspector accepts a screenshot only when ovui's request-scoped result retains
the exact request ID and path registered after scheduling, reaches terminal
`succeeded` status with `success: true`, reports a positive width and height,
and writes a nonempty image with the expected PNG or JPEG signature. A stale
request, wrong path, failure/cancellation, invalid extent, missing or empty
file, or invalid image signature fails the HTTP request. With older ovui
builds that expose only `_schedule_screenshot()` and
`_poll_screenshot_done()`, Inspector retains a compatibility path: it assigns
an Inspector-local request ID and derives the codec and extent from the
persisted PNG or JPEG before returning success. That fallback cannot provide
native request identity, so rebuild ovui when request-scoped correlation is
required.

## Mouse

```text
POST /mouse/move
  {"x": 100, "y": 80, "timeout": 5}

POST /mouse/click
  {"x": 100, "y": 80, "button": "left", "double": false, "timeout": 5}

POST /mouse/drag
  {"start_x": 100, "start_y": 80, "end_x": 300, "end_y": 120,
   "button": "left", "duration": 0.2, "steps": 10,
   "modifiers": ["shift"], "timeout": 10}

POST /mouse/scroll
  {"direction": "down", "amount": 5, "x": 300, "y": 300, "timeout": 5}
```

Coordinates are screenshot pixels. The app drains one input step per ovui frame
so click and drag sequences preserve hover, press, release ordering. Drag
`steps` is the exact movement sample count. If `steps` is omitted, drag
`duration` is converted to movement samples at about 60 samples per second; if
both are supplied, `steps` wins. `/mouse/move` and `/mouse/click` require both
`x` and `y`; missing coordinate fields return a 4xx validation response.
Drag modifiers are held before mouse-down and released after mouse-up, enabling
real Shift/Ctrl marquee and drag-copy scenarios.

## Keyboard

```text
POST /keyboard/type
  {"text": "hello", "timeout": 5}

POST /keyboard/press
  {"key": "enter", "modifiers": ["ctrl"], "timeout": 5}

POST /keyboard/combo
  {"combo": "CTRL+A", "timeout": 5}
```

Supported keys include letters, digits, `enter`, `escape`, `tab`, `space`,
`backspace`, `delete`, arrows, `home`, `end`, `page_up`, `page_down`, `insert`,
and `f1` through `f24`.

The `/keyboard/combo` endpoint reports whether the chord was injected
successfully. Visible shortcut effects depend on the focused widget. For
example, the Stage filter uses a headless remote text fallback that appends
printable text directly to its model, so Ctrl+A followed by `/keyboard/type` is
not a reliable selected-text replacement test for that field.

## Execute And Shutdown

```text
POST /execute
  {"code": "print(app)", "timeout": 10}

POST /shutdown
  {}
```

`/execute` is disabled unless the app was launched with
`OVUIINSPECT_ENABLE_EXECUTE=1`. The namespace exposes `app` and `application` as
the attached `Application` instance.
