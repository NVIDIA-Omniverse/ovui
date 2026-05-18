# Menu Bar, File Open, And Screenshot-First QA

## Menu Bar And File > Open

For Exercise 4, build a minimal top menu in the disposable app. Use `ovui`
menus and the existing `FileImporterHelper`; do not create a custom file
dialog.

```python
import sys

def _to_stage_open_path(url: str) -> str:
    if not url.lower().startswith("file://"):
        return url
    path = url[len("file://"):]
    if (
        sys.platform == "win32"
        and len(path) >= 3
        and path[0] == "/"
        and path[2] == ":"
    ):
        path = path[1:]
    return path

def _build_menu_bar(self) -> None:
    self.menu_window = ui.Window(
        "OvWidgetsTrial_Menu",
        flags=(
            ui.WINDOW_FLAGS_NO_TITLE_BAR
            | ui.WINDOW_FLAGS_NO_RESIZE
            | ui.WINDOW_FLAGS_NO_MOVE
            | ui.WINDOW_FLAGS_NO_SCROLLBAR
            | ui.WINDOW_FLAGS_MENU_BAR
            | ui.WINDOW_FLAGS_NO_DOCKING
            | ui.WINDOW_FLAGS_NO_BACKGROUND
        ),
    )
    self.menu_window.setPosition(0, 0)
    self.menu_window.width = 1280
    self.menu_window.height = 24
    with self.menu_window.frame:
        with ui.MenuBar():
            with ui.Menu("File"):
                ui.MenuItem("Open...", triggered_fn=self.show_open_dialog)
                ui.MenuItem("Exit", triggered_fn=self.request_exit)

def show_open_dialog(self) -> None:
    def on_import(filename: str, dirname: str, selections: list[str]) -> None:
        if selections:
            path = selections[0]
        elif filename:
            path = os.path.join(dirname.rstrip("/"), filename)
        else:
            return
        open_path = _to_stage_open_path(path)
        stage, renderer = open_usd_with_required_ovrtx(open_path)
        self._wire_open_stage(stage, Path(open_path).name, renderer)

    FileImporterHelper.instance().show(
        title="Open USD File",
        import_button_label="Open",
        file_extension_types=USD_EXTENSION_TYPES,
        import_handler=on_import,
        should_validate=True,
    )
```

The dialog callback shape is `import_handler(filename, dirname, selections)`.
Use `selections[0]` when present; otherwise join `dirname` and `filename`.
Local filesystem selections arrive as `file://` URLs from `LocalFSBackend`,
so strip that scheme before calling OpenUSD. Accepted paths must call the
same USD-open path as the positional CLI argument.

## Screenshot-First QA With ovui-inspect

Use `skills/omniverse-ui-inspector` and the QA prompt's screenshot/action/screenshot
loop. Do not use OS-level tools such as `gnome-screenshot`, `xdotool`,
`import`, `xwd`, `scrot`, or raw `ydotool`. Do not use `/execute` to select,
move, or edit prims.

Launch one exercise app at a time as a long-running foreground process:

```bash
mkdir -p "$EVIDENCE_ROOT" "$TRIAL_ROOT/logs"
"$PYTHON_BIN" "$TRIAL_ROOT/trial_app.py" \
  --exercise 3 \
  --width 1280 \
  --height 720 \
  "$USD_FIXTURE" \
  > "$TRIAL_ROOT/logs/exercise3.log" 2>&1
```

In a second shell, drive it with the inspector:

```bash
$REPO/skills/omniverse-ui-inspector/scripts/ovui-inspect wait --timeout 60
$REPO/skills/omniverse-ui-inspector/scripts/ovui-inspect health
$REPO/skills/omniverse-ui-inspector/scripts/ovui-inspect screenshot \
  --out "$EVIDENCE_ROOT/exercise3-01-initial.png" \
  --timeout 60
```

After the launch log contains `renderer=OvRtxRendererAdapter`, poll
`ovui-inspect health` until `last_frame_at` advances between calls and
`queue_depth` is `0`. The first real ovrtx frame can take longer than the
default screenshot timeout, so use `ovui-inspect screenshot --timeout 60` for
the first proof screenshots after launch. One initial timeout during ovrtx
frame settling is not itself a pass/fail signal if `last_frame_at` later
advances, `queue_depth` drains to `0`, and the retry screenshot succeeds.
Repeated timeouts, no frame advancement, or a non-draining queue is a
skill/environment failure.

For every interaction:

1. Open the previous screenshot and identify the target coordinate from what is
   visible.
2. Use exactly one `ovui-inspect move`, `click`, `drag`, `type`, `press`, or
   `combo` command.
3. Capture the next screenshot immediately.
4. Verify visible state before doing the next action.

Proof requirements:

- Exercise 1: viewport-only app, `simple_scene.usda` visibly rendered by
  ovrtx, one prim selected by clicking rendered geometry in the viewport.
- Exercise 2: Stage Browser plus viewport, open USD stage, select `/World/Cube`
  through the visible Stage row or viewport click, both Stage and viewport show
  the same selected prim.
- Exercise 3: Stage, viewport, and Property Inspector, open USD stage, one prim
  selected. Capture before/after screenshots for viewport manipulation updating
  Property, and before/after screenshots for editing a transform/property row
  updating the viewport.
- Exercise 4: Stage, viewport, Property Inspector, and menu bar. Capture
  File > Open menu, the open file dialog, accepted file open, real ovrtx
  viewport content, and one selected prim.

Every successful exercise log must contain the proof marker
`renderer=OvRtxRendererAdapter` and no rejected fallback strings. Every proof
screenshot must show the viewport content itself, not just panel chrome.
