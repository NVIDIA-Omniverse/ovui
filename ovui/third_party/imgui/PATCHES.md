# Dear ImGui Local Patches

Upstream version: `v1.92.7-docking` (`IMGUI_VERSION "1.92.7"` in `imgui.h`).
Upstream repository: https://github.com/ocornut/imgui
Upstream docking branch: https://github.com/ocornut/imgui/tree/docking

This vendored copy is not a clean upstream drop. It carries ovui/NVIDIA API
compatibility patches that downstream core code depends on. Upgraders should
use this file as the local patch inventory before replacing files in this
directory.

Audit commands used for this inventory:

```bash
rg -n 'IMGUI_NVIDIA' ovui/third_party/imgui
rg -n 'Shadow|AddShadow|ShadowRect' ovui/third_party/imgui
rg -n 'ImPow|ImLog' ovui/third_party/imgui
rg -n 'stb_image_write|ImFontAtlasDebugWriteTexToDisk' ovui/third_party/imgui
rg -n 'NVIDIA|nvidia|ovui|OVUI|PR[0-9]+|Compatibility helper|ASan|SHADOWS|Custom NVIDIA|FIXME-SHADOWS' ovui/third_party/imgui
rg -n 'ImDrawFlags_ShadowCutOutShapeBackground' ovui/core/CMakeLists.txt ovui/core/src/Shape.cpp ovui/core/src/Rectangle.cpp
```

## Summary

| Class | Patch sites documented | Description |
| --- | ---: | --- |
| 1 | 7 | `IMGUI_NVIDIA` gated API/style additions. |
| 2 | 63 | Ungated shadow API, style, draw-list, shared-data, and atlas baking additions found by the broad shadow audit. |
| 3 | 2 | `ImPow`/`ImLog` double overload namespace qualification fix. |
| 4 | 4 | Build-system alias and core call sites for the shadow cut-out flag layout mismatch. |
| 5 | 1 | Dead `#if 0` font atlas debug writer block removed because it referenced the deleted vendored stb path. |

The broad `Shadow|AddShadow|ShadowRect` audit also reports 8 upstream
`ImGuiCol_BorderShadow` hits. Those are listed under "Non-patch audit hits"
below and are not local patches.

## Class 1: `IMGUI_NVIDIA` Gated Patches

These blocks are compiled when `IMGUI_NVIDIA` is defined. In this repo that
define is set on the vendored `imgui` target and on ovui core/bindings targets,
so downstream code normally sees these APIs.

Affected vendored files:

| File | Lines | Local change |
| --- | --- | --- |
| `imgui.cpp` | 1561-1564 | Initializes `ImGuiStyle::DockSplitterSize` to `6.0f` and `CustomCharBegin` to `0xFFFF`. |
| `imgui.cpp` | 3875-3877 | Adds `ImGuiCol_CustomChar` to `GetStyleColorName()`. |
| `imgui.h` | 1886-1888 | Adds `ImGuiCol_CustomChar` before `ImGuiCol_COUNT`. |
| `imgui.h` | 2450-2453 | Adds `DockSplitterSize` and `CustomCharBegin` to `ImGuiStyle`. |
| `imgui_draw.cpp` | 255-257 | Adds dark style default color for `ImGuiCol_CustomChar`. |
| `imgui_draw.cpp` | 328-330 | Adds classic style default color for `ImGuiCol_CustomChar`. |
| `imgui_draw.cpp` | 402-404 | Adds light style default color for `ImGuiCol_CustomChar`. |

Downstream consumers and integration points:

| File | Lines | Dependency |
| --- | --- | --- |
| `ovui/third_party/CMakeLists.txt` | 20 | Defines `IMGUI_NVIDIA` publicly on the vendored `imgui` object target. |
| `ovui/core/CMakeLists.txt` | 45-53 | Defines `IMGUI_NVIDIA` for `ovui`. |
| `ovui/core/CMakeLists.txt` | 113-117 | Defines `IMGUI_NVIDIA` for `ovuiscene`. |
| `ovui/core/src/MenuHelper.cpp` | 191-205 | Uses `ImGuiCol_CustomChar` and toggles custom glyph coloring. |
| `ovui/core/src/Widget.cpp` | 1005-1015 | Writes `ImGui::GetStyle().CustomCharBegin`. |
| `ovui/core/include/omni/ui/Widget.h` | 702-708 | Documents the custom glyph coloring contract. |

