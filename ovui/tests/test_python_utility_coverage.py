# SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Unit tests for pure-Python ovui utility layers."""

from __future__ import annotations

import asyncio
import gc
import sys
import types
import unittest
import warnings
from pathlib import Path
from unittest import mock


_ROOT = Path(__file__).resolve().parents[1]
_PYTHON = _ROOT / "python"
if str(_PYTHON) not in sys.path:
    sys.path.insert(0, str(_PYTHON))


try:  # pragma: no cover - import guard for partial worktrees.
    import omni.ui as ui  # noqa: E402
    from omni.ui import _compat  # noqa: E402
    from omni.ui import abstract_shade  # noqa: E402
    from omni.ui import color_utils  # noqa: E402
    from omni.ui import constant_utils  # noqa: E402
    from omni.ui import markdown_styles  # noqa: E402
    from omni.ui import singleton  # noqa: E402
    from omni.ui import standalone as ui_standalone  # noqa: E402
    from omni.ui import testing as ui_testing  # noqa: E402
    from omni.ui import url_utils  # noqa: E402
    from omni.ui_scene import compatibility as scene_compatibility  # noqa: E402
    from omni.ui_scene import gesture_bindings  # noqa: E402

    _HAVE_UI = True
except Exception:  # noqa: BLE001 - tolerate source-only import failures.
    _HAVE_UI = False


if _HAVE_UI:

    class _MemoryShade(abstract_shade.AbstractShade):
        def __init__(self):
            super().__init__()
            object.__setattr__(self, "values", {})

        def _find(self, name):
            return self.values.get(name)

        def _store(self, name, value):
            self.values[name] = value


@unittest.skipUnless(_HAVE_UI, "omni.ui not available")
class TestShadeAndColorUtilities(unittest.TestCase):
    def test_abstract_shade_set_get_alias_dependencies_and_generated_names(self):
        shade = _MemoryShade()

        generated = shade.shade(1, light=2, name="tone")
        self.assertEqual(generated, "tone")
        self.assertEqual(shade.values["tone"], 1)
        shade.set_shade("light")
        self.assertEqual(shade.values["tone"], 2)
        shade.set_shade("light")  # no-op branch
        self.assertEqual(shade.values["tone"], 2)

        shade.alias = "tone"
        self.assertEqual(shade.values["alias"], 2)

        shade.set_shade()
        shade.base = 10
        dependent = shade.shade("base", light=20, alt=3)
        self.assertTrue(dependent.startswith("shade:base;alt=3;light=20"))
        self.assertEqual(shade.values[dependent], 10)
        shade.base = 30
        self.assertEqual(shade.values[dependent], 30)

        shade.named.add_shade(default=5, light=6)
        self.assertEqual(shade.values["named"], 5)
        shade.set_shade("light")
        self.assertEqual(shade.values["named"], 6)

        keep_internal = []
        shade._current_shade = "custom"
        keep_internal.append(shade._current_shade)
        self.assertEqual(keep_internal, ["custom"])

    def test_shade_name_does_nothing_after_parent_is_gone(self):
        shade = _MemoryShade()
        name = shade.transient
        del shade
        gc.collect()
        name.add_shade(default=1)

    def test_color_conversions_and_invalid_input(self):
        color = color_utils.color
        self.assertEqual(color("#01020304"), 0x04030201)
        self.assertEqual(color("#010203"), 0xFF030201)
        self.assertEqual(color(1, 2, 3, 4), 0x04030201)
        self.assertEqual(color(-1, 999, 3), 0xFF03FF00)
        self.assertEqual(color(1.0, 0.5, 0.0, 0.25), (63 << 24) + (0 << 16) + (127 << 8) + 255)
        self.assertEqual(color(7), 0xFF070707)
        self.assertEqual(color(0.5), 0xFF7F7F7F)
        with self.assertRaises(ValueError):
            color(object(), None, None)

    def test_float_and_url_shades_delegate_to_store(self):
        class _Store:
            values = {}

            @classmethod
            def find(cls, name):
                return cls.values.get(name)

            @classmethod
            def store(cls, name, value):
                cls.values[name] = value

        with mock.patch.object(constant_utils.ui, "FloatStore", _Store):
            constant = constant_utils.FloatShade()
            constant.border = 3.5
            self.assertEqual(_Store.values["border"], 3.5)
            self.assertEqual(constant._find("border"), 3.5)

        _Store.values = {}
        with mock.patch.object(url_utils.ui, "StringStore", _Store):
            url = url_utils.StringShade()
            url.icon = "asset://icon.svg"
            self.assertEqual(_Store.values["icon"], "asset://icon.svg")
            self.assertEqual(url._find("icon"), "asset://icon.svg")

    def test_singleton_decorator_returns_one_instance(self):
        calls = []

        @singleton.Singleton
        class Demo:
            def __init__(self, value):
                calls.append(value)
                self.value = value

        self.assertIs(Demo(1), Demo(2))
        self.assertEqual(Demo(3).value, 1)
        self.assertEqual(calls, [1])


