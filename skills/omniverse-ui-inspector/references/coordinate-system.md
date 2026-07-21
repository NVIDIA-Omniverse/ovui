# Coordinate System

ovui-inspect uses full-frame screenshot pixel coordinates.

At the recommended launch size:

```bash
python -m ovui_widgets.app.headless --width 1280 --height 720
```

a point seen at `(200, 150)` in the screenshot should be passed to:

```bash
scripts/ovui-inspect click 200 150
```

The first version does not rescale screenshots. Keep the app resolution fixed
during a QA session unless the task explicitly tests resizing. If a resize is
needed, take a fresh screenshot before any follow-up mouse action.

Rules:

1. Take a screenshot before every mouse target decision.
2. Use coordinates from that screenshot only.
3. Do not reuse coordinates after resizing, moving from headless to windowed
   mode, or changing DPI/backend settings.
4. Negative coordinates are rejected as bad requests.