Upgrade notes:

- Keep the enum insertion and style fields in sync with `ImGuiCol_COUNT` and
  `ImGuiStyle` layout checks. `IMGUI_CHECKVERSION()` validates structure sizes,
  so a missed field or color enum change can fail at runtime.
- Re-check whether upstream docking gained an equivalent splitter size setting.
  If not, preserve `DockSplitterSize` or remove downstream users first.
- `CustomCharBegin` and `ImGuiCol_CustomChar` are ovui compatibility APIs. Do
  not drop them while `MenuHelper`/`Widget` still use them.

## Class 2: Ungated Shadow System Additions

The shadow system is not behind `IMGUI_NVIDIA`; it is a direct extension of the
public and internal ImGui API. Core drawing code calls these APIs directly, so
upgrading to a clean upstream ImGui without porting this class will break
compilation and/or shadow rendering.

Affected vendored files:

| File | Lines | Local change |
| --- | --- | --- |
| `imgui.h` | 243 | Adds `typedef int ImDrawShadowFlags`. |
| `imgui.h` | 1885 | Adds `ImGuiCol_WindowShadow`. |
| `imgui.h` | 2443-2445 | Adds `WindowShadowSize`, `WindowShadowOffsetDist`, and `WindowShadowOffsetAngle` to `ImGuiStyle`. |
| `imgui.h` | 3412-3417 | Adds `ImDrawShadowFlags_` and `ImDrawShadowFlags_CutOutShapeBackground` at bit 0. |
| `imgui.h` | 3515-3521 | Adds `IMGUI_HAS_SHADOWS` and `ImDrawList::AddShadowRect`, `AddShadowCircle`, `AddShadowConvexPoly`, and `AddShadowNGon`. |
| `imgui.h` | 3832-3847 | Adds `ImFontAtlasShadowTexConfig`. |
| `imgui.h` | 3967-3969 | Adds `ShadowRectIds[2]`, `ShadowRectUvs[10]`, and `ShadowTexConfig` to `ImFontAtlas`. |
| `imgui_internal.h` | 892-893 | Adds cached shadow atlas pointers to `ImDrawListSharedData`. |
| `imgui.cpp` | 1558-1560 | Initializes the three `WindowShadow*` style fields. |
| `imgui.cpp` | 3874 | Adds `WindowShadow` to `GetStyleColorName()`. |
| `imgui_draw.cpp` | 254, 327, 401 | Adds default `ImGuiCol_WindowShadow` values to dark/classic/light styles. |
| `imgui_draw.cpp` | 408-427 | Implements `ImFontAtlasShadowTexConfig` defaults and convex texture size helpers. |
| `imgui_draw.cpp` | 2153-2165 | Adds the "Shadow Primitives" section and an `ImLength()` compatibility helper. |
| `imgui_draw.cpp` | 2167-2422 | Adds internal helpers for subtracted rectangles and clipped convex shadow geometry. |
| `imgui_draw.cpp` | 2424-2478 | Implements `ImDrawList::AddShadowRect()`. |
| `imgui_draw.cpp` | 2480-2659 | Implements `ImDrawList::AddShadowConvexPoly()`. |
| `imgui_draw.cpp` | 2661-2685 | Implements `ImDrawList::AddShadowCircle()`. |
| `imgui_draw.cpp` | 2687-2691 | Implements `ImDrawList::AddShadowNGon()`. |
| `imgui_draw.cpp` | 3238 | Initializes `ImFontAtlas::ShadowRectIds` to `-1`. |
| `imgui_draw.cpp` | 4160-4382 | Adds shadow texture baking, including rectangular and convex shadow atlases. |
| `imgui_draw.cpp` | 4819-4820 | Propagates shadow atlas pointers into draw-list shared data. |
| `imgui_draw.cpp` | 4951, 5102 | Calls `ImFontAtlasBuildUpdateShadowTexData()` during atlas build/update paths. |

Requested broad shadow audit coverage:

