# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def test_browser_python_shim_and_loose_dist_tree_are_absent():
    assert not (REPO_ROOT / "web/python/omni/ui/__init__.py").exists()
    assert not (REPO_ROOT / "web/python/omni/__init__.py").exists()
    assert not (REPO_ROOT / "web/dist/python").exists()


def test_static_shell_loads_local_emscripten_app_without_external_python_runtime():
    index_html = read("web/static/index.html")
    app_js = read("web/static/app.js")
    build_script = read("web/build_wasm.sh")
    for text in (index_html, app_js, build_script):
        assert "loadPyodide" not in text
        assert "cdn.jsdelivr.net/pyodide" not in text
    assert '<script src="./app.js" defer></script>' in index_html
    assert "Module.ccall(" in app_js
    assert '"ovui_web_init"' in app_js
    assert 'Module.ccall("ovui_web_run_python"' in app_js
    assert 'Module.ccall("ovui_web_tick"' in app_js
    assert "ovui.wasm" not in index_html


def test_browser_shell_has_no_hand_written_widget_bridge():
    app_js = read("web/static/app.js")
    forbidden = [
        "ovuiWasmBridge",
        "cwrap(",
        "ovui_add_label",
        "_dispatch_from_wasm",
        "createOvuiWasmModule",
    ]
    for token in forbidden:
        assert token not in app_js


def test_build_script_fetches_and_builds_official_cpython_sources():
    build_script = read("web/build_wasm.sh")
    assert "https://www.python.org/ftp/python/${CPYTHON_VERSION}/${CPYTHON_TARBALL}" in build_script
    assert "a6b9459f45a6ebbbc1af44f5762623fa355a0c87208ed417628b379d762dddb0" in build_script
    assert "./Tools/wasm/wasm_build.py build" in build_script
    assert "emconfigure ../../configure" in build_script
    assert "--host=wasm32-unknown-emscripten" in build_script
    assert "--with-emscripten-target=browser" in build_script
    assert "--disable-wasm-dynamic-linking" in build_script
    assert "--with-build-python=" in build_script


def test_new_runtime_links_cpython_ovui_and_builtin_pybind_module():
    cmake = read("web/runtime/CMakeLists.txt")
    assert "add_executable(ovui_web" in cmake
    assert "WebRuntime.cpp" in cmake
    assert "WebPlatform.cpp" in cmake
    assert "WebPlatformBindings.cpp" in cmake
    assert 'bindings/Module.cpp"' in cmake
    assert 'bindings/BindCornerFlag.cpp"' in cmake
    assert "libpython3.12.a" in cmake
    assert "OMNIUI_PYBIND_EMBEDDED" in cmake
    assert "OMNIUI_PYBIND_STRICT_KWARGS" in cmake
    assert "--preload-file ${OVUI_WEB_PACKAGE_DIR}/usr@/usr" in cmake
    assert "--preload-file ${OVUI_WEB_PACKAGE_DIR}/home@/home" in cmake
    assert "--preload-file ${OVUI_WEB_PACKAGE_DIR}/assets@/assets" in cmake
    assert "_ovui_web_init" in cmake
    assert "_ovui_web_run_python" in cmake
    assert "_ovui_web_tick" in cmake


def test_existing_binding_module_can_be_built_as_cpython_embedded_module():
    module_cpp = read("bindings/Module.cpp")
    package_init = read("python/omni/ui/__init__.py")
    assert "include <pybind11/embed.h>" in module_cpp
    assert "define OMNIUI_PYBIND_MODULE PYBIND11_EMBEDDED_MODULE" in module_cpp
    assert "OMNIUI_PYBIND_MODULE(_ui, m)" in module_cpp
    assert '_importlib.import_module("_ui")' in package_init
    assert '_sys.modules.setdefault(__name__ + "._ui", _ui_module)' in package_init
    assert "_web_init = _ui_module._web_init" in package_init
    assert "_web_window_callback_count = _ui_module._web_window_callback_count" in package_init


def test_browser_c_abi_runs_python_through_embedded_cpython():
    runtime = read("web/runtime/WebRuntime.cpp")
    assert "PyConfig_InitIsolatedConfig(&config)" in runtime
    assert "config.module_search_paths_set = 1" in runtime
    assert 'appendSearchPath(config, L"/home/ovui/python")' in runtime
    assert 'appendSearchPath(config, L"/usr/local/lib/python312.zip")' in runtime
    assert "Py_InitializeFromConfig(&config)" in runtime
    assert 'PyImport_ImportModule("omni.ui")' in runtime
    assert "ui._web_reset()" in runtime
    assert "exec(_ovui_user_code" in runtime


def test_default_example_uses_real_binding_arguments():
    app_js = read("web/static/app.js")
    assert "fill_app_window=False" in app_js
    assert "fill_app_window=True" not in app_js
    assert "ui.SimpleFloatModel" in app_js
    assert "ui.ProgressBar(progress_model" in app_js
    assert "ui.set_style" not in app_js


def test_fill_app_window_is_the_only_fill_window_binding_name():
    bind_init = read("core/include/omni/ui/bind/BindWindow.h")
    bind_window = read("bindings/BindWindow.h")
    assert "OMNIUI_PYBIND_INIT_CAST(fill_app_window, setFillAppWindow, bool)" in bind_init
    assert '.def_property("fill_app_window", &Window::getFillAppWindow, &Window::setFillAppWindow' in bind_window