@unittest.skipUnless(_HAVE_UI, "omni.ui not available")
class TestMarkdownStyleBranches(unittest.TestCase):
    def test_normalization_aliases_and_invalid_name(self):
        self.assertEqual(markdown_styles._normalize_name(None), "black")
        self.assertEqual(markdown_styles._normalize_name(" LIGHT "), "white")
        self.assertEqual(markdown_styles._normalize_name("darkblue"), "dark-blue")
        with self.assertRaises(ValueError):
            markdown_styles._normalize_name("magenta")

    def test_each_style_branch_contains_expected_values_and_is_fresh(self):
        white = markdown_styles.markdown_style("white", table_policy="content-fit", font_size=15)
        blue = markdown_styles.markdown_style("dark-blue", table_policy="equal", font_size=16)
        black = markdown_styles.markdown_style("black")

        self.assertEqual(white["MarkdownWidget"]["font_size"], 15)
        self.assertEqual(white["MarkdownWidget.Table"]["layout_policy"], "content-fit")
        self.assertEqual(blue["MarkdownWidget"]["font_size"], 16)
        self.assertIn("MarkdownWidget.H2", blue)
        self.assertIn("MarkdownWidget.Alert.Caution", black)
        self.assertIn("MarkdownWidget.CodeBlock.Keyword", white)
        self.assertIn("MarkdownWidget.CodeBlock.Keyword", blue)
        self.assertIn("MarkdownWidget.CodeBlock.Keyword", black)

        white["MarkdownWidget"]["font_size"] = 99
        self.assertEqual(markdown_styles.markdown_style("white")["MarkdownWidget"]["font_size"], 14)

    def test_background_and_theme_branches(self):
        self.assertIsInstance(markdown_styles.markdown_background("white"), int)
        self.assertIsInstance(markdown_styles.markdown_background("dark-blue"), int)
        self.assertIsInstance(markdown_styles.markdown_background("black"), int)
        theme = markdown_styles.markdown_theme("blue", table_policy="content-fit", font_size=17)
        self.assertIn("background", theme)
        self.assertEqual(theme["style"]["MarkdownWidget"]["font_size"], 17)
        self.assertEqual(theme["style"]["MarkdownWidget.Table"]["layout_policy"], "content-fit")