- Local extension hits: `imgui_internal.h:892-893`; `imgui.h:243`,
  `1885`, `2443-2445`, `3412-3416`, `3515`, `3518-3521`,
  `3832-3841`, `3967-3969`; `imgui_draw.cpp:254`, `327`, `401`,
  `408`, `411`, `420`, `425`, `2153`, `2158-2161`, `2424`,
  `2432`, `2452`, `2480`, `2482`, `2490`, `2661`, `2683`,
  `2687`, `2690`, `3238`, `4160`, `4211`, `4217`, `4220`,
  `4224-4225`, `4249`, `4315`, `4325`, `4380`, `4819-4820`,
  `4951`, `5102`; `imgui.cpp:1558-1560`, `3874`.
- Standard upstream `BorderShadow` hits, not local patches:
  `imgui.h:1829`; `imgui_draw.cpp:198`, `271`, `345`;
  `imgui.cpp:3818`, `4050`, `4062`; `imgui_widgets.cpp:1406`.

Downstream consumers in ovui core:

| File | Lines | Dependency |
| --- | --- | --- |
| `ovui/core/src/Shape.cpp` | 63-76 | Resolves shadow style properties, translates the legacy cut-out bit, then forwards shadow parameters to shape-specific drawing. |
| `ovui/core/src/Rectangle.cpp` | 62-68 | Translates legacy corner flags and calls `AddShadowRect()`. |
| `ovui/core/src/Circle.cpp` | 163 | Calls `AddShadowCircle()`. |
| `ovui/core/src/Ellipse.cpp` | 64 | Calls `AddShadowConvexPoly()`. |
| `ovui/core/src/Line.cpp` | 184 | Calls `AddShadowConvexPoly()`. |
| `ovui/core/src/Triangle.cpp` | 157 | Calls `AddShadowConvexPoly()`. |
| `ovui/core/src/Window.cpp` | 535-543, 552-573 | Pushes `ImGuiCol_WindowShadow` for popup and tooltip styling. |
| `ovui/core/src/MainWindow.cpp` | 249 | Pushes transparent `ImGuiCol_WindowShadow` for the main dock window. |
| `ovui/core/src/BezierCurve.cpp` | 178, 182, 188 | Commented-out shadow draw-list calls; audit-only, not active code. |

Other non-core consumers worth checking during upgrades:

- `ovui/standalone/src/HeadlessVulkanPlatform.cpp:227` sets
  `ImGuiCol_WindowShadow`.
- `ovui/standalone/src/GlfwPlatform.cpp:360` sets
  `ImGuiCol_WindowShadow`.

Upgrade notes:

- This class changes public ABI: `ImGuiCol_COUNT`, `ImGuiStyle`,
  `ImDrawList`, `ImFontAtlas`, and `ImDrawListSharedData` all differ from
  upstream. Re-run ImGui's data layout checks after porting.
- Preserve the legacy shadow flag bit layout unless core code and the compile
  definition alias in Class 4 are changed together.
- Re-check upstream atlas APIs. This local copy uses the 1.92 `AddCustomRect()`
  and `GetCustomRect()` APIs while baking shadow textures.
- Keep the ASan-related bound fix in `imgui_draw.cpp:4230-4242`; it prevents
  the rectangular shadow source buffer from being smaller than the copied area
  if padding/config values change.

## Class 3: `ImPow`/`ImLog` Namespace Fix

The local ambiguity fix qualifies the double overloads with the global namespace
to avoid conflicts when other headers, notably Python headers, introduce names
that make unqualified lookup ambiguous.

Affected vendored files:

| File | Lines | Local change |
| --- | --- | --- |
| `imgui_internal.h` | 500 | `ImPow(double, double)` calls `::pow(x, y)`. |
| `imgui_internal.h` | 502 | `ImLog(double)` calls `::log(x)` and carries the `PR7` comment. |

Requested `ImPow|ImLog` audit coverage:

- Patch definitions: `imgui_internal.h:500`, `502`.
- Nearby unmodified float overloads: `imgui_internal.h:499`, `501`.
- Config/comment hit: `imconfig.h:48`.
- Callers/macros that depend on the overload set: `imgui_draw.cpp:148`,
  `4264`, `4333`; `imgui_widgets.cpp:2475`, `2593`, `3007`, `3009`,
  `3012`, `3014`, `3061`, `3063`, `3066`, `3068`, `3121`.

Upgrade notes:

- If upstream changes these wrappers, keep explicit global qualification for
  the double overloads or validate against the Python-enabled build that
  originally needed this fix.
