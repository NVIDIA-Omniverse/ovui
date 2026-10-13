# Native Plot Widget

Use this reference for `ui.Plot` and `ui.TimelinePlot`.

## Two drawing modes

`ui.Plot` defaults to `ui.PlotMode.LEGACY`. This mode keeps the original
ImGui line, histogram, and resampled XY line drawing. Existing constructor
arguments, scales, offsets, strides, styles, and hover tips keep their behavior.

Select `mode=ui.PlotMode.INTERACTIVE` for axes, labels, line, scatter, bars,
and a histogram of sample counts. This mode uses ovui's existing ImGui draw
lists. It needs no extra library, context, renderer, or texture bridge.
`ui.TimelinePlot` remains a separate widget and also uses ImGui draw lists.

The old `ui.ImPlot` and `ui.ImPlotType` names are removed. Use `ui.Plot` in
interactive mode and `ui.PlotType` instead. The original `ui.Type` enum
remains. `ui.PlotType` is an alias for it, with `LINE`, `HISTOGRAM`, `LINE2D`,
`SCATTER`, and `BARS`. The original enum values do not change. Scatter and
bars apply to interactive mode. `LINE2D` also draws a line in that mode.

## Python surface

The first two positional arguments after `type` remain `scale_min` and
`scale_max` in both modes. These scales, `value_offset`, and `value_stride`
apply to legacy drawing. In interactive mode, use `set_data()` or
`set_xy_data()` to supply data and `set_axis_limits()` for fixed ranges.
This avoids using sample values as constructor scales by mistake.

```python
plot = ui.Plot(
    ui.PlotType.LINE,
    mode=ui.PlotMode.INTERACTIVE,
    title="Frame Time",
    x_label="Sample",
    y_label="ms",
    series_label="Frame Time",
    show_legend=False,
    width=ui.Fraction(1),
    height=ui.Fraction(1),
)
plot.set_data(*samples)
plot.fit()
```

In interactive mode, data methods keep double precision. `set_data()` uses
sample indices for X. `set_xy_data()` uses explicit `(x, y)` pairs.
`set_data_provider_fn(fn, count)` calls the provider once for each index.
Changing `mode` keeps the series. Legacy drawing uses float values, as before.
Native C++ code keeps the original float `setData()`, `setXYData()`, and
`setDataProviderFn()` methods. For double precision, use `setSamples()`,
`setXYSamples()`, and `setSampleProviderFn()`, or the constructor
`Plot(Type, Mode, std::vector<double>)`.

The following controls apply to interactive mode:

- `fit()` clears fixed limits and fits both axes on the next draw.
  `auto_fit=True` fits on each draw.
- `set_axis_limits(x_min, x_max, y_min, y_max)` locks the ranges.
  `clear_axis_limits()` removes the lock and requests a fit.
- `sparkline=True` hides decorations and disables mouse range controls.
- Drag the left button to pan. Use the wheel to zoom. Drag the right button
  to select a range. Hold Shift for X only or Alt for Y only.
- Use the wheel or drag over an axis to change that axis only. Release the
  left button to cancel a box while the right button is down. Escape also
  cancels a box.
- Double-click the left button or click the middle button to fit. Click the
  right button over an axis to open its range and display menu. It has Min,
  Max, range locks, per-axis Auto-Fit, Invert, Opposite, Label, Grid Lines,
  Tick Marks, and Tick Labels. Click a legend entry to hide its series.
- The plot menu has both axis menus, Legend, and Settings. Legend controls
  its display, location, and inside or outside placement. Settings controls
  Equal axis units per pixel, Box Select, Title, Mouse Position, and Crosshairs.
- Explicit limits prevent mouse range changes. An axis with Auto-Fit enabled
  also blocks mouse range changes. Min and Max locks keep that range endpoint.
- `interactive=False` disables range controls, selection, menus, and legend
  toggles. It can still show crosshairs and sample hover tips.

Markers and sample tips are off by default. `show_markers=True` draws a
circle at each line sample. `show_sample_tooltip=True` shows the value, X,
and delta from the previous X. With markers, a tip opens only near a circle.
Without markers, it follows the nearest X sample inside the plot.
Use `crosshairs=True` to show a crosshair. `show_mouse_position` controls the
plot-space mouse text. `x_axis_format` sets the X tick format.
Tick labels are spaced with their rendered text width. Histogram bins use
the data range before axis fit padding. Equal samples have a zero-width bin
at their value, drawn as a count peak.

The default tip labels are `Value`, `X`, and `Delta X`. Set
`sample_tooltip_value_label`, `sample_tooltip_x_label`, and
`sample_tooltip_delta_x_label` only where the view owns that meaning.
A view of timed samples supplies `(process_time_seconds, value)` pairs and
sets labels such as `From Process Start (s)` and `From Prev Sample (s)` in
its own view.

## Layout and style

Both modes use the `Plot` selector and `GLOBAL_STYLES["Plot"]`. The separate
`ImPlot` style key is removed. Move custom styles from that key to `Plot`,
or use a named `Plot` variant for a local style.

Use `ui.Fraction(1)` for a plot that follows its parent size. The widget uses
its computed content size. Draw only inside the active widget window and
keep all clip rectangle pushes and pops balanced.

In interactive mode, `background_color` sets the frame and canvas, `color`
sets the series, `border_color` sets the border, and `secondary_color` sets
the text. `padding` and `border_width` set spacing and border width.
Use `name=` for a variant that inherits `Plot`. Use
`style_type_name_override` only for a separate style.

## Data updates

Update retained data only when it changes. The setter invalidates the
raster content. Keep sampling and aggregation outside the widget. Plot
presentation must not give domain meaning to a sample value or timestamp.