def test_transcription_mistake_fill_alias_is_not_present_in_ovui_sources():
    forbidden = "fill_" + "up_window"
    skipped_dirs = {".cache", "build-wasm", "dist", "__pycache__"}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(REPO_ROOT)
        if any(part in skipped_dirs or part.startswith(".") for part in relative.parts):
            continue
        if path.suffix in {".a", ".so", ".o", ".png", ".jpg", ".jpeg", ".ttf", ".wasm", ".data", ".pyc"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        assert forbidden not in text, str(relative)


def test_browser_keyboard_focus_is_scoped_to_canvas():
    html = read("web/static/index.html")
    app_js = read("web/static/app.js")
    platform = read("web/runtime/WebPlatform.cpp")
    assert 'id="canvas"' in html
    assert 'tabindex="0"' in html
    assert 'canvas.addEventListener("pointerdown"' in app_js
    assert "EMSCRIPTEN_EVENT_TARGET_WINDOW" not in platform
    assert "emscripten_set_keydown_callback(m_canvasSelector.c_str(), this, EM_FALSE, keyCallback)" in platform
    assert "isPrintableInput(event)" in platform
    assert "io.AddInputCharactersUTF8(event->key)" in platform
    assert "emscripten_set_keypress_callback" not in platform


def test_browser_canvas_backing_store_uses_device_pixel_ratio():
    app_js = read("web/static/app.js")
    platform = read("web/runtime/WebPlatform.cpp")
    bindings = read("web/runtime/WebPlatformBindings.cpp")
    assert "window.devicePixelRatio" in app_js
    assert "canvas.getBoundingClientRect()" not in app_js
    assert "canvas.clientWidth" in app_js
    assert "canvas.clientHeight" in app_js
    assert "Math.round(cssWidth * dpr)" in app_js
    assert "Math.round(cssHeight * dpr)" in app_js
    assert "canvas.width = framebufferWidth" in app_js
    assert "canvas.height = framebufferHeight" in app_js
    assert "canvasSizeDirty" in app_js
    assert "state.canvasSizeDirty && state.ready && !state.running" in app_js
    assert '"ovui_web_resize"' in app_js
    assert 'pybind11::arg("device_pixel_ratio") = 1.0f' in bindings
    assert "_web_dpi_info" in bindings
    assert "m_logicalWidth" in platform
    assert "m_framebufferWidth" in platform
    assert "io.DisplaySize = ImVec2(static_cast<float>(m_logicalWidth), static_cast<float>(m_logicalHeight))" in platform
    assert "io.DisplayFramebufferScale" in platform
    assert "viewport->FramebufferScale = io.DisplayFramebufferScale" in platform
    assert "glViewport(0, 0, m_framebufferWidth, m_framebufferHeight)" in platform


def test_browser_canvas_border_is_outside_drawable_canvas():
    index_html = read("web/static/index.html")
    styles = read("web/static/styles.css")
    assert '<div class="canvas-frame">' in index_html
    assert ".canvas-frame" in styles
    canvas_block = styles[styles.index("#canvas") : styles.index(".editor-pane")]
    assert "border: 0;" in canvas_block
    assert "border-radius: 0;" in canvas_block
    assert "outline: none;" in canvas_block


def test_browser_shell_is_named_ovui_playground():
    index_html = read("web/static/index.html")
    readme = read("web/README.md")
    assert "<title>ovui playground</title>" in index_html
    assert '<span class="brand-title">ovui playground</span>' in index_html
    assert readme.startswith("# ovui playground")


def test_built_dist_has_exact_target_shape_when_present():
    dist = REPO_ROOT / "web/dist"
    if not dist.exists():
        pytest.skip("wasm dist has not been built")

    files = sorted(path.name for path in dist.iterdir())
    assert files == ["app.js", "index.html", "ovui.data", "ovui.wasm", "styles.css"]
    assert (dist / "ovui.wasm").read_bytes()[:4] == b"\0asm"
    assert (dist / "ovui.data").stat().st_size > 1_000_000

    app_js = (dist / "app.js").read_text(encoding="utf-8", errors="ignore")
    assert '"/home/ovui/python/omni/ui/__init__.py"' in app_js
    assert '"/usr/local/lib/python312.zip"' in app_js
    assert '"/assets/fonts/NotoSans-Regular.ttf"' in app_js
    assert "loadPyodide" not in app_js
    assert "cdn.jsdelivr.net/pyodide" not in app_js


def test_browser_has_reusable_high_dpi_qa_script():
    qa_script = read("web/test_hidpi_browser.js")
    assert "deviceScaleFactor" in qa_script
    assert "canvas.clientWidth" in qa_script
    assert "Math.round(metrics.clientWidth * metrics.dpr)" in qa_script
    assert "keyboard.insertText" in qa_script
    assert "fill_app_window=True" in qa_script
    assert "mobile_390_ready" in qa_script
    assert "width: 390" in qa_script
    assert "assertCanvasFitsViewport" in qa_script


def test_web_reset_clears_window_callbacks():
    platform = read("web/runtime/WebPlatform.cpp")
    bindings = read("web/runtime/WebPlatformBindings.cpp")
    manager = read("standalone/src/StandaloneWindowCallbackManager.h")
    assert "clearCallbacks()" in manager
    assert "s_windowCallbackManager->clearCallbacks()" in platform
    assert "_web_window_callback_count" in bindings


def test_wasm_binding_rejects_unknown_kwargs_in_strict_build():
    bind_utils = read("core/include/omni/ui/bind/BindUtils.h")
    assert "OMNIUI_PYBIND_STRICT_KWARGS" in bind_utils
    assert "Unsupported omni.ui keyword argument" in bind_utils
    assert "pybind11::key_error" in bind_utils
