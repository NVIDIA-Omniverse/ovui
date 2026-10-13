# ovui-inspect API Quick Reference

Base URL: `http://127.0.0.1:9910`

## Health

```text
GET /health
GET /status
```

Both return JSON with `status`, `version`, `app_attached`, `queue_depth`,
`state_enabled`, `execute_enabled`, and recent error fields. `last_error` is the
most recent failed request (any client, including readiness polls) and
`last_error_at` its wall-clock time; neither affects `status`.

## Errors and timeouts

A failed request returns HTTP 400 with `detail` as one line
(`ExceptionType: message`) and, for commands that report coded errors, an
`errors` list. The traceback is written to the application's
log; only `/execute` returns it (as `traceback`), since it describes the caller's
own code. A request
that times out says whether the frame loop had started it: "timed out before
the ovui frame loop started it; it was not run", or "timed out after it
started; it may still complete". A timed-out drag, click or combo releases any
button or key it pressed. Input endpoints (`/mouse/*`, `/keyboard/*`) accept `?timeout=` like `/commands`;
the CLI input verbs take `--timeout`.

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
under the `state` key. The inspector does not define that payload: the
application does, and the snapshot's shape therefore belongs to the
application's own documentation. The USD Viewer snapshot is described in
`omniverse-ui-widgets/references/inspector-commands.md`, including the
`state.provider` name, the per-provider scene sections, and the `parity`
object's authority model (`parity.baseline`,
`parity.adapter_matches_baseline`, `parity.topology`, and the deprecated
USD-baseline fields).

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

## Contributed application commands

```text
GET /commands
POST /commands/{name}?timeout=30
```

The catalog provides descriptions and JSON argument schemas for the current app.
POST a direct JSON arguments object; success returns `success` and `result`.
CLI equivalents are `ovui-inspect commands` and `ovui-inspect call NAME
--arguments JSON`. These endpoints use the same queue as existing input,
screenshot and execute requests. They are available only for commands the host
explicitly registers. See [application-commands.md](application-commands.md) for
registration, async handlers, cancellation, shared viewport commands and the
optional persistent namespace/result extension to `/execute`.
