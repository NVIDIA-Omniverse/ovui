# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""3D viewport widget with a real tool toolbar and layered viewport body.

ViewportWidget hosts the RTX render surface and delegates GPU calls to
the RendererAdapter. Layer 2 is a SceneView for camera and pick gestures.
"""

import inspect
from typing import Any, Callable, Optional

import omni.ui as ui
from omni.ui_scene import scene as sc
from ovui_data_adapters.common import (
    VIEWPORT_CAMERA_POSE_SOURCE,
    BoundCameraPose,
    RendererAdapter,
    is_viewport_camera_pose_change_event,
)

from ovwidgets.common.managed_window import ManagedWindow
from ovwidgets.common.menu import create_flat_menu
from ovwidgets.common.selection import SelectionChangedEvent
from ovwidgets.viewport import _livestream_status_overlay as _ls_overlay
from ovwidgets.viewport.camera_controller import CameraController
from ovwidgets.viewport.camera_flight_keyboard import (
    FLY_SPEED_SETTING,
    FlightModeKeyboard,
)
from ovwidgets.viewport.camera_inertia import (
    DEFAULT_TIME_CONSTANT as DEFAULT_TUMBLE_INERTIA,
)
from ovwidgets.viewport.camera_inertia import (
    TUMBLE_INERTIA_SETTING,
    TumbleInertia,
)
from ovwidgets.viewport.camera_manipulator import (
    CameraManipulator,
    CameraManipulatorModel,
)
from ovwidgets.viewport.camera_navigation_state import CameraNavigationState
from ovwidgets.viewport.image_bridge import ImageBridge
from ovwidgets.viewport.manipulator_registry import ACTIVE_TOOL_SETTING, ToolRegistry
from ovwidgets.viewport.pick_gesture import (
    MOD_CTRL,
    MOD_NONE,
    MOD_SHIFT,
    GizmoAwarePickManager,
    PickGesture,
    PickRectGesture,
)
from ovwidgets.viewport.prim_transform_model import PrimTransformModel
from ovwidgets.viewport.transform_manipulator import (
    TOOL_ROTATE,
    TOOL_SCALE,
    TOOL_TRANSLATE,
    VALID_TOOLS,
    TransformManipulator,
)

_TOOLBAR_TOOL_SPECS = (
    (TOOL_TRANSLATE, "Move", "W", "viewport_tool_move"),
    (TOOL_ROTATE, "Rotate", "E", "viewport_tool_rotate"),
    (TOOL_SCALE, "Scale", "R", "viewport_tool_scale"),
)
_TOOLBAR_CAMERA_KEY = "camera"
_TOOLBAR_CAMERA_MENU_TITLE = "Camera"
_TOOLBAR_NO_CAMERAS_LABEL = "(no cameras)"
_TOOLBAR_RENDER_PRODUCT_KEY = "render_product"
_TOOLBAR_RENDER_PRODUCT_MENU_TITLE = "Render Product"
_TOOLBAR_NO_RENDER_PRODUCTS_LABEL = "(no render products)"
_TOOLBAR_ICON_PROVIDERS: dict[str, "ui.RasterImageProvider"] = {}


def _toolbar_icon_provider(path: str) -> "ui.RasterImageProvider":
    provider = _TOOLBAR_ICON_PROVIDERS.get(path)
    if provider is None:
        provider = ui.RasterImageProvider(path)
        _TOOLBAR_ICON_PROVIDERS[path] = provider
    return provider


class ViewportWidget(ManagedWindow):
    """3D viewport panel — toolbar row + rendered image / SceneView / HUD stack."""

    MAX_FPS_FOREGROUND = 60
    MAX_FPS_BACKGROUND = 10

    # Clamp the render resolution before handing it to the renderer adapter.
    # Floor at 64×64 so the renderer always has a sensible buffer to work
    # with (matches the viewport behavior); ceiling at 4K UHD to avoid
    # accidental gigantic GPU allocations when a user maximises onto a
    # high-DPI display. ImageWithProvider uses IWP_PRESERVE_ASPECT_FIT so
    # the on-screen image still fills the widget when these clamps kick in.
    MIN_RENDER_WIDTH = 64
    MIN_RENDER_HEIGHT = 64
    MAX_RENDER_WIDTH = 3840
    MAX_RENDER_HEIGHT = 2160
    TOOLBAR_HEIGHT = 24
    TOOLBAR_BUTTON_SIZE = 20
    TOOLBAR_ICON_SIZE = 13
    CAMERA_NAVIGATION_SETTLE_FRAMES = 2

    def __init__(
        self,
        services: Any = None,
        renderer: Optional[RendererAdapter] = None,
        bus: Any = None,
        on_drop_fn: Optional[Callable[[Any], None]] = None,
        stage_adapter_provider: Optional[Callable[[], Any]] = None,
        window_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        # Step 11.3/13: viewport seam atomic conversion.
        # ``services`` replaces the old ``app`` parameter. The two
        # other widget-injection seams are explicit per-widget
        # callbacks rather than members of the WidgetServices Protocol
        # (which stays at exactly three members per Plan Rev 2 §5.20):
        #
        # * ``on_drop_fn(event) -> None`` — single-argument drop
        #   delegate. Application binds ``target="viewport"`` via a
        #   lambda at the call site so the viewport widget itself
        #   has no notion of ``target`` strings.
        # * ``stage_adapter_provider() -> StageAdapter | None`` —
        #   bound method on Application that returns the live
        #   ``_stage_adapter`` for bbox / frame-selected camera
        #   computations. A lambda wrapping a single attribute access
        #   adds no value; the bound method is the canonical form.
        self._services = services
        self._on_drop_fn = on_drop_fn
        self._stage_adapter_provider = stage_adapter_provider
        self._renderer = renderer
        self._width = 1280
        self._height = 720
        # Shared zero-copy state (strata#16 tier-2). When OVGEAR_ZERO_COPY=1
        # is set, both the renderer and the bridge route LdrColor through a
        # CUDA-mapped pointer; the bridge probes ovui's GPU backend on the
        # first frame and latches to tier-1 if the standalone build no-ops
        # set_bytes_data_from_gpu. If the renderer was built externally and
        # already carries its own state, reuse it; otherwise install ours.
        from ovui_data_adapters.common import ZeroCopyState
        self._zero_copy_state = ZeroCopyState.from_env()
        self._attach_zero_copy_state(renderer, adopt_existing=True)
        self._bridge = ImageBridge(self._width, self._height, state=self._zero_copy_state)
        self._camera = CameraController()
        self._camera_model = CameraManipulatorModel()
        # Flight-mode keyboard — Step B.3. Constructed here (not in
        # ``_build_ui``) so the application can wire its key dispatcher
        # to ``_flight_keyboard.handle_key_event`` before the first
        # frame. The gesture list it polls is populated in ``_build_ui``
        # once the tumble/look gestures exist.
        # Step 11.3: read FLY_SPEED from the explicit
        # ``ovwidgets.common.settings.Settings`` singleton wired
        # by ``Application.__init__`` in Step 10. Headless / mock
        # paths without a registered Settings fall back to the
        # default 1.0.
        fly_speed = 1.0
        try:
            from ovwidgets.common.settings import Settings
            _settings = Settings._instance
            if _settings is not None:
                fly_speed = float(_settings.get(FLY_SPEED_SETTING, 1.0))
        except (AttributeError, TypeError, ValueError):
            fly_speed = 1.0
        self._flight_keyboard = FlightModeKeyboard(
            self._camera, model=self._camera_model, base_speed=fly_speed
        )
        # Tumble inertia — Step B.4. The ``tumble_inertia`` model item
        # drives the time constant so live setting changes propagate
        # without reinstancing. A setting value of 0.0 disables inertia
        # (``TumbleInertia.is_enabled`` returns False and ``start`` is
        # a no-op).
        # Step 11.3: read TUMBLE_INERTIA from the explicit
        # ``ovwidgets.common.settings.Settings`` singleton.
        tumble_inertia_s = DEFAULT_TUMBLE_INERTIA
        try:
            from ovwidgets.common.settings import Settings
            _settings = Settings._instance
            if _settings is not None:
                tumble_inertia_s = float(
                    _settings.get(TUMBLE_INERTIA_SETTING, DEFAULT_TUMBLE_INERTIA)
                )
        except (AttributeError, TypeError, ValueError):
            tumble_inertia_s = DEFAULT_TUMBLE_INERTIA
        self._camera_model.set_floats("tumble_inertia", [tumble_inertia_s])
        self._tumble_inertia = TumbleInertia(
            self._camera, model=self._camera_model
        )
        self._camera_manipulator: Optional[CameraManipulator] = None
        self._transform_manipulator: Optional[TransformManipulator] = None
        # Construct the transform model eagerly in ``__init__`` so it is
        # already present when :meth:`Application._load_stage` calls
        # :meth:`attach_stage`. Before this moved out of ``_build_ui``,
        # the frame's build function ran lazily on first render, so stage
        # load routinely happened while the model was still ``None`` —
        # ``attach_adapters`` was silently skipped and every
        # ``get_pivot_world()`` returned the fallback origin, parking the
        # gizmo at (0,0,0) regardless of selection. The model is pure
        # data (no UI), so there is no reason to tie it to frame build.
        self._transform_model: Optional[PrimTransformModel] = PrimTransformModel()
        self._tool_registry: Optional[ToolRegistry] = None
        # Last-rebuilt gizmo world-scale; used by ``_on_frame`` to decide
        # whether the camera moved enough since the previous rebuild to
        # justify invalidating the manipulator. Invalidating blindly
        # every frame destroys the shapes the gesture system captured
        # mouse input against, which broke drag and hover continuity.
        self._last_gizmo_scale: float = 0.0
        self._image: Optional[Any] = None
        self._scene_view: Optional[Any] = None
        self._scene_name: Optional[str] = None
        self._prim_count: int = 0
        self._last_fps: Optional[float] = None
        self._last_resolution: Optional[tuple[int, int]] = None
        self._fps_label: Optional[Any] = None
        self._prim_count_label: Optional[Any] = None
        self._scene_row: Optional[Any] = None
        self._fps_res_row: Optional[Any] = None
        self._scene_value_label: Optional[Any] = None
        self._fps_value_label: Optional[Any] = None
        self._resolution_label: Optional[Any] = None
        self._resolution_value_label: Optional[Any] = None
        self._fps_res_separator_label: Optional[Any] = None
        # Step 1.7: livestream status overlay. Top-right HUD block,
        # hidden when the renderer has no livestream tap (i.e.
        # ``OVGEAR_LIVESTREAM`` is unset or the SDK is missing).
        self._livestream_row: Optional[Any] = None
        self._livestream_value_label: Optional[Any] = None
        self._toolbar_frame: Optional[Any] = None
        self._toolbar_buttons: dict[str, Any] = {}
        self._toolbar_button_backgrounds: dict[str, Any] = {}
        self._camera_menu: Optional[Any] = None
        self._active_camera_path: Optional[str] = None
        self._last_authored_camera_signature: Optional[tuple[Any, ...]] = None
        self._committing_active_camera_pose = False
        self._camera_navigation_state = CameraNavigationState(
            stable_frame_threshold=self.CAMERA_NAVIGATION_SETTLE_FRAMES
        )
        self._render_product_menu: Optional[Any] = None
        self._active_render_product_path: Optional[str] = None
        self._pushing_to_bus = False
        self._receiving_from_bus = False
        # Step 11.3: ``services.selection_bus`` is the WidgetServices
        # member; bus override still wins.
        self._bus = bus or (
            services.selection_bus if services is not None else None
        )
        self._bus_sub = None
        self._manipulator_registry = None
        if self._bus:
            self._bus_sub = self._bus.subscribe(self._on_bus_selection_changed)
        super().__init__("Viewport", width=800, height=600, **(window_kwargs or {}))
        # Content-Browser Step 40 — per-window drop handler. Wires the
        # viewport's :class:`ui.Window` to a shim that delegates back to
        # :meth:`Application._on_drop` with ``target="viewport"`` so a
        # ``.usd`` dragged from the content browser opens as the active
        # stage (the content browser behavior). ``hasattr`` guards
        # ovui test builds that expose :class:`ui.Window` without
        # :meth:`set_drop_fn`.
        if self._window is not None and hasattr(self._window, "set_drop_fn"):
            self._window.set_drop_fn(self._on_drop)

    def _on_drop(self, event: Any) -> None:
        """Forward a viewport drop event to :meth:`Application._on_drop`.

        ovui delivers :class:`WidgetMouseDropEvent` whose ``mime_data``
        is the ``"\\n"``-joined URL payload the drag source produced
        (the content browser's internal / external drag MIME format —
        see :meth:`FileBrowserWidget._tree_drag_payload`). The widget
        itself has no USD-open surface; it delegates to the
        application-level dispatcher so the target-branch + stage-load
        logic stays in one place. Silent no-op when no application is
        wired (pure-test viewport instances).
        """
        # Step 11.3: route the drop through the explicit
        # ``on_drop_fn`` callback. Application binds ``target=
        # "viewport"`` via lambda at the call site so the
        # viewport widget no longer reaches into the app object.
        if self._on_drop_fn is not None:
            self._on_drop_fn(event)

    def _build_ui(self) -> None:
        self._toolbar_buttons = {}
        self._toolbar_button_backgrounds = {}
        with ui.ZStack():
            with ui.ZStack():
                # Layer 1: rendered image via ByteImageProvider
                self._image = ui.ImageWithProvider(
                    self._bridge.provider,
                    fill_policy=ui.IwpFillPolicy.IWP_PRESERVE_ASPECT_FIT,
                    style_type_name_override="ViewportWidget.Image",
                )
                # Layer 2: SceneView for camera and pick gestures. The
                # ``CameraManipulator`` (Step B.5) owns the four camera
                # gestures plus the RMB-binding on ``self._flight_keyboard``
                # and forwards tumble-release velocity into
                # ``self._tumble_inertia``; its ``on_build`` will emit the
                # gesture-bearing ``sc.Screen`` on the next draw.
                self._scene_view = sc.SceneView()
                # Let toolbar button ``content_clipping`` stacks shield
                # clicks from the SceneView so opening a menu does not also
                # select/manipulate viewport content underneath.
                self._scene_view.child_windows_input = False
                # D.2 / D.3 — point pick and marquee each instantiate three
                # variants, one per selection mode, so ``omni.ui_scene``'s
                # modifier-aware dispatch routes the click / drag to the
                # right callback. We build callbacks via ``_make_*_callback``
                # so each variant carries its own selection mode rather than
                # stashing state on the widget between event and callback.
                pick_replace = PickGesture(
                    callback=self._make_pick_callback("replace"),
                    modifiers=MOD_NONE,
                )
                pick_add = PickGesture(
                    callback=self._make_pick_callback("add"),
                    modifiers=MOD_SHIFT,
                )
                pick_remove = PickGesture(
                    callback=self._make_pick_callback("remove"),
                    modifiers=MOD_CTRL,
                )
                pick_rect_replace = PickRectGesture(
                    callback=self._make_pick_rect_callback("replace"),
                    modifiers=MOD_NONE,
                )
                pick_rect_add = PickRectGesture(
                    callback=self._make_pick_rect_callback("add"),
                    modifiers=MOD_SHIFT,
                )
                pick_rect_remove = PickRectGesture(
                    callback=self._make_pick_rect_callback("remove"),
                    modifiers=MOD_CTRL,
                )
                # Tie-breaker registry for the LMB pick / marquee gestures
                # and the LMB gizmo drags. The manager is stashed as a
                # plain attribute on each pick gesture (assigning it as
                # ``.manager`` starves the gizmo's drag of on-move events
                # in a way we have not fully diagnosed yet). Each pick
                # gesture reaches back to it from ``_process_ended`` and
                # skips the selection mutation when a sibling gizmo drag
                # captured the same mouse-down.
                self._pick_manager = GizmoAwarePickManager()
                for g in (
                    pick_replace, pick_add, pick_remove,
                    pick_rect_replace, pick_rect_add, pick_rect_remove,
                ):
                    g._viewport_pick_manager = self._pick_manager
                # ``PrimTransformModel`` is constructed eagerly in
                # ``__init__`` so :meth:`Application._load_stage` can call
                # :meth:`attach_stage` before the viewport's frame build
                # runs (Step C.2 — Step C.5 will fold the SelectionBus→model
                # subscription into the model itself).
                initial_tool = self._get_active_tool()
                if initial_tool not in VALID_TOOLS:
                    initial_tool = TOOL_TRANSLATE
                with self._scene_view.scene:
                    self._camera_manipulator = CameraManipulator(
                        camera_controller=self._camera,
                        model=self._camera_model,
                        viewport_size_fn=self._get_viewport_size,
                        flight_keyboard=self._flight_keyboard,
                        tumble_inertia=self._tumble_inertia,
                    )
                    self._transform_manipulator = TransformManipulator(
                        model=self._transform_model,
                        tool=initial_tool,
                        pivot_fn=self._transform_model.get_pivot_world,
                        size_fn=self._get_gizmo_world_scale,
                    )
                    # Register the gizmo's persistent drag gestures with the
                    # pick manager. The manager exposes ``set_gizmo_gestures``
                    # for callers that want to add custom tie-breaking; in
                    # the default config the list is kept for introspection
                    # only — scene-graph ordering handles dispatch priority.
                    self._pick_manager.set_gizmo_gestures([
                        *self._transform_manipulator._translate_drags,
                        *self._transform_manipulator._rotate_drags,
                        *self._transform_manipulator._scale_drags,
                        self._transform_manipulator._uniform_scale_drag,
                    ])
                    # Screen with selection gestures added LAST — under
                    # ``omni.ui_scene``'s LIFO gesture-dispatch, an earlier
                    # shape gesture (the gizmo arrow lines) captures LMB
                    # before this Screen's marquee gets a turn, so a drag
                    # on an axis translates the prim instead of drawing a
                    # selection rectangle. With the Screen added first the
                    # pick gestures ended up "owning" the drag and the
                    # gizmo's ``on_began`` fired but its ``on_ended`` fired
                    # immediately afterwards, losing every ``on_changed``
                    # in between — the "drag only changes selection" bug.
                    sc.Screen(
                        gestures=[
                            pick_replace,
                            pick_add,
                            pick_remove,
                            pick_rect_replace,
                            pick_rect_add,
                            pick_rect_remove,
                        ]
                    )
                # ``ToolRegistry`` reads the ``viewport.manipulator.active_tool``
                # setting, subscribes to changes, and converts W/E/R key presses
                # into tool switches on the attached manipulator. Constructed
                # outside the scene block because it isn't scene geometry.
                settings = self._resolve_settings()
                self._tool_registry = ToolRegistry(
                    settings=settings,
                    manipulator=self._transform_manipulator,
                    on_tool_changed=self._on_tool_changed,
                )
                self._refresh_toolbar_state()
                # Layer 3: HUD overlay
                self._build_hud()
            # Existing transform-tool controls, restyled as a transparent
            # overlay instead of a separate boxed toolbar band.
            self._build_toolbar_row()

    def _iter_toolbar_tool_specs(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(spec for spec in _TOOLBAR_TOOL_SPECS if spec[0] in VALID_TOOLS)

    def _get_active_tool(self) -> Optional[str]:
        if self._tool_registry is not None:
            return getattr(self._tool_registry, "active_tool", None)
        if self._transform_manipulator is not None:
            return getattr(self._transform_manipulator, "tool", None)
        settings = self._resolve_settings()
        if settings is not None:
            try:
                raw = settings.get(ACTIVE_TOOL_SETTING, TOOL_TRANSLATE)
            except (AttributeError, TypeError):
                raw = TOOL_TRANSLATE
            if raw in VALID_TOOLS:
                return raw
        return TOOL_TRANSLATE

    def _build_toolbar_row(self) -> None:
        """Build the real-tools-only viewport toolbar.

        Step 21 intentionally exposes only controls backed by existing
        viewport state. Today that is the transform manipulator's move /
        rotate / scale modes plus the stage-camera and render-product
        selectors; there is no separate select tool, shading mode, grid
        toggle, or lock API to wire here.
        """
        specs = self._iter_toolbar_tool_specs()
        if not specs:
            self._toolbar_frame = None
            return

        from ovwidgets.common.style.urls import get_icon_path

        active_tool = self._get_active_tool()
        self._toolbar_frame = ui.Frame(height=self.TOOLBAR_HEIGHT)
        with self._toolbar_frame:
            with ui.ZStack(style_type_name_override="Viewport.Toolbar"):
                ui.Rectangle(style_type_name_override="Viewport.Toolbar")
                with ui.HStack(height=self.TOOLBAR_HEIGHT, spacing=0):
                    ui.Spacer(width=10)
                    for tool, label, hotkey, icon_name in specs:
                        icon_path = get_icon_path(icon_name)
                        button_name = f"viewport_toolbar_{tool}"
                        with ui.ZStack(
                            width=self.TOOLBAR_BUTTON_SIZE,
                            height=self.TOOLBAR_BUTTON_SIZE,
                            content_clipping=True,
                        ):
                            background = ui.Rectangle(
                                name="active" if tool == active_tool else "",
                                style_type_name_override="Viewport.Toolbar.Button",
                            )
                            with ui.VStack(spacing=0):
                                ui.Spacer()
                                with ui.HStack(height=self.TOOLBAR_ICON_SIZE, spacing=0):
                                    ui.Spacer()
                                    ui.ImageWithProvider(
                                        _toolbar_icon_provider(icon_path),
                                        width=self.TOOLBAR_ICON_SIZE,
                                        height=self.TOOLBAR_ICON_SIZE,
                                        enabled=False,
                                        opaque_for_mouse_events=False,
                                        style_type_name_override="Viewport.Toolbar.Icon",
                                    )
                                    ui.Spacer()
                                ui.Spacer()
                            button = ui.InvisibleButton(
                                width=self.TOOLBAR_BUTTON_SIZE,
                                height=self.TOOLBAR_BUTTON_SIZE,
                                identifier=button_name,
                                tooltip=f"{label} ({hotkey})",
                            )
                            button.set_clicked_fn(
                                lambda t=tool: self._on_toolbar_tool_clicked(t)
                            )
                        self._toolbar_buttons[tool] = button
                        self._toolbar_button_backgrounds[tool] = background
                        ui.Spacer(width=3)
                    camera_icon_path = get_icon_path("prim_camera")
                    with ui.ZStack(
                        width=self.TOOLBAR_BUTTON_SIZE,
                        height=self.TOOLBAR_BUTTON_SIZE,
                        content_clipping=True,
                    ):
                        background = ui.Rectangle(
                            style_type_name_override="Viewport.Toolbar.Button",
                        )
                        with ui.VStack(spacing=0):
                            ui.Spacer()
                            with ui.HStack(height=self.TOOLBAR_ICON_SIZE, spacing=0):
                                ui.Spacer()
                                ui.ImageWithProvider(
                                    _toolbar_icon_provider(camera_icon_path),
                                    width=self.TOOLBAR_ICON_SIZE,
                                    height=self.TOOLBAR_ICON_SIZE,
                                    enabled=False,
                                    opaque_for_mouse_events=False,
                                    style_type_name_override="Viewport.Toolbar.Icon",
                                )
                                ui.Spacer()
                            ui.Spacer()
                        button = ui.InvisibleButton(
                            width=self.TOOLBAR_BUTTON_SIZE,
                            height=self.TOOLBAR_BUTTON_SIZE,
                            identifier="viewport_toolbar_camera",
                            tooltip="Camera",
                        )
                        button.set_clicked_fn(self._on_camera_menu_button_clicked)
                    self._toolbar_buttons[_TOOLBAR_CAMERA_KEY] = button
                    self._toolbar_button_backgrounds[_TOOLBAR_CAMERA_KEY] = background
                    ui.Spacer(width=3)
                    render_product_icon_path = get_icon_path("asset_image")
                    with ui.ZStack(
                        width=self.TOOLBAR_BUTTON_SIZE,
                        height=self.TOOLBAR_BUTTON_SIZE,
                        content_clipping=True,
                    ):
                        background = ui.Rectangle(
                            style_type_name_override="Viewport.Toolbar.Button",
                        )
                        with ui.VStack(spacing=0):
                            ui.Spacer()
                            with ui.HStack(height=self.TOOLBAR_ICON_SIZE, spacing=0):
                                ui.Spacer()
                                ui.ImageWithProvider(
                                    _toolbar_icon_provider(render_product_icon_path),
                                    width=self.TOOLBAR_ICON_SIZE,
                                    height=self.TOOLBAR_ICON_SIZE,
                                    enabled=False,
                                    opaque_for_mouse_events=False,
                                    style_type_name_override="Viewport.Toolbar.Icon",
                                )
                                ui.Spacer()
                            ui.Spacer()
                        button = ui.InvisibleButton(
                            width=self.TOOLBAR_BUTTON_SIZE,
                            height=self.TOOLBAR_BUTTON_SIZE,
                            identifier="viewport_toolbar_render_product",
                            tooltip="Render Product",
                        )
                        button.set_clicked_fn(
                            self._on_render_product_menu_button_clicked
                        )
                    self._toolbar_buttons[_TOOLBAR_RENDER_PRODUCT_KEY] = button
                    self._toolbar_button_backgrounds[
                        _TOOLBAR_RENDER_PRODUCT_KEY
                    ] = background
                    ui.Spacer(width=3)
                    ui.Spacer()

    def _on_toolbar_tool_clicked(self, tool: str) -> None:
        if tool not in VALID_TOOLS:
            return
        if self._tool_registry is not None:
            self._tool_registry.set_active_tool(tool)
        elif self._transform_manipulator is not None:
            self._transform_manipulator.tool = tool
        else:
            settings = self._resolve_settings()
            if settings is not None:
                try:
                    settings.set(ACTIVE_TOOL_SETTING, tool)
                except AttributeError:
                    pass
        self._refresh_toolbar_state()

    def _on_tool_changed(self, _old_tool: str, _new_tool: str) -> None:
        self._refresh_toolbar_state()

    def _refresh_toolbar_state(self) -> None:
        active_tool = self._get_active_tool()
        for tool, background in self._toolbar_button_backgrounds.items():
            try:
                background.name = "active" if tool == active_tool else ""
            except Exception:
                pass

    def _get_stage_adapter(self) -> Any:
        if self._stage_adapter_provider is None:
            return None
        try:
            return self._stage_adapter_provider()
        except Exception:
            return None

    def _list_camera_choices(self) -> tuple[Any, ...]:
        adapter = self._get_stage_adapter()
        if adapter is None:
            return ()
        try:
            return tuple(adapter.list_cameras())
        except Exception:
            return ()

    def _list_render_product_choices(self) -> tuple[Any, ...]:
        adapter = self._get_stage_adapter()
        if adapter is None:
            return ()
        try:
            return tuple(adapter.list_render_products())
        except Exception:
            return ()

    def _stage_choice_label(self, choice: Any) -> str:
        display_name = str(getattr(choice, "display_name", "") or "").strip()
        if display_name:
            return display_name
        return str(getattr(choice, "path", "") or "")

    def _destroy_camera_menu(self) -> None:
        menu = self._camera_menu
        if menu is None:
            return
        try:
            menu.destroy()
        except Exception:
            try:
                menu.hide()
            except Exception:
                pass
        self._camera_menu = None

    def _destroy_render_product_menu(self) -> None:
        menu = self._render_product_menu
        if menu is None:
            return
        try:
            menu.destroy()
        except Exception:
            try:
                menu.hide()
            except Exception:
                pass
        self._render_product_menu = None

    def _on_camera_menu_button_clicked(self) -> None:
        button = self._toolbar_buttons.get(_TOOLBAR_CAMERA_KEY)
        if button is None:
            return
        x = float(getattr(button, "screen_position_x", 0.0) or 0.0)
        y = float(
            (getattr(button, "screen_position_y", 0.0) or 0.0)
            + (getattr(button, "computed_height", self.TOOLBAR_BUTTON_SIZE) or 0.0)
        )
        self._show_camera_menu_at(x, y)

    def _show_camera_menu_at(self, x: float, y: float) -> Any:
        self._destroy_camera_menu()
        menu = create_flat_menu(_TOOLBAR_CAMERA_MENU_TITLE, ui_module=ui)
        self._camera_menu = menu
        choices = self._list_camera_choices()
        with menu:
            added_item = False
            if choices:
                for choice in choices:
                    path = str(getattr(choice, "path", "") or "")
                    if not path:
                        continue
                    checked = path == self._active_camera_path
                    ui.MenuItem(
                        self._stage_choice_label(choice),
                        checkable=True,
                        checked=checked,
                        triggered_fn=lambda p=path: self._select_camera_path(p),
                    )
                    added_item = True
            if not added_item:
                ui.MenuItem(_TOOLBAR_NO_CAMERAS_LABEL, enabled=False)
        menu.show_at(float(x), float(y))
        return menu

    def _set_renderer_camera_path_if_supported(self, path: Optional[str]) -> bool:
        """Return False only when a concrete renderer selector rejects ``path``."""
        setter = getattr(self._renderer, "set_active_camera_path", None)
        if not callable(setter):
            return True
        if getattr(setter, "__func__", None) is RendererAdapter.set_active_camera_path:
            return True
        try:
            return bool(setter(path))
        except Exception:
            return False

    def _select_camera_path(self, path: str) -> bool:
        if not isinstance(path, str) or not path:
            return False
        adapter = self._get_stage_adapter()
        if adapter is None:
            return False
        try:
            pose = adapter.read_camera_pose(path)
        except Exception:
            return False
        previous_path = self._active_camera_path
        # Bind the renderer to the selected camera before recording the
        # widget state. Supporting renderers can reject invalid prim paths;
        # when that happens the menu must not claim a camera that the
        # renderer did not actually bind. Minimal/mock renderers inherit
        # the base no-op selector and remain permissive for pure widget
        # tests.
        if not self._set_renderer_camera_path_if_supported(path):
            return False
        if previous_path and previous_path != path:
            self._commit_active_camera_pose_if_dirty()
        if not self.apply_camera_pose(pose):
            self._set_renderer_camera_path_if_supported(previous_path)
            return False
        self._active_camera_path = path
        self._last_authored_camera_signature = self._camera_author_signature(path)
        self._reset_camera_navigation_state()
        return True

    def _read_renderer_active_render_product_path(self) -> Optional[str]:
        renderer = self._renderer
        getter = getattr(renderer, "get_active_render_product_path", None)
        if not callable(getter):
            return self._active_render_product_path
        try:
            path = getter()
        except Exception:
            return self._active_render_product_path
        if path:
            return str(path)
        return self._active_render_product_path

    def _on_render_product_menu_button_clicked(self) -> None:
        button = self._toolbar_buttons.get(_TOOLBAR_RENDER_PRODUCT_KEY)
        if button is None:
            return
        x = float(getattr(button, "screen_position_x", 0.0) or 0.0)
        y = float(
            (getattr(button, "screen_position_y", 0.0) or 0.0)
            + (getattr(button, "computed_height", self.TOOLBAR_BUTTON_SIZE) or 0.0)
        )
        self._show_render_product_menu_at(x, y)

    def _show_render_product_menu_at(self, x: float, y: float) -> Any:
        self._destroy_render_product_menu()
        menu = create_flat_menu(
            _TOOLBAR_RENDER_PRODUCT_MENU_TITLE,
            ui_module=ui,
        )
        self._render_product_menu = menu
        active_path = self._read_renderer_active_render_product_path()
        choices = self._list_render_product_choices()
        with menu:
            if active_path:
                ui.MenuItem(f"Active: {active_path}", enabled=False)
            added_item = False
            if choices:
                for choice in choices:
                    path = str(getattr(choice, "path", "") or "")
                    if not path:
                        continue
                    checked = path == active_path
                    ui.MenuItem(
                        self._stage_choice_label(choice),
                        checkable=True,
                        checked=checked,
                        triggered_fn=lambda p=path: (
                            self._select_render_product_path(p)
                        ),
                    )
                    added_item = True
            if not added_item:
                ui.MenuItem(_TOOLBAR_NO_RENDER_PRODUCTS_LABEL, enabled=False)
        menu.show_at(float(x), float(y))
        return menu

    def _select_render_product_path(self, path: str) -> bool:
        if not isinstance(path, str) or not path:
            return False
        setter = getattr(self._renderer, "set_active_render_product_path", None)
        if not callable(setter):
            return False
        try:
            accepted = bool(setter(path))
        except Exception:
            return False
        if not accepted:
            return False
        self._active_render_product_path = path
        return True

    def _build_hud_label(
        self,
        text: str,
        style: str,
        width: Optional[int] = None,
        alignment: Any = ui.Alignment.LEFT_CENTER,
    ) -> Any:
        kwargs = {
            "alignment": alignment,
            "style_type_name_override": style,
        }
        if width is not None:
            kwargs["width"] = width
        return ui.Label(text, **kwargs)

    def _build_hud_pair(
        self,
        label: str,
        label_width: int = 42,
        value_width: Optional[int] = None,
        right_align_value: bool = False,
    ) -> Any:
        self._build_hud_label(label, "Viewport.HUD.Label", width=label_width)
        ui.Spacer(width=6)
        alignment = ui.Alignment.RIGHT_CENTER if right_align_value else ui.Alignment.LEFT_CENTER
        return self._build_hud_label(
            "",
            "Viewport.HUD.Value",
            width=value_width,
            alignment=alignment,
        )

    def _build_hud(self) -> None:
        with ui.ZStack(style_type_name_override="Viewport.HUD"):
            # Top-left: scene, FPS, and render resolution.
            with ui.VStack(spacing=0):
                ui.Spacer(height=self._get_hud_top_padding())
                with ui.HStack(height=38):
                    ui.Spacer(width=14)
                    with ui.VStack(width=430, spacing=0):
                        self._scene_row = ui.HStack(height=16, spacing=0)
                        with self._scene_row:
                            self._scene_value_label = self._build_hud_pair("SCENE")
                        self._fps_res_row = ui.HStack(height=16, spacing=0)
                        with self._fps_res_row:
                            self._fps_value_label = self._build_hud_pair(
                                "FPS",
                                label_width=28,
                                value_width=30,
                            )
                            ui.Spacer(width=8)
                            self._fps_res_separator_label = self._build_hud_label(
                                "·",
                                "Viewport.HUD.Separator",
                                width=8,
                            )
                            ui.Spacer(width=8)
                            self._resolution_label = self._build_hud_label(
                                "RES",
                                "Viewport.HUD.Label",
                                width=28,
                            )
                            ui.Spacer(width=6)
                            self._resolution_value_label = self._build_hud_label(
                                "",
                                "Viewport.HUD.Value",
                                width=120,
                            )
                    ui.Spacer()
                ui.Spacer()

            # Top-right: livestream status overlay (Step 1.7). The row
            # is hidden when the renderer has no livestream tap; when
            # present, ``_refresh_livestream_status`` rewrites the label
            # text every frame from ``LivestreamTap.status()`` and a
            # tooltip surfaces the static config (protocol, ports, IP).
            with ui.VStack(spacing=0):
                ui.Spacer(height=self._get_hud_top_padding())
                with ui.HStack(height=22):
                    ui.Spacer()
                    self._livestream_row = ui.HStack(width=320, height=18, spacing=0)
                    with self._livestream_row:
                        ui.Spacer()
                        self._build_hud_label(
                            "STREAM", "Viewport.HUD.Label", width=56,
                        )
                        ui.Spacer(width=6)
                        self._livestream_value_label = self._build_hud_label(
                            "",
                            "Viewport.HUD.Value",
                            width=240,
                        )
                    ui.Spacer(width=14)
                ui.Spacer()

        # Backward-compatible alias used by older tests and callers: the FPS
        # value label is now only the value part of the label/value row.
        self._fps_label = self._fps_value_label
        self._refresh_hud()

    def _get_hud_top_padding(self) -> int:
        return self.TOOLBAR_HEIGHT + 4

    @staticmethod
    def _set_widget_visible(widget: Any, visible: bool) -> None:
        if widget is not None:
            widget.visible = visible

    def _refresh_hud(self) -> None:
        scene = self._scene_name or ""
        if self._scene_value_label is not None:
            self._scene_value_label.text = scene
        self._set_widget_visible(self._scene_row, bool(scene))

        fps_text = "" if self._last_fps is None else f"{self._last_fps:.0f}"
        res_text = ""
        if self._last_resolution is not None:
            res_text = f"{self._last_resolution[0]}×{self._last_resolution[1]}"
        if self._fps_value_label is not None:
            self._fps_value_label.text = fps_text
        if self._resolution_value_label is not None:
            self._resolution_value_label.text = res_text
        self._set_widget_visible(self._fps_res_row, bool(fps_text or res_text))
        self._set_widget_visible(self._resolution_label, bool(res_text))
        self._set_widget_visible(self._resolution_value_label, bool(res_text))
        self._set_widget_visible(self._fps_res_separator_label, bool(fps_text and res_text))

        self._refresh_livestream_status()

    def _refresh_livestream_status(self) -> None:
        """Read the current livestream-tap snapshot and update the
        Step-1.7 status overlay (label text + tooltip).

        Hidden when the renderer has no ``livestream`` tap (i.e.
        ``OVGEAR_LIVESTREAM`` is unset or the SDK is missing). Called
        from ``_refresh_hud`` so the overlay updates once per render.
        """
        tap = getattr(self._renderer, "livestream", None) if self._renderer else None
        if tap is None:
            self._set_widget_visible(self._livestream_row, False)
            return

        try:
            state, n_clients, last_error = tap.status()
        except Exception:
            self._set_widget_visible(self._livestream_row, False)
            return

        signal_port = int(getattr(tap, "signal_port", 0))
        media_port = int(getattr(tap, "media_port", 0))
        protocol = str(getattr(tap, "protocol", "?"))
        public_ip = getattr(tap, "public_ip", None)

        text = _ls_overlay.format_indicator(
            state, n_clients, last_error, signal_port, media_port,
        )
        tooltip = _ls_overlay.format_tooltip(
            state, n_clients, last_error, signal_port, media_port,
            protocol, public_ip,
        )

        if self._livestream_value_label is not None:
            self._livestream_value_label.text = text
            # ``set_tooltip`` is the omni.ui idiom; fall back to
            # ``tooltip`` attribute on builds where the setter is absent.
            try:
                self._livestream_value_label.set_tooltip(tooltip)
            except AttributeError:
                try:
                    self._livestream_value_label.tooltip = tooltip
                except Exception:
                    pass
        self._set_widget_visible(self._livestream_row, True)

    def _get_viewport_size(self) -> tuple:
        """Return the current (width, height) of the viewport image in pixels.

        The camera gestures use this to convert pixel deltas into angular or
        world-space units. Falls back to the last known render-buffer size
        (``self._width``/``self._height``) if the image widget has not yet
        laid out — that keeps Pan feeling right before the first frame.
        """
        w = 0
        h = 0
        if self._image is not None:
            w = int(self._image.computed_width or 0)
            h = int(self._image.computed_height or 0)
        if w <= 0:
            w = self._width
        if h <= 0:
            h = self._height
        return (w, h)

    def _make_pick_callback(self, mode: str) -> Any:
        """Return a point-pick callback bound to a selection ``mode``.

        ``mode`` is one of ``"replace"`` / ``"add"`` / ``"remove"`` — see
        :meth:`_merge_selection` for the semantics. The returned closure
        is what ``PickGesture`` invokes with the NDC ``(x, y)`` of the
        click.
        """
        def _cb(x: float, y: float) -> None:
            self._on_pick(x, y, mode)
        return _cb

    def _make_pick_rect_callback(self, mode: str) -> Any:
        """Return a marquee callback bound to a selection ``mode``."""
        def _cb(x0: float, y0: float, x1: float, y1: float) -> None:
            self._on_pick_rect(x0, y0, x1, y1, mode)
        return _cb

    def _on_pick(self, x: float, y: float, mode: str = "replace") -> None:
        if self._receiving_from_bus:
            return
        self._renderer.cancel_pick("viewport_click")  # type: ignore[union-attr]
        self._renderer.pick(  # type: ignore[union-attr]
            x, y,
            lambda path, pos: self._on_pick_result(path, mode),
            "viewport_click",
        )

    def _on_pick_result(self, path: Any, mode: str = "replace") -> None:
        hits = [path] if path else []
        merged = self._merge_selection(hits, mode)
        self._pushing_to_bus = True
        try:
            if self._bus:
                self._bus.publish(merged, source="viewport")
        finally:
            self._pushing_to_bus = False
        self._apply_self_published_selection(merged)

    def _on_pick_rect(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        mode: str = "replace",
    ) -> None:
        if self._receiving_from_bus:
            return
        self._renderer.pick_rect(  # type: ignore[union-attr]
            x0, y0, x1, y1,
            lambda paths: self._on_pick_rect_result(paths, mode),
        )

    def _on_pick_rect_result(self, paths: Any, mode: str = "replace") -> None:
        merged = self._merge_selection(list(paths or []), mode)
        self._pushing_to_bus = True
        try:
            if self._bus:
                self._bus.publish(merged, source="viewport")
        finally:
            self._pushing_to_bus = False
        self._apply_self_published_selection(merged)

    def _apply_self_published_selection(self, paths: list) -> None:
        """Mirror a viewport-initiated publish onto the viewport's own UI.

        :meth:`_on_bus_selection_changed` short-circuits when
        ``_pushing_to_bus`` is ``True`` to avoid a republish loop. That
        guard also skipped the benign-but-necessary calls that update
        the renderer highlight and gizmo — so a
        click on a prim selected it on the bus but left the viewport's
        own overlays stale. This helper runs those updates after the
        guard window closes. ``_on_bus_selection_changed`` keeps doing
        them for non-viewport sources (Stage Browser, keyboard shortcut,
        undo, etc.).
        """
        self._set_renderer_selection_highlight(paths)
        if self._manipulator_registry is not None:
            try:
                self._manipulator_registry.on_selection_changed(paths)
            except Exception:
                pass
        if self._transform_model is not None:
            try:
                self._transform_model.set_selection(paths)
            except Exception:
                pass
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.invalidate()
            except Exception:
                pass
            # Selection moved the pivot — reset the scale baseline so the
            # next ``_maybe_invalidate_gizmo_for_scale`` re-evaluates
            # against the new pivot rather than the previous prim's.
            self._last_gizmo_scale = 0.0

    def _merge_selection(self, hits: list, mode: str) -> list:
        """Combine ``hits`` with the current selection according to ``mode``.

        * ``"replace"`` — returns ``hits`` verbatim (plain click behavior).
        * ``"add"`` — union of current selection + ``hits``, current-order
          first so a shift-click appended item lands at the end of the
          list.
        * ``"remove"`` — current selection minus ``hits``; order of the
          surviving paths is preserved. A ctrl-click on empty space
          (``hits == []``) leaves the selection unchanged.

        Duplicates in ``hits`` or between ``hits`` and current selection
        are collapsed via ``dict.fromkeys`` (preserves order, dedupes).
        """
        if self._bus is None:
            return list(hits) if mode != "remove" else []
        try:
            snap = self._bus.get_snapshot()
            current = list(snap.paths()) if snap else []
        except Exception:
            current = []
        if mode == "replace":
            return list(dict.fromkeys(hits))
        if mode == "add":
            return list(dict.fromkeys(current + list(hits)))
        if mode == "remove":
            hit_set = set(hits)
            return [p for p in current if p not in hit_set]
        # Unknown mode — fall back to replace rather than raise so a
        # stale setting can't bring the viewport down.
        return list(dict.fromkeys(hits))

    def _on_bus_selection_changed(self, event: SelectionChangedEvent) -> None:
        if self._pushing_to_bus:
            return
        self._receiving_from_bus = True
        try:
            paths = event.snapshot.paths()
            self._set_renderer_selection_highlight(paths)
            if self._manipulator_registry is not None:
                self._manipulator_registry.on_selection_changed(paths)
            # Feed the transform gizmo. ``set_selection`` filters to the
            # transformable subset when the adapter is wired (post
            # ``attach_stage``); otherwise it keeps the raw list so the
            # gizmo still appears. Invalidate so the next draw emits
            # geometry at the new pivot.
            if self._transform_model is not None:
                self._transform_model.set_selection(paths)
            if self._transform_manipulator is not None:
                self._transform_manipulator.invalidate()
                self._last_gizmo_scale = 0.0
        finally:
            self._receiving_from_bus = False
        self._refresh_hud()

    def _set_renderer_selection_highlight(self, paths: list) -> None:
        """Apply selection highlights to renderable mesh targets.

        Stage/Property selection remains the user's exact selected paths.
        The renderer outline pass, however, only visibly outlines renderable
        geometry, so Xform/Scope/group selections are expanded to their
        descendant mesh prims before calling the renderer.
        """
        try:
            highlight_paths = self._resolve_selection_highlight_paths(paths)
            self._renderer.set_selection_highlight(  # type: ignore[union-attr]
                highlight_paths
            )
        except Exception:
            pass

    def _resolve_selection_highlight_paths(self, paths: list) -> list[str]:
        selected = [str(path) for path in (paths or []) if path]
        adapter = self._get_stage_adapter()
        if adapter is None:
            return list(dict.fromkeys(selected))

        resolved: list[str] = []
        for path in selected:
            try:
                item = adapter.get_item_at_path(path)
            except Exception:
                item = None
            if item is None:
                resolved.append(path)
                continue
            resolved.extend(self._collect_mesh_highlight_paths(adapter, item))
        return list(dict.fromkeys(resolved))

    def _collect_mesh_highlight_paths(self, adapter: Any, item: Any) -> list[str]:
        paths: list[str] = []
        stack = [item]
        while stack:
            current = stack.pop()
            try:
                if adapter.get_type_category(current) == "Mesh":
                    paths.append(str(adapter.get_item_path(current)))
            except Exception:
                pass
            try:
                children = list(adapter.get_children(current) or [])
            except Exception:
                children = []
            stack.extend(reversed(children))
        return paths

    def _get_outline_selection(self) -> list:
        """Return selected paths for renderer/gizmo change invalidation.

        Reads from the ``SelectionBus`` rather than the transform model so
        non-transformable prims are still considered when deciding whether a
        stage change affects the current selection.
        """
        if self._bus is None:
            return []
        try:
            snap = self._bus.get_snapshot()
        except Exception:
            return []
        if snap is None:
            return []
        try:
            return list(snap.paths())
        except Exception:
            return []

    def _get_gizmo_world_scale(self) -> float:
        """Return the per-frame gizmo world-scale for constant screen size.

        The fixed :data:`~ovwidgets.viewport.transform_manipulator.GIZMO_SIZE_SCALE`
        placeholder is too small for USD scenes authored in centimetres or
        larger units — a 0.05-unit gizmo is sub-pixel at normal camera
        distances. This computes a world scale that keeps the gizmo a
        consistent fraction of the viewport height:

            world_scale = distance_from_eye_to_pivot
                         * tan(fov/2) * 2
                         * SCREEN_FRACTION / viewport_height_px

        With ``fov = 45°`` and ``SCREEN_FRACTION = 80 px``, that collapses
        to roughly ``0.092 * distance`` on a 720-px-tall viewport, which
        sits comfortably between "visible at every distance" and
        "dominates the frame".
        """
        import math
        try:
            pivot = self._transform_model.get_pivot_world() if self._transform_model else (0.0, 0.0, 0.0)
            eye = self._camera._get_eye()
            dx = float(eye[0]) - float(pivot[0])
            dy = float(eye[1]) - float(pivot[1])
            dz = float(eye[2]) - float(pivot[2])
            dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        except Exception:
            dist = float(self._camera.state.distance)
        # Keep the gizmo roughly 80 pixels tall on a 720-tall viewport.
        # tan(22.5°) ≈ 0.4142. The final ratio is independent of viewport
        # height for a perspective camera — the FOV fully determines the
        # screen-space / world-space ratio at the pivot.
        SCREEN_PIXEL_TARGET = 80.0
        _, vh = self._get_viewport_size()
        if vh <= 0:
            vh = 720
        scale = dist * math.tan(math.radians(45.0) * 0.5) * 2.0 * (SCREEN_PIXEL_TARGET / float(vh))
        # Floor so the gizmo never shrinks to zero at very small camera
        # distances (e.g., min-zoom clamp at 0.01).
        return max(scale, 1e-4)

    def _compute_world_bbox(self, path: str):
        """Return ``((min_xyz, max_xyz))`` AABB for ``path`` or ``None``.

        Retained as a small compatibility helper for existing tests and
        callers that need viewport-owned stage bounds. Native ovrtx selection
        outlines no longer use this path for production drawing.

        Step 17 delegates to
        :meth:`StageAdapter.compute_prim_world_aabb_with_extent_fallback`
        so the widget no longer imports ``pxr``. The adapter implementation
        retains the original two-tier algorithm: ``Boundable.ComputeExtent``
        for prims with extent-driving attributes (radius / size / points),
        ``UsdGeom.BBoxCache`` for non-Boundable selections.

        Adapter exceptions are caught and reported as ``None``, preserving
        the pre-Step-17 no-throw contract (the old inline pxr code wrapped
        the entire body in ``try/except`` for the same reason). A failing
        adapter implementation must not break the manipulator.
        """
        if self._stage_adapter_provider is None:
            return None
        adapter = self._stage_adapter_provider()
        if adapter is None:
            return None
        try:
            return adapter.compute_prim_world_aabb_with_extent_fallback(path)
        except Exception:
            return None

    def attach_stage(
        self,
        transform_adapter: Any,
        stage_adapter: Any,
        undo_manager: Any,
        snap_system: Any = None,
    ) -> None:
        """Wire per-stage adapters into the transform gizmo (Step C.2).

        Called by :class:`~ovwidgets.app.application.Application._load_stage` after
        the USD stage has been opened and the stage/transform adapters have
        been constructed. The adapters live on the
        :class:`PrimTransformModel` for the lifetime of the stage; loading
        a different stage replaces them.
        """
        if self._transform_model is None:
            return
        self._commit_active_camera_pose_if_dirty()
        self._active_camera_path = None
        self._last_authored_camera_signature = None
        self._reset_camera_navigation_state()
        # Drop any previously bound camera selection on the renderer so
        # a fresh stage starts on the default session camera instead of
        # whatever the previous stage's user-selected camera was.
        reset = getattr(self._renderer, "set_active_camera_path", None)
        if callable(reset):
            try:
                reset(None)
            except Exception:
                pass
        self._transform_model.attach_adapters(
            transform_adapter=transform_adapter,
            stage_adapter=stage_adapter,
            undo=undo_manager,
            snap_system=snap_system,
        )

    def frame_paths(self, paths: list) -> bool:
        """Frame the camera to enclose the given prim paths.

        Returns ``True`` when real bounds were computed and applied;
        ``False`` when no real bounds were available (empty paths,
        no adapter, no provider, adapter returned ``None``, or adapter
        raised). On the ``False`` path with non-empty ``paths``, the
        camera falls back to a safe default focus
        (``center=(0, 0, 0)``, ``distance=5.0``) so the viewport remains
        usable. Empty ``paths`` returns ``False`` without touching the
        camera at all.

        Adapter exceptions are caught and treated as "no bounds available"
        (matching the pre-Step-17 inline pxr code's blanket ``except``
        guard). This preserves the no-throw contract — a failing adapter
        implementation never breaks the framing loop.

        Special case ``"/"`` is handled inside the adapter
        (:meth:`StageAdapter.compute_world_aabb` iterates the pseudo-root's
        children when given the pseudo-root path); the widget no longer
        needs to know about it.
        """
        if not paths:
            return False
        bounds = None
        if self._stage_adapter_provider is not None:
            adapter = self._stage_adapter_provider()
            if adapter is not None:
                try:
                    bounds = adapter.compute_world_aabb(paths)
                except Exception:
                    bounds = None
        if bounds is None:
            # Fallback: keep the viewport usable with a safe default
            # focus. Mirrors the pre-Step-17 inline behavior where
            # missing/invalid bounds fell through to the default
            # ``center=(0,0,0), distance=5.0`` focus call.
            self._camera.focus([0.0, 0.0, 0.0], 5.0)
            return False
        (min_x, min_y, min_z), (max_x, max_y, max_z) = bounds
        center = [
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        ]
        size = (max_x - min_x, max_y - min_y, max_z - min_z)
        distance = max(float(max(size[0], size[1], size[2])) * 2.0, 0.5)
        self._camera.focus(center, distance)
        return True

    def apply_camera_pose(self, pose: Optional[BoundCameraPose]) -> bool:
        """Apply ``pose`` to the viewport camera.

        Step 16 closes the previous raw-``Usd.Stage`` seam: callers
        (typically :class:`Application`) parse the bound-camera metadata
        through the stage adapter and pass the resulting
        :class:`BoundCameraPose` value object here. The widget no
        longer touches ``Usd.Stage`` for camera metadata.

        Returns ``True`` when a pose was successfully applied; ``False``
        when ``pose`` is ``None`` or when the underlying camera setter
        raised. Callers fall back to :meth:`frame_paths` when this is
        ``False`` so the bbox framing remains the safe default.
        """
        if pose is None:
            return False
        try:
            self._camera.set_pose(
                eye=pose.eye,
                target=pose.target,
                up_axis=pose.up_axis,
                fov_degrees=pose.fov_degrees,
            )
        except Exception:
            return False
        return True

    def _camera_author_signature(self, path: str) -> tuple[Any, ...]:
        state = self._camera.state
        return (
            path,
            tuple(round(float(v), 9) for v in state.target),
            round(float(state.distance), 9),
            round(float(state.azimuth), 9),
            round(float(state.elevation), 9),
            tuple(round(float(v), 9) for v in self._camera.up_axis),
            round(float(self._camera.fov_degrees), 9),
        )

    def _camera_navigation_signature(self) -> tuple[Any, ...]:
        return self._camera_author_signature(self._active_camera_path or "")

    def _reset_camera_navigation_state(self) -> None:
        self._camera_navigation_state.reset(self._camera_navigation_signature())

    def _tick_camera_navigation_state(self) -> None:
        self._camera_navigation_state.observe(self._camera_navigation_signature())

    def is_camera_navigation_active(self) -> bool:
        return self._camera_navigation_state.is_active

    def has_dirty_camera_navigation(self) -> bool:
        return self._camera_navigation_state.is_dirty

    def _write_active_camera_pose_from_matrices(
        self,
        path: str,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
        *,
        undoable: bool = True,
    ) -> bool:
        adapter = self._get_stage_adapter()
        writer = getattr(adapter, "write_camera_pose_from_matrices", None)
        if not callable(writer):
            return False
        try:
            self._committing_active_camera_pose = True
            target = tuple(float(v) for v in self._camera.state.target)
            kwargs: dict[str, Any] = {}
            if self._callable_accepts_keyword(writer, "source"):
                kwargs["source"] = VIEWPORT_CAMERA_POSE_SOURCE
            if self._callable_accepts_keyword(writer, "undoable"):
                kwargs["undoable"] = undoable
            return bool(
                writer(path, view_matrix, proj_matrix, width, height, target, **kwargs)
            )
        except Exception:
            return False
        finally:
            self._committing_active_camera_pose = False

    @staticmethod
    def _callable_accepts_keyword(callable_obj: Any, keyword: str) -> bool:
        try:
            parameters = inspect.signature(callable_obj).parameters
        except (TypeError, ValueError):
            return True
        if keyword in parameters:
            return True
        return any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        )

    def _commit_active_camera_pose_if_dirty(self, *, undoable: bool = True) -> bool:
        if self._committing_active_camera_pose:
            return False
        path = self._active_camera_path
        if not path or not self._camera_navigation_state.is_dirty:
            return False
        resolution = self._last_resolution
        if resolution is None:
            self._camera_navigation_state.clear_dirty()
            return False
        width, height = resolution
        if width <= 0 or height <= 0:
            self._camera_navigation_state.clear_dirty()
            return False
        view, proj = self._camera.get_matrices(width, height)
        signature = self._camera_author_signature(path)
        accepted = self._write_active_camera_pose_from_matrices(
            path,
            view,
            proj,
            width,
            height,
            undoable=undoable,
        )
        if accepted:
            self._last_authored_camera_signature = signature
        self._camera_navigation_state.clear_dirty()
        return accepted

    @staticmethod
    def _stage_change_path_affects_prim(change_path: Any, prim_path: str) -> bool:
        path = str(change_path or "")
        prim = str(prim_path or "")
        if not path or not prim:
            return False
        if path == prim or path.startswith(prim + "/") or path.startswith(prim + "."):
            return True
        # USD attribute notices use property paths such as
        # ``/World.xformOp:translate``. The active camera's world pose changes
        # when an ancestor xform attribute changes, so compare against the
        # owning prim path too.
        owner = path.split(".", 1)[0]
        return owner == "/" or prim == owner or prim.startswith(owner + "/")

    def _is_self_authored_active_camera_pose_event(self, event: Any) -> bool:
        path = self._active_camera_path
        if not path or not is_viewport_camera_pose_change_event(event):
            return False
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        return any(
            self._stage_change_path_affects_prim(changed_path, path)
            for changed_path in changed + resynced
        )

    def _sync_active_camera_from_stage_change(self, event: Any) -> bool:
        path = self._active_camera_path
        if not path:
            return False
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        if not changed and not resynced:
            return False
        if not any(
            self._stage_change_path_affects_prim(changed_path, path)
            for changed_path in changed + resynced
        ):
            return False
        if self._is_self_authored_active_camera_pose_event(event):
            return False
        adapter = self._get_stage_adapter()
        reader = getattr(adapter, "read_camera_pose", None)
        if not callable(reader):
            return False
        should_reset_navigation = not self._camera_navigation_state.is_active
        if should_reset_navigation:
            self._commit_active_camera_pose_if_dirty()
        try:
            pose = reader(path)
        except Exception:
            return False
        if not self.apply_camera_pose(pose):
            return False
        self._last_authored_camera_signature = self._camera_author_signature(path)
        # External Properties edits arrive while navigation is settled and
        # should become the new baseline. A self-authored camera notice can
        # arrive after the render tick already marked navigation active; do
        # not let that notice erase the active/dirty state Step 4 will use.
        if should_reset_navigation:
            self._reset_camera_navigation_state()
        return True

    def _author_active_camera_pose(
        self,
        view_matrix: Any,
        proj_matrix: Any,
        width: int,
        height: int,
    ) -> bool:
        """Persist active USD camera navigation back to the stage.

        Selecting a USD camera puts the viewport in camera-edit mode: pan,
        zoom, orbit, look, and flight changes must move that camera prim so
        Properties and later camera switches see the edited pose. Minimal
        adapters return ``False`` and keep the free-camera behavior.
        """
        path = self._active_camera_path
        if not path:
            return False
        signature = self._camera_author_signature(path)
        if signature == self._last_authored_camera_signature:
            self._camera_navigation_state.clear_dirty()
            return False
        if self._camera_navigation_state.is_active:
            return False
        accepted = self._write_active_camera_pose_from_matrices(
            path,
            view_matrix,
            proj_matrix,
            width,
            height,
        )
        if accepted:
            self._last_authored_camera_signature = signature
            self._camera_navigation_state.clear_dirty()
        return accepted

    # Camera-physics dt clamps. ``TumbleInertia.tick`` already clamps
    # internally (see ``camera_inertia.py:DT_CLAMP_MIN/MAX``); flight mode
    # has no built-in clamp and would otherwise launch the camera across
    # the scene if the loop ever produces a multi-second tick (debugger
    # pause, GC stall, first-frame clock bug). Mirror tumble's bounds.
    _UPDATE_DT_MIN = 0.001
    _UPDATE_DT_MAX = 0.1

    def update(self, tick_dt: float) -> None:
        """Per-tick wall-clock physics — flight + tumble inertia.

        Runs every outer-loop tick regardless of whether the render gate
        fires this frame. ``tick_dt`` is the time since the previous tick.
        Non-positive values (``None``, ``0.0``, negative) short-circuit
        the whole method: ``FlightModeKeyboard.integrate()`` documents
        non-positive dt as a no-op (camera_flight_keyboard.py:248-252)
        and ``TumbleInertia.tick()`` does the same — there is nothing
        useful for either subsystem to do at a zero or negative interval.

        Positive values are clamped to ``[_UPDATE_DT_MIN, _UPDATE_DT_MAX]``
        before reaching flight integration so a long stall cannot teleport
        the camera. Tumble inertia clamps the same range internally; we
        pass it the original (positive) value so its own bounds remain
        authoritative.
        """
        if tick_dt is None or tick_dt <= 0.0:
            return
        # Flight integration is speed × seconds; clamp before forwarding so
        # a multi-second stall can't propel the camera through the scene.
        if self._flight_keyboard.is_flying:
            dt = max(self._UPDATE_DT_MIN, min(self._UPDATE_DT_MAX, float(tick_dt)))
            self._flight_keyboard.integrate(dt)
        if self._tumble_inertia.is_active:
            self._tumble_inertia.tick(tick_dt)

    def render(self, render_dt: float) -> bool:
        """Per-render path — RTX render, image bridge upload, HUD refresh.

        Returns ``True`` iff a frame was actually rendered. The Application
        only commits the FrameClock on ``True``, so a hidden, zero-size, or
        first-pass-with-no-renderer frame leaves the cadence clock untouched
        and the next tick re-attempts rendering immediately rather than
        waiting out the throttle period.

        ``render_dt`` is the time since the last *committed* render. The FPS
        HUD reads it directly. The first render for a target sees
        ``render_dt == 0.0``; the FPS HUD update is suppressed in that case
        so the user doesn't see a one-frame "inf FPS" or boot-clock-derived
        garbage value.
        """
        if self._image is None:
            return False
        if not self._image.visible:
            return False
        w = int(self._image.computed_width or 0)
        h = int(self._image.computed_height or 0)
        if w <= 0 or h <= 0:
            return False
        if self._renderer is None:
            return False
        # Update the FPS HUD only after we've seen at least one prior render
        # — the first-frame ``render_dt = 0.0`` would otherwise divide by
        # zero / report nonsense.
        if render_dt > 0.0:
            self._last_fps = 1.0 / render_dt
            self._refresh_hud()
        w = max(self.MIN_RENDER_WIDTH, min(self.MAX_RENDER_WIDTH, w))
        h = max(self.MIN_RENDER_HEIGHT, min(self.MAX_RENDER_HEIGHT, h))
        self._last_resolution = (w, h)
        self._refresh_hud()
        view, proj = self._camera.get_matrices(w, h)
        self._tick_camera_navigation_state()
        self._author_active_camera_pose(view, proj, w, h)
        frame = self._renderer.render_frame(w, h, view, proj)  # type: ignore[union-attr]
        self._bridge.update(frame)
        # Sync the scene-view overlay's camera so gizmo geometry drawn in
        # world coordinates (translate handles, pick markers, etc.) aligns
        # with the rendered prims. ``sc.SceneView.view`` / ``projection``
        # expect a flat 16-float matrix with translation in the *last row*
        # (positions 12/13/14), but :func:`CameraController._look_at`
        # stores it in the last *column* (indices 3/7/11). Transpose
        # before flattening so the column-convention matrix matches the
        # row-convention binding.
        if self._scene_view is not None:
            try:
                view_flat = (
                    view.T.flatten().tolist() if hasattr(view, "T") else list(view)
                )
                proj_flat = (
                    proj.T.flatten().tolist() if hasattr(proj, "T") else list(proj)
                )
                self._scene_view.view = view_flat
                self._scene_view.projection = proj_flat
            except Exception:
                pass
        # Drive the gizmo's position & scale via direct ``sc.Transform``
        # attribute updates — same "build-once-update-per-frame" pattern
        # Kit uses in ``omni.kit.manipulator.transform.TransformManipulator.
        # _update_from_model``. Every frame the manipulator reads the
        # current pivot + camera-distance scale off our callables and
        # writes them into its persistent Transform nodes, so selection
        # changes show up on the very next draw without any
        # ``invalidate()`` race. Cheap: two matrix writes when anything
        # actually changed, no-op otherwise.
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.refresh_transform()
            except Exception:
                pass
        # Kept for the "camera moved enough → invalidate" fallback path
        # that still forces a full rebuild when the gizmo size needs a
        # major step. With ``refresh_transform`` in place this is
        # mostly a no-op; retained as defence in depth.
        self._maybe_invalidate_gizmo_for_scale()
        return True

    def _on_frame(self, dt: float) -> None:
        """Backward-compatible single-call entry — splits into update + render.

        Production: :class:`Application` calls :meth:`update` and
        :meth:`render` separately under control of its own
        :class:`FrameClock`. This shim is retained for legacy QA scripts
        and pre-FrameClock unit tests that still drive the viewport with a
        single ``dt``. It applies the simple "skip render if dt below
        ``1/MAX_FPS_FOREGROUND``" gate so test expectations from the
        pre-split era keep matching.
        """
        target_dt = 1.0 / self.MAX_FPS_FOREGROUND
        self.update(dt)
        if self._image is None or not self._image.visible:
            return
        if dt < target_dt:
            return
        self.render(dt)

    def _is_gizmo_drag_active(self) -> bool:
        """True iff a translate / rotate / scale drag is currently in flight.

        Each gesture exposes an ``is_active`` flag it sets between
        ``on_began`` and ``on_ended``. If any of them is active we must
        not invalidate the manipulator — doing so swaps the shape the
        gesture is bound to and the drag dies silently.
        """
        mani = self._transform_manipulator
        if mani is None:
            return False
        for group in (
            getattr(mani, "_translate_drags", None) or (),
            getattr(mani, "_rotate_drags", None) or (),
            getattr(mani, "_scale_drags", None) or (),
        ):
            for g in group:
                if getattr(g, "is_active", False):
                    return True
        uniform = getattr(mani, "_uniform_scale_drag", None)
        if uniform is not None and getattr(uniform, "is_active", False):
            return True
        return False

    def _maybe_invalidate_gizmo_for_scale(self) -> None:
        """Invalidate the gizmo iff camera-driven size changed non-trivially.

        Compares the current ``_get_gizmo_world_scale`` against the
        value at the last rebuild; only invalidates when the relative
        change is ≥ 10 % or the baseline is zero (first build). Skipped
        while a drag is active — see :meth:`_is_gizmo_drag_active`.
        """
        mani = self._transform_manipulator
        if mani is None or not mani.has_selection():
            self._last_gizmo_scale = 0.0
            return
        if self._is_gizmo_drag_active():
            return
        try:
            current = float(self._get_gizmo_world_scale())
        except Exception:
            return
        if current <= 0.0:
            return
        last = self._last_gizmo_scale
        if last <= 0.0 or abs(current - last) / max(last, 1e-6) >= 0.10:
            try:
                mani.invalidate()
            except Exception:
                return
            self._last_gizmo_scale = current

    def update_prim_count(self, count: int) -> None:
        """Store the current stage prim count.

        Step 18 removes the viewport's old prim-count HUD line in favour of
        scene/selection data. The value is still stored because the
        application continues to notify the viewport after stage resyncs.
        """
        self._prim_count = int(count)

    def set_scene_name(self, name: Optional[str]) -> None:
        """Set the viewport HUD scene name from the active stage title."""
        self._scene_name = name or None
        self._refresh_hud()

    def notify_stage_changed(self, event: Any) -> None:
        """Forward a stage ``ChangeEvent`` to the active renderer if it can handle it.

        Called by ``Application._on_stage_changed`` whenever the USD stage adapter
        flushes a batch of changes (Property Inspector edits, undo/redo, external
        stage mutations). The renderer decides what to re-read; the viewport
        routes the event and also invalidates scene-view overlays whose geometry
        depends on selected-prim state (the transform gizmo pivot) so a
        Property-panel translate / scale / radius edit shows up in the viewport
        without requiring a re-click. Active USD camera changes are also re-read
        through the stage adapter so Properties edits to the selected camera
        immediately update the viewport's controller pose.
        """
        if not self._is_self_authored_active_camera_pose_event(event):
            self._sync_active_camera_from_stage_change(event)
        if self._renderer is not None:
            handler = getattr(self._renderer, "notify_stage_changed", None)
            if handler is not None:
                try:
                    handler(event)
                except Exception:
                    pass
        # Invalidate outline + gizmo whenever any selected prim (or its
        # subtree) is part of the change. We compare path prefixes so a
        # parent-level xform edit pushes a refresh through to children that
        # inherit it. An empty selection short-circuits — there's nothing
        # to refresh.
        selected = self._get_outline_selection()
        if not selected:
            return
        changed = tuple(getattr(event, "changed_paths", ()) or ())
        resynced = tuple(getattr(event, "resynced_paths", ()) or ())
        if not changed and not resynced:
            return
        affected = False
        for path in list(changed) + list(resynced):
            for sel in selected:
                # Matches the prim path itself, a descendant prim path
                # (``/Foo`` → ``/Foo/Bar``), an ancestor path (parent xform
                # edits propagate down), and property paths
                # (``/Foo.xformOp:translate`` is how USD reports attribute
                # changes — those never match ``startswith(sel + '/')``).
                if (
                    path == sel
                    or path.startswith(sel + "/")
                    or path.startswith(sel + ".")
                    or sel.startswith(path + "/")
                ):
                    affected = True
                    break
            if affected:
                break
        if not affected:
            return
        if self._transform_manipulator is not None:
            try:
                self._transform_manipulator.invalidate()
            except Exception:
                pass

    def _resolve_settings(self) -> Any:
        """Return the live :class:`Settings` instance, or ``None``.

        Step 11.3: two-stage explicit lookup. First check the
        services object the widget was constructed with for an
        attached ``settings`` attribute (legacy test fakes that still
        set ``services=SimpleNamespace(settings=...)`` rely on this),
        then fall back to the
        :class:`ovwidgets.common.settings.Settings` singleton wired by
        :meth:`Application.__init__` in Step 10. Returns ``None`` if
        neither path supplies a live Settings (headless / mock paths).
        """
        services_settings = getattr(self._services, "settings", None)
        if services_settings is not None:
            return services_settings
        from ovwidgets.common.settings import Settings
        return Settings._instance

    def _attach_zero_copy_state(
        self,
        renderer: Optional[RendererAdapter],
        *,
        adopt_existing: bool = False,
    ) -> None:
        """Attach this viewport's zero-copy state to ``renderer`` when possible."""
        if renderer is None:
            return
        if adopt_existing:
            existing = getattr(renderer, "_zero_copy_state", None)
            if existing is not None:
                self._zero_copy_state = existing
                return

        setter = getattr(renderer, "set_zero_copy_state", None)
        if callable(setter):
            setter(self._zero_copy_state)
            return

        try:
            renderer._zero_copy_state = self._zero_copy_state
        except AttributeError:
            pass

    def set_renderer(self, renderer: RendererAdapter) -> None:
        """Swap the active renderer. Shuts down the old one and reapplies selection.

        Failures during shutdown or selection reapply are swallowed: the new
        renderer is already installed and the next frame will drive it; an
        error tearing down the old renderer must not prevent the swap.
        """
        old = self._renderer
        self._attach_zero_copy_state(renderer)
        self._renderer = renderer
        self._active_render_product_path = None
        if old is not None and old is not renderer:
            try:
                old.shutdown()
            except Exception:
                pass
        if self._bus is not None:
            try:
                snap = self._bus.get_snapshot()
                paths = snap.paths() if snap else []
                renderer.set_selection_highlight(
                    self._resolve_selection_highlight_paths(paths)
                )
            except Exception:
                pass

    def destroy(self) -> None:
        """Tear down the viewport.

        Issue #35 Step 5b / Round 3 F4: each cleanup step runs in its
        own ``try/except``, AND ``super().destroy()`` runs in a
        ``finally`` so the underlying :class:`ui.Window` is always
        released — even if ``self._renderer.shutdown()`` raises. The
        previous shape skipped ``super().destroy()`` on a renderer
        shutdown failure, leaving the window alive in
        :data:`omni.ui.Workspace` until ``Py_FinalizeEx`` (the exact
        UAF window-leak mode this whole fix prevents). Same
        best-effort pattern as :meth:`Application.shutdown` (Round 2
        F3 / Round 3 F5 / Round 5 F1).
        """
        try:
            self._commit_active_camera_pose_if_dirty(undoable=False)
        except Exception:
            pass
        try:
            if self._bus_sub:
                self._bus_sub.cancel()
                self._bus_sub = None
        except Exception:
            pass
        try:
            if self._tool_registry is not None:
                self._tool_registry.destroy()
                self._tool_registry = None
        except Exception:
            pass
        try:
            self._destroy_camera_menu()
        except Exception:
            pass
        try:
            self._destroy_render_product_menu()
        except Exception:
            pass
        try:
            try:
                self._renderer.shutdown()  # type: ignore[union-attr]
            except Exception:
                # Round 3 F4: the ui.Window MUST be destroyed regardless
                # — see super().destroy() in the finally below.
                pass
        finally:
            super().destroy()


# ── Issue #35 Step 3: register the module-scope provider cache so
# Application.shutdown() drops every ui.RasterImageProvider it holds
# before omni.ui.shutdown() runs.
from ovwidgets.common.icon_caches import register_dict as _register_dict_for_shutdown

_register_dict_for_shutdown(_TOOLBAR_ICON_PROVIDERS)
