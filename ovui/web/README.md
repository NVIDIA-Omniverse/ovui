# ovui playground

ovui playground is a browser build of the real ovui C++ and pybind11 binding
surface. The shipped app is a custom Emscripten application: official CPython
is built from source for `wasm32-emscripten`, linked with ovui, and initialized
inside `ovui.wasm`.

The top panel is a `<canvas>` rendered by C++ ovui widgets through Dear ImGui
and WebGL. The bottom panel is a browser editor that sends Python source to the
embedded CPython runtime. The shell does not recreate ovui widgets in
JavaScript or DOM.

## Build

Activate Emscripten 3.1.58, or leave `/tmp/ovui-emsdk/emsdk_env.sh` available
for the script to source automatically:

```bash
ovui/web/build_wasm.sh
```

The script downloads and verifies official CPython 3.12.3 sources, builds the
native build Python helper, then configures CPython for the browser
`wasm32-emscripten` target. Build products are cached under ignored directories
inside `ovui/web/`.

The final distribution is always reduced to exactly:

```text
ovui/web/dist/index.html
ovui/web/dist/app.js
ovui/web/dist/styles.css
ovui/web/dist/ovui.wasm
ovui/web/dist/ovui.data
```

`ovui.wasm` contains CPython, the built-in `_ui` extension module, ovui core,
Dear ImGui, and the WebGL platform layer. `ovui.data` preloads CPython standard
library files, the `omni.ui` Python package, and Noto Sans into MEMFS.

## Run

```bash
python3 -m http.server 8765 --directory ovui/web/dist
```

Open:

```text
http://127.0.0.1:8765/
```

## Validation

Useful local checks after a build:

```bash
find ovui/web/dist -maxdepth 1 -type f -printf '%f\n' | sort
python3 - <<'PY'
from pathlib import Path
print(Path("ovui/web/dist/ovui.wasm").read_bytes()[:4])
PY
python3 -m pytest ovui/tests/test_wasm_pybind_architecture.py
```

The reusable high-DPI browser QA script is:

```bash
node ovui/web/test_hidpi_browser.js http://127.0.0.1:8765/index.html
```

## Scope

Included:

- ovui C++ core compiled for WebAssembly.
- Official CPython built from source for `wasm32-emscripten`.
- Existing pybind11 `_ui` binding module compiled as a built-in CPython
  extension.
- Browser `import omni.ui as ui` using the real package, not a fake shim.
- Dear ImGui rendering to a WebGL canvas.
- Packaged Noto Sans font loaded from the preloaded filesystem.

Excluded:

- ovwidgets, ovrtx, USD, CUDA, Vulkan, NVENC, and server streaming.
- `omni.ui_scene` in the first browser target.