class _FakeUiInput:
    def __init__(self):
        self.calls = []
        self.clipboard = ""
        self.schedule_result = True
        self.poll_result = True
        self.fallback_result = False
        self.raise_schedule_attribute = False

    def _inject_mouse_move(self, x, y):
        self.calls.append(("move", x, y))

    def _inject_mouse_button(self, button, down):
        self.calls.append(("button", button, down))

    def _inject_mouse_scroll(self, dx, dy):
        self.calls.append(("scroll", dx, dy))

    def _inject_text_input(self, text):
        self.calls.append(("text", text))

    def _inject_key_event(self, key_code, down):
        self.calls.append(("key", key_code, down))

    def _get_clipboard_text(self):
        return self.clipboard

    def _set_clipboard_text(self, text):
        self.clipboard = text

    def _schedule_screenshot(self, filepath):
        if self.raise_schedule_attribute:
            raise AttributeError("old backend")
        self.calls.append(("schedule", filepath))
        return self.schedule_result

    def _poll_screenshot_done(self):
        self.calls.append(("poll",))
        return self.poll_result

    def _capture_screenshot(self, filepath):
        self.calls.append(("capture", filepath))
        return self.fallback_result


@unittest.skipUnless(_HAVE_UI, "omni.ui not available")
class TestTestingHelpers(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake_ui = _FakeUiInput()
        self.frames = 0
        self._old_ui = ui_testing._ui
        self._old_next_frame = ui_testing.next_frame
        ui_testing._ui = self.fake_ui

        async def fake_next_frame():
            self.frames += 1
            await asyncio.sleep(0)

        ui_testing.next_frame = fake_next_frame

    async def asyncTearDown(self):
        ui_testing._ui = self._old_ui
        ui_testing.next_frame = self._old_next_frame

    async def test_mouse_helpers(self):
        await ui_testing.mouse_click(10, 20, button=1)
        self.assertEqual(
            self.fake_ui.calls,
            [("move", 10, 20), ("button", 1, True), ("button", 1, False)],
        )
        self.assertEqual(self.frames, 5)

        self.fake_ui.calls.clear()
        self.frames = 0
        await ui_testing.mouse_double_click(1, 2)
        self.assertEqual(self.fake_ui.calls.count(("button", 0, True)), 2)
        self.assertEqual(self.fake_ui.calls.count(("button", 0, False)), 2)
        self.assertEqual(self.frames, 8)

        self.fake_ui.calls.clear()
        self.frames = 0
        await ui_testing.mouse_move(3, 4)
        await ui_testing.mouse_drag(0, 0, 10, 20, steps=2)
        await ui_testing.mouse_scroll(5, 6, dx=1, dy=-2)
        self.assertIn(("move", 5.0, 10.0), self.fake_ui.calls)
        self.assertIn(("move", 10.0, 20.0), self.fake_ui.calls)
        self.assertIn(("scroll", 1, -2), self.fake_ui.calls)
        self.assertEqual(self.frames, 11)

    async def test_keyboard_text_and_wait_helpers(self):
        await ui_testing.type_text("Hello")
        await ui_testing.press_key(42)
        await ui_testing.wait_frames(3)

        self.assertEqual(self.fake_ui.calls, [("text", "Hello"), ("key", 42, True), ("key", 42, False)])
        self.assertEqual(self.frames, 7)

    async def test_next_frame_calls_tick_when_not_patched(self):
        ui_testing.next_frame = self._old_next_frame
        with mock.patch.object(ui_testing, "_tick_one_frame") as tick:
            await ui_testing.next_frame()
        tick.assert_called_once_with()

    async def test_clipboard_and_screenshot_paths(self):
        ui_testing.set_clipboard_text("copied")
        self.assertEqual(ui_testing.get_clipboard_text(), "copied")

        with mock.patch("omni.ui.standalone._tick_one_frame") as tick:
            self.assertTrue(ui_testing.capture_screenshot("/tmp/shot.png"))
        tick.assert_called_once_with()
        self.assertIn(("schedule", "/tmp/shot.png"), self.fake_ui.calls)
        self.assertIn(("poll",), self.fake_ui.calls)

        self.fake_ui.calls.clear()
        self.fake_ui.schedule_result = False
        self.fake_ui.fallback_result = True
        self.assertTrue(ui_testing.capture_screenshot("/tmp/fallback.png"))
        self.assertIn(("capture", "/tmp/fallback.png"), self.fake_ui.calls)

        self.fake_ui.calls.clear()
        self.fake_ui.raise_schedule_attribute = True
        self.assertTrue(ui_testing.capture_screenshot("/tmp/old.png"))
        self.assertIn(("capture", "/tmp/old.png"), self.fake_ui.calls)


@unittest.skipUnless(_HAVE_UI, "omni.ui not available")
class TestCompatAndNamespaceUtilities(unittest.TestCase):
    def test_standalone_settings_and_step_frame(self):
        _compat.set_setting("/test/value", 123)
        self.assertEqual(_compat.get_setting("/test/value"), 123)
        self.assertEqual(_compat.get_setting("/test/missing", "fallback"), "fallback")
        self.assertIsNone(_compat.subscribe_to_change("/test/value", lambda *_: None))
        self.assertIsNone(_compat.unsubscribe_to_change(None))
        self.assertIsNone(_compat.step_frame(3))

    def test_add_to_namespace_lifetime_and_none(self):
        module = types.SimpleNamespace(__name__="package.demo")
        namespace = {}
        remover = ui.add_to_namespace(module, namespace)
        self.assertIs(namespace["demo"], module)
        self.assertIsNone(ui.add_to_namespace(None, namespace))
        del remover
        gc.collect()
        self.assertNotIn("demo", namespace)

    def test_set_shade_and_menu_delegate(self):
        with mock.patch.object(abstract_shade.AbstractShade, "set_shade", autospec=True) as set_shade:
            ui.set_shade("light")
        self.assertEqual(set_shade.call_count, 3)
        self.assertEqual([call.args[1] for call in set_shade.call_args_list], ["light", "light", "light"])
        self.assertEqual([call.args[0] for call in set_shade.call_args_list], [ui.color, ui.constant, ui.url])

        with mock.patch.object(ui.MenuDelegate, "set_default_delegate") as set_default:
            ui.set_menu_delegate("delegate")
        set_default.assert_called_once_with("delegate")


class _FakeStandaloneBackend:
    def __init__(self):
        self.calls = []
        self.window_size = (640, 480)
        self.cursor_enabled = False
        self.should_close_values = [True]
        self.init_streaming_result = True
        self.streaming_tick_result = True
        self.resize_streaming_result = True

    def _standalone_init(self, title, width, height):
        self.calls.append(("init", title, width, height))

    def _standalone_shutdown(self):
        self.calls.append(("shutdown",))

    def _standalone_tick(self):
        self.calls.append(("tick",))

    def _standalone_should_close(self):
        if self.should_close_values:
            return self.should_close_values.pop(0)
        return True

    def _standalone_set_window_size(self, width, height):
        self.window_size = (width, height)
        return True

    def _standalone_get_window_size(self):
        return self.window_size

    def _set_software_cursor(self, enabled):
        self.cursor_enabled = enabled

    def _is_software_cursor_enabled(self):
        return self.cursor_enabled

    def _init_streaming(self, width, height):
        self.calls.append(("init_streaming", width, height))
        return self.init_streaming_result

    def _shutdown_streaming(self):
        self.calls.append(("shutdown_streaming",))

    def _streaming_tick(self):
        self.calls.append(("streaming_tick",))
        return self.streaming_tick_result

    def _get_streaming_gl_texture(self):
        return 101

    def _get_streaming_width(self):
        return 1920

    def _get_streaming_height(self):
        return 1080

    def _get_streaming_cuda_ptr(self):
        return 202

    def _get_streaming_cuda_pitch(self):
        return 303

    def _get_streaming_format(self):
        return "rgba8"

    def _is_streaming_cuda_available(self):
        return True

    def _streaming_sync(self):
        self.calls.append(("streaming_sync",))

    def _get_streaming_cuda_event(self):
        return 404

    def _resize_streaming(self, width, height):
        self.calls.append(("resize_streaming", width, height))
        return self.resize_streaming_result


@unittest.skipUnless(_HAVE_UI, "omni.ui not available")
class TestStandaloneHelpers(unittest.TestCase):
    def setUp(self):
        self.fake_ui = _FakeStandaloneBackend()
        self._saved = {
            "_ui": ui_standalone._ui,
            "_initialized": ui_standalone._initialized,
            "_next_frame_futures": list(ui_standalone._next_frame_futures),
            "_frame_index": ui_standalone._frame_index,
            "_last_tick_time": ui_standalone._last_tick_time,
            "_max_frame_rate": ui_standalone._max_frame_rate,
            "_streaming_initialized": ui_standalone._streaming_initialized,
        }
        ui_standalone._ui = self.fake_ui
        ui_standalone._initialized = False
        ui_standalone._next_frame_futures = []
        ui_standalone._frame_index = 0
        ui_standalone._last_tick_time = None
        ui_standalone._max_frame_rate = 60.0
        ui_standalone._streaming_initialized = False

    def tearDown(self):
        ui_standalone._ui = self._saved["_ui"]
        ui_standalone._initialized = self._saved["_initialized"]
        ui_standalone._next_frame_futures = self._saved["_next_frame_futures"]
        ui_standalone._frame_index = self._saved["_frame_index"]
        ui_standalone._last_tick_time = self._saved["_last_tick_time"]
        ui_standalone._max_frame_rate = self._saved["_max_frame_rate"]
        ui_standalone._streaming_initialized = self._saved["_streaming_initialized"]

    def test_init_shutdown_window_cursor_and_frame_rate(self):
        ui_standalone.set_max_frame_rate(None)
        self.assertIsNone(ui_standalone.get_max_frame_rate())
        ui_standalone.set_max_frame_rate(0)
        self.assertIsNone(ui_standalone.get_max_frame_rate())
        ui_standalone.set_max_frame_rate(120)
        self.assertEqual(ui_standalone.get_max_frame_rate(), 120.0)
        self.assertAlmostEqual(ui_standalone._max_fps_target_period(), 1 / 120)

        self.assertFalse(ui_standalone.set_window_size(1, 2))
        self.assertEqual(ui_standalone.get_window_size(), (0, 0))

        with mock.patch("atexit.register") as register:
            ui_standalone.init("Demo", 300, 200, max_fps=30)
            ui_standalone.init("Demo again", 1, 1, max_fps=None)
        self.assertEqual(self.fake_ui.calls.count(("init", "Demo", 300, 200)), 1)
        register.assert_called_once_with(ui_standalone.shutdown)
        self.assertIsNone(ui_standalone.get_max_frame_rate())

        self.assertTrue(ui_standalone.set_window_size(800, 600))
        self.assertEqual(ui_standalone.get_window_size(), (800, 600))
        ui_standalone.set_software_cursor(True)
        self.assertTrue(ui_standalone.is_software_cursor_enabled())

        ui_standalone.shutdown()
        self.assertIn(("shutdown",), self.fake_ui.calls)
        self.assertFalse(ui_standalone._initialized)
        self.assertEqual(ui_standalone._frame_index, 0)
        self.assertIsNone(ui_standalone._last_tick_time)

    def test_tick_resolves_futures_and_remaining_budget(self):
        loop = asyncio.new_event_loop()
        self.addCleanup(loop.close)
        future = loop.create_future()
        ui_standalone._next_frame_futures.append(future)

        # _tick_one_frame requires a live backend: it re-checks
        # ``_initialized`` under the native lock and skips after teardown.
        ui_standalone._initialized = True
        self.addCleanup(setattr, ui_standalone, "_initialized", False)
        with mock.patch.object(ui_standalone.time, "monotonic", side_effect=[10.0, 10.01, 10.02]):
            first = ui_standalone._tick_one_frame()
            remaining = ui_standalone._max_fps_remaining_since(10.0)

        self.assertEqual(first, ui_standalone.FrameInfo(dt=0.0, time=10.0, index=0))
        self.assertTrue(future.done())
        self.assertIs(future.result(), first)
        self.assertGreater(remaining, 0.0)
        self.assertIn(("tick",), self.fake_ui.calls)

        ui_standalone.set_max_frame_rate(None)
        self.assertEqual(ui_standalone._max_fps_target_period(), 0.0)
        self.assertEqual(ui_standalone._max_fps_remaining_since(10.0), 0.0)

    def test_ensure_initialized_run_and_async_loop_exit(self):
        with mock.patch.object(ui_standalone, "init") as init:
            ui_standalone._ensure_initialized()
        init.assert_called_once_with()

        # run()'s pacing is an interruptible event wait (returns False on
        # timeout = budget elapsed), re-checking should_close each pass:
        # one False for the outer loop, one for the pacing loop.
        self.fake_ui.should_close_values = [False, False, True]
        with mock.patch.object(
            ui_standalone._wakeup_event, "wait", return_value=False
        ) as wait:
            with mock.patch.object(ui_standalone, "_max_fps_remaining_since", return_value=0.001):
                with mock.patch("atexit.register"):
                    ui_standalone.run()
        wait.assert_called_once_with(0.001)
        self.assertFalse(ui_standalone._initialized)

        async def run_once():
            self.fake_ui.should_close_values = [False, True]
            with mock.patch("atexit.register"):
                with mock.patch.object(ui_standalone, "_max_fps_remaining_since", return_value=0.0):
                    await ui_standalone.run_async()

        asyncio.run(run_once())

    def test_streaming_state_transitions_and_accessors(self):
        self.assertEqual(ui_standalone.get_streaming_gl_texture(), 0)
        self.assertEqual(ui_standalone.get_streaming_size(), (0, 0))
        self.assertEqual(ui_standalone.get_streaming_cuda_ptr(), 0)
        self.assertEqual(ui_standalone.get_streaming_cuda_pitch(), 0)
        self.assertEqual(ui_standalone.get_streaming_cuda_buffer(), (0, 0))
        with self.assertRaises(RuntimeError):
            ui_standalone.streaming_tick()
        with self.assertRaises(RuntimeError):
            ui_standalone.resize_streaming(1, 1)
        ui_standalone.shutdown_streaming()

        self.fake_ui.init_streaming_result = False
        with self.assertRaises(RuntimeError):
            ui_standalone.init_streaming(320, 240)

        self.fake_ui.init_streaming_result = True
        with mock.patch("atexit.register") as register:
            ui_standalone.init_streaming(320, 240)
        register.assert_called_once_with(ui_standalone.shutdown_streaming)
        with self.assertRaises(RuntimeError):
            ui_standalone.init_streaming(320, 240)

        self.assertTrue(ui_standalone.streaming_tick())
        self.assertEqual(ui_standalone.get_streaming_gl_texture(), 101)
        self.assertEqual(ui_standalone.get_streaming_size(), (1920, 1080))
        self.assertEqual(ui_standalone.get_streaming_cuda_ptr(), 202)
        self.assertEqual(ui_standalone.get_streaming_cuda_pitch(), 303)
        self.assertEqual(ui_standalone.get_streaming_cuda_buffer(), (202, 303))
        self.assertEqual(ui_standalone.get_streaming_format(), "rgba8")
        self.assertTrue(ui_standalone.is_streaming_cuda_available())
        ui_standalone.streaming_sync()
        self.assertEqual(ui_standalone.get_streaming_cuda_event(), 404)

        self.fake_ui.resize_streaming_result = False
        with self.assertRaises(RuntimeError):
            ui_standalone.resize_streaming(640, 480)
        self.fake_ui.resize_streaming_result = True
        ui_standalone.resize_streaming(640, 480)
        self.assertIn(("resize_streaming", 640, 480), self.fake_ui.calls)

        ui_standalone.shutdown_streaming()
        self.assertFalse(ui_standalone._streaming_initialized)
        self.assertIn(("shutdown_streaming",), self.fake_ui.calls)


@unittest.skipUnless(_HAVE_UI, "omni.ui_scene not available")
class TestGestureBindings(unittest.TestCase):
    def test_parse_binding_buttons_modifiers_and_invalid_token(self):
        bindings = gesture_bindings.GestureBindings({})
        binding = bindings.parse_binding("LeftButton RightButton MiddleButton Shift Ctrl Alt Super Any")
        self.assertEqual(binding.mouse_buttons, [0, 1, 2])
        self.assertEqual(binding.modifiers, 0xFFFFFFFF)
        with self.assertRaises(RuntimeError):
            bindings.parse_binding("LeftButton Unknown")

    def test_instantiators_from_callable_dict_module_globals_and_failures(self):
        class DemoGesture:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        module = types.ModuleType("gesture_test_module")
        module.DemoGesture = DemoGesture
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)

        self.assertIs(gesture_bindings.GestureBindings({})._get_instantiator(DemoGesture), DemoGesture)
        self.assertIs(
            gesture_bindings.GestureBindings({}, gesture_module={"DemoGesture": DemoGesture})._get_instantiator("DemoGesture"),
            DemoGesture,
        )
        self.assertIs(
            gesture_bindings.GestureBindings({}, gesture_module=module.__name__)._get_instantiator("DemoGesture"),
            DemoGesture,
        )
        self.assertIs(
            gesture_bindings.GestureBindings({})._get_instantiator(f"{module.__name__}.DemoGesture"),
            DemoGesture,
        )

        gesture_bindings.GlobalGestureForTest = DemoGesture
        self.addCleanup(delattr, gesture_bindings, "GlobalGestureForTest")
        self.assertIs(gesture_bindings.GestureBindings({})._get_instantiator("GlobalGestureForTest"), DemoGesture)

        with mock.patch.object(gesture_bindings, "_log_error") as log_error:
            self.assertIsNone(gesture_bindings.GestureBindings({}, gesture_module="missing.module")._get_instantiator("DemoGesture"))
            self.assertIsNone(gesture_bindings.GestureBindings({}, gesture_module=module.__name__)._get_instantiator("Missing"))
            module.NotCallable = object()
            self.assertIsNone(gesture_bindings.GestureBindings({}, gesture_module=module.__name__)._get_instantiator("NotCallable"))
            self.assertIsNone(gesture_bindings.GestureBindings({})._get_instantiator("MissingGlobal"))
        self.assertEqual(log_error.call_count, 4)

    def test_parse_bindings_ignore_and_error_paths(self):
        class DemoGesture:
            def __init__(self, mouse_buttons, modifiers, label=None):
                self.mouse_buttons = mouse_buttons
                self.modifiers = modifiers
                self.label = label

        module = types.SimpleNamespace(DemoGesture=DemoGesture, BadBinding=DemoGesture)
        bindings = gesture_bindings.GestureBindings(
            {
                "DemoGesture": "LeftButton Shift",
                "Ignored": "RightButton",
                "BadBinding": "Unknown",
                "Missing": "LeftButton",
            },
            gesture_module=module,
        )
        self.assertIn("DemoGesture", bindings)
        self.assertEqual(bindings["DemoGesture"], "LeftButton Shift")

        with mock.patch.object(gesture_bindings, "_log_error") as log_error:
            with mock.patch.object(gesture_bindings, "_log_warn") as log_warn:
                parsed = list(bindings.parse_bindings(gesture_ignore_list=["Ignored"], label="ok"))
        self.assertEqual(log_error.call_count, 2)
        log_warn.assert_called_once()
        self.assertEqual(len(parsed), 1)
        gesture, binding = parsed[0]
        self.assertIsInstance(gesture, DemoGesture)
        self.assertEqual(gesture.mouse_buttons, [0])
        self.assertEqual(gesture.modifiers, 1)
        self.assertEqual(gesture.label, "ok")
        self.assertEqual(binding.mouse_buttons, [0])

    def test_string_bindings_in_standalone_warn_and_empty(self):
        if gesture_bindings._HAVE_CARB:
            self.skipTest("standalone warning branch only")
        with self.assertLogs(gesture_bindings._log, level="WARNING") as logs:
            bindings = gesture_bindings.GestureBindings("/settings/path")
        self.assertNotIn("anything", bindings)
        self.assertIn("cannot be resolved", "\n".join(logs.output))

    def test_manipulator_rebuild_bindings_and_destroy(self):
        class DemoGesture:
            def __init__(self, mouse_buttons, modifiers):
                self.mouse_buttons = mouse_buttons
                self.modifiers = modifiers

        class DemoManipulator(gesture_bindings.GestureBindingManipulator):
            invalidated = 0

            def invalidate(self):
                self.invalidated += 1

            def get_default_bindings(self):
                return {"DemoGesture": "LeftButton"}

        manipulator = DemoManipulator()
        gestures = manipulator.get_gestures(gesture_module={"DemoGesture": DemoGesture})
        self.assertEqual(len(gestures), 1)
        self.assertEqual(gestures[0].mouse_buttons, [0])

        manipulator.bindings = {"DemoGesture": "RightButton Ctrl"}
        gestures = manipulator.get_gestures(gesture_module={"DemoGesture": DemoGesture})
        self.assertEqual(gestures[0].mouse_buttons, [1])
        self.assertEqual(gestures[0].modifiers, 2)

        manipulator.destroy()