- The float overloads use `powf()`/`logf()` and are not the patched sites.

## Class 4: Build-System Shadow Flag Alias

This class is not a patch inside `third_party/imgui`, but it is part of the
local ImGui integration contract. Kit's ImGui moved the shadow cut-out flag into
`ImDrawFlags` at bit 9, while this standalone vendored ImGui keeps the legacy
separate `ImDrawShadowFlags` enum at bit 0. The alias lets byte-identical shared
core code compile and behave against the standalone vendored ImGui.

Affected build/core files:

| File | Lines | Local integration |
| --- | --- | --- |
| `ovui/core/CMakeLists.txt` | 49-53 | Defines `ImDrawFlags_ShadowCutOutShapeBackground=(1<<0)` for the `ovui` target. |
| `ovui/core/src/Shape.cpp` | 68-74 | Uses `ImDrawFlags_ShadowCutOutShapeBackground` when remapping legacy `shadow_flag=1`. |
| `ovui/core/src/Rectangle.cpp` | 62-68 | ORs `shadowFlag` with translated rounded-corner bits before calling `AddShadowRect()`. |

Requested alias audit coverage:

- `ovui/core/CMakeLists.txt:53`
- `ovui/core/src/Shape.cpp:69`, `74`
- `ovui/core/src/Rectangle.cpp:64`

Upgrade notes:

- If the vendored ImGui shadow API is migrated to upstream-style
  `ImDrawFlags_ShadowCutOutShapeBackground` at bit 9, remove or update the
  compile definition alias and re-check `Shape.cpp`/`Rectangle.cpp` together.
- Do not change only the enum value or only the alias; either mismatch changes
  whether shadows are filled or cut out.

## Class 5: Removed Dead stb Debug Writer Block

`imgui_draw.cpp` previously carried an upstream `#if 0` debug helper,
`ImFontAtlasDebugWriteTexToDisk()`, that locally included
`../stb/stb_image_write.h`. The block was never compiled, and after the third
party cleanup removed `ovui/third_party/stb/`, that relative include pointed at
a non-existent vendored path. The entire disabled helper block was deleted
instead of rewritten to the FetchContent include style.

Affected vendored files:

| File | Lines | Local change |
| --- | --- | --- |
| `imgui_draw.cpp` | ~4875 | Deletes the disabled `STB_IMAGE_WRITE_IMPLEMENTATION` debug helper block and its `../stb/stb_image_write.h` include. |

Upgrade notes:

- If this texture dump helper is needed during a future ImGui upgrade, restore
  it deliberately and include `stb_image_write.h` through the build target's
  dependency include path instead of a relative vendored path.

## Other Marker Audit

The focused marker search found no additional local patch classes beyond the
ones above:

- `IMGUI_NVIDIA` hits are the 7 sites in Class 1.
- `Custom NVIDIA extension` section markers are the shadow primitive and shadow
  texture baking sections in Class 2.
- `Compatibility helper` at `imgui_draw.cpp:2164` and the ASan note at
  `imgui_draw.cpp:4236` are part of Class 2.
- `PR7` at `imgui_internal.h:502` is Class 3.
- Broad `custom`/`patch` searches also find normal upstream ImGui comments such
  as custom backends, custom rectangles, and changelog text. Those are not local
  patches unless listed above.

## How To Upgrade

1. Start from the target upstream docking version, then reapply or intentionally
   replace each class above. Treat Class 2 as the highest-risk class because it
   changes public API, internal shared data, and atlas building.
2. Re-run the audit commands at the top of this file against the upgraded tree.
   Every `IMGUI_NVIDIA`, shadow, and `ImPow`/`ImLog` hit should either map to an
   item in this file or be explicitly classified as an upstream/non-patch hit.
3. Build both standalone and any Python/bindings targets that include Python
   headers to validate the Class 3 namespace fix.
4. Exercise core shadow users: rectangle, circle, ellipse, line, triangle,
   popup/tooltips, and the main dock window. The most likely regressions are
   missing atlas UVs, filled shadows when cut-out was requested, or enum/style
   layout mismatches.
5. If upstream now provides equivalent shadow APIs, remove downstream aliases and
   call-site compatibility code in one coordinated change. Do not leave two
   shadow flag layouts active at the same time.
