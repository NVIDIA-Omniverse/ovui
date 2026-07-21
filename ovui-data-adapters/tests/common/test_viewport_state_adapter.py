from __future__ import annotations

from types import SimpleNamespace

from ovui_data_adapters.common import (
    RenderTargetCatalog,
    RenderTargetDescriptor,
    RenderTargetOutputKind,
    RenderVarOutputCatalog,
    RenderVarOutputDescriptor,
    ViewportStateAdapter,
)


class FakeStageAdapter:
    def __init__(self) -> None:
        self.camera_calls = 0
        self.target_calls = 0

    def list_cameras(self):
        self.camera_calls += 1
        return (
            SimpleNamespace(path="/World/Camera_A", display_name="Camera A"),
            SimpleNamespace(path="/World/Camera_B", display_name="Camera B"),
        )

    def get_render_target_catalog(self):
        self.target_calls += 1
        return RenderTargetCatalog(
            targets=(
                RenderTargetDescriptor(
                    target_id="camera:/Render/Main",
                    render_product_path="/Render/Main",
                    display_name="Main Product",
                    kind="camera",
                    output_kind=RenderTargetOutputKind.IMAGE,
                    resolution=(1280, 720),
                    enabled=True,
                ),
                RenderTargetDescriptor(
                    target_id="pointcloud:/Render/Points",
                    render_product_path="/Render/Points",
                    display_name="Points Product",
                    kind="sensor",
                    output_kind=RenderTargetOutputKind.POINT_CLOUD,
                    enabled=False,
                    disabled_reason="point cloud renderer unavailable",
                ),
            ),
            active_target_id="camera:/Render/Main",
            active_render_product_path="/Render/Main",
        )


class FakeRendererAdapter:
    def __init__(self) -> None:
        self.output_calls: list[str | None] = []

    def get_active_camera_path(self):
        return "/World/Camera_A"

    def get_active_render_product_path(self):
        return "/Render/Main"

    def list_render_var_outputs(self, render_product_path=None):
        self.output_calls.append(render_product_path)
        return RenderVarOutputCatalog(
            outputs=(
                RenderVarOutputDescriptor(
                    output_id="depth",
                    render_product_path="/Render/Main",
                    render_var_name="Depth",
                    display_name="Depth",
                    output_kind="scalar_depth",
                    enabled=True,
                ),
                RenderVarOutputDescriptor(
                    output_id="normals",
                    render_product_path="/Render/Main",
                    render_var_name="Normals",
                    display_name="Normals",
                    output_kind="vector_normal",
                    enabled=True,
                ),
            ),
            active_render_product_path="/Render/Main",
            active_output_id="depth",
        )


def test_viewport_state_adapter_publishes_backend_viewport_chrome_state() -> None:
    stage = FakeStageAdapter()
    renderer = FakeRendererAdapter()
    adapter = ViewportStateAdapter(
        stage_adapter=stage,
        renderer_adapter=renderer,
        tool_registry_available=True,
    )

    notifications = []
    subscription = adapter.subscribe_viewport_state_changes(notifications.append)
    snapshot = adapter.refresh_from_adapters(
        current_usd_path="/tmp/simple_scene.usda",
        fps=47.5,
        resolution=(1280, 720),
        stream_state="LISTENING",
        client_count=2,
        signal_port=49100,
        media_port=47999,
        stream_source="test-tap",
    )

    assert notifications[-1] is snapshot
    assert stage.camera_calls == 1
    assert stage.target_calls == 1
    assert renderer.output_calls == ["/Render/Main"]
    assert snapshot.active_tool == "move"
    assert snapshot.ovui_tool == "translate"
    assert snapshot.available_tools == ("move", "rotate", "scale")
    assert snapshot.tool_registry_available is True
    assert [camera.path for camera in snapshot.cameras] == ["/World/Camera_A", "/World/Camera_B"]
    assert snapshot.active_camera_path == "/World/Camera_A"
    assert snapshot.render_target_catalog.active_target_id == "camera:/Render/Main"
    assert snapshot.active_target_id == "camera:/Render/Main"
    assert snapshot.active_kind == "camera"
    assert any(group["kind"] == "point_cloud" for group in snapshot.render_target_groups)
    assert snapshot.render_var_catalog.active_output_id == "depth"
    assert [item["id"] for item in snapshot.render_var_items] == ["depth", "normals"]
    assert snapshot.active_render_var_output_id == "depth"
    assert snapshot.supports_render_var_clear is True
    assert snapshot.scene_label == "simple_scene.usda"
    assert snapshot.fps == 47.5
    assert snapshot.resolution == (1280, 720)
    assert snapshot.stream is not None
    assert snapshot.stream.state == "STREAMING"
    assert snapshot.stream.client_count == 2
    assert snapshot.stream.source == "test-tap"
    assert snapshot.toolbar_availability["move"]["available"] is True
    assert snapshot.toolbar_availability["camera"]["available"] is True
    assert snapshot.toolbar_availability["render_target"]["available"] is True
    assert snapshot.toolbar_availability["rendervar"]["available"] is True
    assert snapshot.toolbar_availability["path_tracing_progress"]["available"] is False
    assert snapshot.render_progress_present is False
    assert snapshot.path_tracing_present is False
    assert not hasattr(snapshot, "render_progress")
    assert not hasattr(snapshot, "path_tracing")

    subscription.cancel()
    adapter.set_active_tool("rotate")
    assert notifications[-1] is snapshot
    assert adapter.snapshot().active_tool == "rotate"


def test_viewport_state_adapter_reports_unavailable_state_without_fake_runtime() -> None:
    adapter = ViewportStateAdapter()
    snapshot = adapter.refresh_from_adapters(
        current_usd_path="",
        resolution=None,
        stream_state="OFF",
        client_count=0,
    )

    assert snapshot.cameras == ()
    assert snapshot.render_target_catalog.targets == ()
    assert snapshot.render_target_groups == ()
    assert snapshot.render_var_catalog.outputs == ()
    assert snapshot.render_var_items == ()
    assert snapshot.active_camera_path is None
    assert snapshot.active_target_id is None
    assert snapshot.active_render_var_output_id is None
    assert snapshot.scene_label is None
    assert snapshot.resolution is None
    assert snapshot.stream is not None
    assert snapshot.stream.state == "OFF"
    assert snapshot.tool_registry_available is False
    assert snapshot.toolbar_availability["move"]["available"] is False
    assert snapshot.toolbar_availability["camera"]["available"] is False
    assert snapshot.toolbar_availability["render_target"]["available"] is False
    assert snapshot.toolbar_availability["rendervar"]["available"] is False
    assert snapshot.backend_owned is True
    assert snapshot.render_progress_present is False
    assert snapshot.path_tracing_present is False