@unittest.skipUnless(_HAVE_UI, "omni.ui_scene not available")
class TestSceneCompatibilityHelpers(unittest.TestCase):
    def test_add_compatibility_for_property_method_and_alias(self):
        class Demo:
            def __init__(self):
                self.payload = "initial"

            @property
            def gesture_payload(self):
                return self.payload

            @gesture_payload.setter
            def gesture_payload(self, value):
                self.payload = value

            def get_gesture_payload(self):
                return self.payload

        scene_compatibility._add_compatibility(Demo, "intersection", "gesture_payload")
        scene_compatibility._add_compatibility(Demo, "get_intersection", "get_gesture_payload")
        scene_compatibility._add_compatibility(Demo, "Intersection", "gesture_payload", False)

        demo = Demo()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            self.assertEqual(demo.intersection, "initial")
            demo.intersection = "changed"
            self.assertEqual(demo.get_intersection(), "changed")
        self.assertEqual(len(caught), 3)
        self.assertEqual(Demo.Intersection.fget, Demo.gesture_payload.fget)

    def test_add_intersection_attributes_uses_scene_namespace(self):
        def make_cls(name):
            return type(
                name,
                (),
                {
                    "gesture_payload": property(lambda self: "payload", lambda self, value: None),
                    "get_gesture_payload": lambda self: "payload",
                    "GesturePayload": object,
                },
            )

        fake_scene = types.SimpleNamespace(
            AbstractGesture=make_cls("AbstractGesture"),
            AbstractShape=make_cls("AbstractShape"),
            Arc=make_cls("Arc"),
            Line=make_cls("Line"),
            Points=make_cls("Points"),
            PolygonMesh=make_cls("PolygonMesh"),
            Rectangle=make_cls("Rectangle"),
            Screen=make_cls("Screen"),
        )

        with mock.patch.object(scene_compatibility, "sc", fake_scene):
            scene_compatibility.add_intersection_attributes()

        for cls in [
            fake_scene.AbstractGesture,
            fake_scene.AbstractShape,
            fake_scene.Arc,
            fake_scene.Line,
            fake_scene.Points,
            fake_scene.PolygonMesh,
            fake_scene.Rectangle,
            fake_scene.Screen,
        ]:
            self.assertTrue(hasattr(cls, "intersection"))
            self.assertTrue(hasattr(cls, "get_intersection"))
        self.assertIs(fake_scene.AbstractGesture.Intersection, fake_scene.AbstractGesture.GesturePayload)


if __name__ == "__main__":
    unittest.main()
