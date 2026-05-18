# ovui-inspect API Quick Reference

Base URL: `http://127.0.0.1:9910`

## Health

```text
GET /health
GET /status
```

Both return JSON with `status`, `version`, `app_attached`, `queue_depth`,
`execute_enabled`, and recent error fields.

If a CLI or HTTP client reports connection refused, the FastAPI inspector is no
longer reachable. Verify that the ovui app process is still running and that
the recorded PID is still listening on the configured port before treating the
next input command as a keyboard or mouse failure.

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

## Mouse

```text
POST /mouse/move
  {"x": 100, "y": 80, "timeout": 5}

POST /mouse/click
  {"x": 100, "y": 80, "button": "left", "double": false, "timeout": 5}

POST /mouse/drag
  {"start_x": 100, "start_y": 80, "end_x": 300, "end_y": 120,
   "button": "left", "duration": 0.2, "steps": 10, "timeout": 10}

POST /mouse/scroll
  {"direction": "down", "amount": 5, "x": 300, "y": 300, "timeout": 5}
```

Coordinates are screenshot pixels. The app drains one input step per ovui frame
so click and drag sequences preserve hover, press, release ordering. Drag
`steps` is the exact movement sample count. If `steps` is omitted, drag
`duration` is converted to movement samples at about 60 samples per second; if
both are supplied, `steps` wins. `/mouse/move` and `/mouse/click` require both
`x` and `y`; missing coordinate fields return a 4xx validation response.

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
