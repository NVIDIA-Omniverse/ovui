# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest
from ovui_data_adapters.services.selection import SelectionBus
from ovui_data_adapters.services.undo import UndoManager

from ovui_widgets.app.inspector_state import (
    _attribute_value_parity,
    _backing_layer_snapshot,
    _bridge_identity_snapshot,
    _file_fingerprint,
    _json_value,
    _layer_state_parity,
    _native_attribute_snapshot,
    _numeric_value_fingerprint,
    _topology_value_parity,
    _viewport_snapshot,
    capture_application_state,
)

pxr = pytest.importorskip("pxr")
from ovui_data_adapters.openusd.layer_stack_adapter import (  # noqa: E402
    UsdLayerStackAdapter,
)
from ovui_data_adapters.openusd.property_adapter import (  # noqa: E402
    UsdPropertyAdapter,
)
from ovui_data_adapters.openusd.provider import OpenUSDProviderSession  # noqa: E402
from ovui_data_adapters.openusd.stage_adapter import UsdStageAdapter  # noqa: E402
from ovui_data_adapters.openusd.transform_adapter import (  # noqa: E402
    UsdTransformAdapter,
)
from pxr import Gf, Usd, UsdGeom  # noqa: E402


def _application_with_stage() -> SimpleNamespace:
    stage = Usd.Stage.CreateInMemory()
    world = UsdGeom.Xform.Define(stage, "/World")
    cube = UsdGeom.Cube.Define(stage, "/World/Cube")
    cube.AddTranslateOp().Set(Gf.Vec3d(1.0, 2.0, 3.0))
    stage.SetDefaultPrim(world.GetPrim())

    undo = UndoManager()
    selection = SelectionBus()
    selection.publish(["/World/Cube"], source="stage")
    stage_adapter = UsdStageAdapter(stage, undo)
    transform_adapter = UsdTransformAdapter(stage)
    layer_adapter = UsdLayerStackAdapter(stage, undo)
    return SimpleNamespace(
        _adapter_provider=SimpleNamespace(name="openusd"),
        _adapter_session=OpenUSDProviderSession(),
        _stage_adapter=stage_adapter,
        _layer_adapter=layer_adapter,
        _selection_bus=selection,
        _undo_manager=undo,
        _viewport_window=SimpleNamespace(
            _transform_model=SimpleNamespace(_transform=transform_adapter),
            _renderer=None,
        ),
        _current_file_path=None,
    )


def test_inspector_state_compares_usd_adapter_hierarchy_and_transforms() -> None:
    state = capture_application_state(_application_with_stage())

    assert state["provider"] == "openusd"
    assert state["selection"]["paths"] == ["/World/Cube"]
    assert state["usd"]["paths"] == ["/World", "/World/Cube"]
    assert state["adapter"]["paths"] == ["/World", "/World/Cube"]
    assert state["usd"]["default_prim"] == "/World"
    assert state["usd"]["prims"]["/World/Cube"]["attributes"]["size"]["value"] == 2.0
    assert state["transforms"]["paths"]["/World/Cube"]["matches"] is True
    assert state["parity"]["adapter_matches_usd"] is True
    assert state["parity"]["comparable_native"] is False
    assert state["parity"]["topology_matches"] is True
    assert state["parity"]["layers_match"] is True
    assert state["parity"]["ok"] is True


def test_inspector_state_records_layer_and_undo_edges_without_mutating() -> None:
    app = _application_with_stage()

    before = app._stage_adapter.stage.GetRootLayer().ExportToString()
    state = capture_application_state(app)
    after = app._stage_adapter.stage.GetRootLayer().ExportToString()

    assert before == after
    assert state["layers"]["available"] is True
    assert state["layers"]["edit_target"] == app._stage_adapter.stage.GetRootLayer().identifier
    assert state["undo"] == {
        "can_undo": False,
        "can_redo": False,
        "undo_depth": 0,
        "redo_depth": 0,
        "group_depth": 0,
        "undo_label": "",
        "redo_label": "",
        "stage_adapter_uses_app_manager": True,
    }


def test_property_ui_snapshot_exposes_read_only_real_field_geometry() -> None:
    app = _application_with_stage()
    adapter = UsdPropertyAdapter(
        app._stage_adapter.stage,
        ["/World/Cube"],
    )
    field = SimpleNamespace(
        screen_position_x=900.0,
        screen_position_y=250.0,
        computed_width=120.0,
        computed_height=22.0,
        enabled=True,
    )
    indicator_widget = SimpleNamespace(
        screen_position_x=1025.0,
        screen_position_y=257.0,
        computed_width=8.0,
        computed_height=8.0,
        visible=True,
    )
    row = SimpleNamespace(
        _widget=field,
        _indicator=SimpleNamespace(
            active_state=SimpleNamespace(name="NotDefault"),
            widget=indicator_widget,
        ),
    )
    filter_model = SimpleNamespace(get_value_as_string=lambda: "Size")
    app._property_window = SimpleNamespace(
        _adapter=adapter,
        _selection=["/World/Cube"],
        _inspector_attribute_rows={"size": row},
        _filter_field=SimpleNamespace(model=filter_model),
        _filter_border_rect=SimpleNamespace(
            name="focused",
            screen_position_x=850.0,
            screen_position_y=100.0,
            computed_width=300.0,
            computed_height=22.0,
        ),
        _filter_clear_button=None,
        _scroll_frame=None,
    )

    state = capture_application_state(app)

    property_ui = state["property_ui"]
    assert property_ui["available"] is True
    assert property_ui["filter_text"] == "Size"
    assert property_ui["filter_focused"] is True
    assert property_ui["rows"]["size"]["value"] == pytest.approx(2.0)
    assert property_ui["rows"]["size"]["field_points"] == [[960, 261]]
    assert property_ui["rows"]["size"]["indicator_state"] == "NotDefault"


def test_json_value_does_not_materialize_large_iterables() -> None:
    class LargeIterable:
        consumed = 0

        def __len__(self) -> int:
            return 1_000_000

        def __iter__(self):
            for value in range(1_000_000):
                self.consumed += 1
                yield value

    value = LargeIterable()

    result = _json_value(value)

    assert result["length"] == 1_000_000
    assert result["truncated"] is True
    assert result["sample"] == list(range(8))
    assert value.consumed == 8


def test_numeric_fingerprint_detects_large_array_tail_changes() -> None:
    left = list(range(512))
    right = list(left)
    right[-1] += 1

    left_fingerprint = _numeric_value_fingerprint(left)
    right_fingerprint = _numeric_value_fingerprint(right)

    assert left_fingerprint is not None
    assert right_fingerprint is not None
    assert left_fingerprint["complete"] is True
    assert left_fingerprint["shape"] == [512]
    assert left_fingerprint["sha256"] != right_fingerprint["sha256"]


def test_attribute_parity_rejects_decoded_and_opaque_numeric_mismatches() -> None:
    usd = {
        "prims": {
            "/World/Cube": {
                "source_authored": True,
                "attributes": {
                    "size": {"value": 2.0, "numeric_fingerprint": None},
                    "points": {
                        "value": [],
                        "numeric_fingerprint": {
                            "complete": True,
                            "bytes": 8,
                            "sha256": "usd-hash",
                        },
                    },
                },
            }
        }
    }
    native = {
        "prims": {
            "/World/Cube": {
                "attributes": {
                    "size": {"value": 3.0},
                    "points": {"bytes": 8, "sha256": "native-hash"},
                }
            }
        }
    }

    result = _attribute_value_parity(usd, native)

    assert result["compared_count"] == 2
    assert result["complete"] is True
    assert result["matches"] is False
    assert {item["key"] for item in result["mismatches"]} == {
        "/World/Cube.points",
        "/World/Cube.size",
    }


def test_attribute_parity_reports_absent_native_schema_fallback_as_gap() -> None:
    usd = {
        "prims": {
            "/World/Scope": {
                "source_authored": True,
                "attributes": {
                    "visibility": {
                        "value": "inherited",
                        "numeric_fingerprint": None,
                    }
                },
                "relationships": {},
            }
        }
    }
    native = {
        "prims": {
            "/World/Scope": {
                "attributes": {
                    "visibility": {"bytes": 0, "sha256": ""},
                }
            }
        }
    }

    result = _attribute_value_parity(usd, native)

    assert result["matches"] is True
    assert result["complete"] is False
    assert result["gaps"] == ["/World/Scope.visibility"]


def test_native_snapshot_omits_empty_byte_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ovui_data_adapters.ovstage import _native

    class _Stage:
        @staticmethod
        def read_attribute(*_args):
            return b""

    monkeypatch.setattr(
        _native,
        "read_token_attribute",
        lambda *_args: b"",
    )

    token = _native_attribute_snapshot(
        _Stage(),
        1,
        "/World/Mesh",
        "subdivisionScheme",
    )
    opaque = _native_attribute_snapshot(
        _Stage(),
        1,
        "/World/Mesh",
        "normals",
    )

    assert "value" not in token
    assert "value" not in opaque


def test_attribute_parity_requires_exact_native_relationship_and_connection_targets() -> None:
    usd = {
        "prims": {
            "/World/Cube": {
                "source_authored": True,
                "type_name": "Cube",
                "attributes": {},
                "relationships": {
                    "material:binding": {
                        "targets": ["/World/Looks/Material"],
                    }
                },
            },
            "/World/Looks/Material": {
                "source_authored": True,
                "type_name": "Material",
                "attributes": {
                    "outputs:surface": {
                        "connections": [
                            "/World/Looks/Material/Shader.outputs:surface"
                        ]
                    }
                },
                "relationships": {},
            },
        }
    }
    matching_native = {
        "prims": {
            "/World/Cube": {
                "attributes": {
                    "material:binding": {
                        "path_targets": ["/World/Looks/Material"],
                    }
                }
            },
            "/World/Looks/Material": {
                "attributes": {
                    "outputs:surface": {
                        "path_targets": [
                            "/World/Looks/Material/Shader.outputs:surface"
                        ],
                    }
                }
            },
        }
    }

    exact = _attribute_value_parity(usd, matching_native)

    assert exact["matches"] is True
    assert exact["path_targets_complete"] is True
    assert exact["unsupported_path_target_gaps"] == []
    assert exact["path_target_compared"] == [
        "/World/Cube.material:binding",
        "/World/Looks/Material.outputs:surface",
    ]

    missing_native = {
        "prims": {
            "/World/Cube": {"attributes": {}},
            "/World/Looks/Material": {"attributes": {}},
        }
    }
    missing = _attribute_value_parity(usd, missing_native)
    assert missing["matches"] is False
    assert missing["path_targets_complete"] is False
    assert missing["path_target_gaps"] == [
        "/World/Cube.material:binding",
    ]
    assert missing["unsupported_path_target_gaps"] == [
        {
            "key": "/World/Looks/Material.outputs:surface",
            "reason": (
                "OVStage 0.1 public query/read filters Fabric "
                "NameSuffix::connection columns, so neither the material "
                "output base name nor its .connect form produces a native "
                "read group"
            ),
        }
    ]

    binding_only_native = {
        "prims": {
            "/World/Cube": {
                "attributes": {
                    "material:binding": {
                        "path_targets": ["/World/Looks/Material"],
                    }
                }
            },
            "/World/Looks/Material": {"attributes": {}},
        }
    }
    accepted_runtime_limit = _attribute_value_parity(usd, binding_only_native)
    assert accepted_runtime_limit["matches"] is True
    assert accepted_runtime_limit["path_targets_complete"] is True
    assert accepted_runtime_limit["path_target_gaps"] == []
    assert accepted_runtime_limit["unsupported_path_target_gaps"][0]["key"] == (
        "/World/Looks/Material.outputs:surface"
    )

    wrong_connection_native = {
        "prims": {
            "/World/Cube": {
                "attributes": {
                    "material:binding": {
                        "path_targets": ["/World/Looks/Material"],
                    }
                }
            },
            "/World/Looks/Material": {
                "attributes": {
                    "outputs:surface": {
                        "path_targets": ["/World/Looks/Wrong.outputs:surface"],
                    }
                }
            },
        }
    }
    wrong_connection = _attribute_value_parity(usd, wrong_connection_native)
    assert wrong_connection["matches"] is False
    assert wrong_connection["unsupported_path_target_gaps"] == []
    assert wrong_connection["mismatches"][0]["kind"] == "path_targets"


def test_attribute_parity_does_not_waive_non_material_connections() -> None:
    usd = {
        "prims": {
            "/World/Looks/Shader": {
                "source_authored": True,
                "type_name": "Shader",
                "attributes": {
                    "inputs:color": {
                        "connections": ["/World/Looks/Texture.outputs:rgb"],
                    }
                },
                "relationships": {},
            }
        }
    }
    native = {
        "prims": {
            "/World/Looks/Shader": {
                "attributes": {},
            }
        }
    }

    result = _attribute_value_parity(usd, native)

    assert result["matches"] is False
    assert result["path_target_gaps"] == [
        "/World/Looks/Shader.inputs:color",
    ]
    assert result["unsupported_path_target_gaps"] == []


def test_topology_and_layer_parity_reject_order_type_and_target_drift() -> None:
    usd = {
        "prims": {
            "/World": {
                "source_authored": True,
                "type_name": "Xform",
                "children": ["/World/A", "/World/B"],
            },
            "/World/A": {
                "source_authored": True,
                "type_name": "Cube",
                "children": [],
            },
            "/World/B": {
                "source_authored": True,
                "type_name": "Sphere",
                "children": [],
            },
        }
    }
    adapter = {
        "prims": {
            "/World": {"type_name": "Xform", "children": ["/World/B", "/World/A"]},
            "/World/A": {"type_name": "Sphere", "children": []},
            "/World/B": {"type_name": "Sphere", "children": []},
        }
    }
    native = {
        "prims": {
            "/World": {"type_name": "Xform"},
            "/World/A": {"type_name": "Cube"},
            "/World/B": {"type_name": "Cone"},
        }
    }

    topology = _topology_value_parity(usd, native, adapter)

    assert topology["matches"] is False
    assert topology["adapter_type_mismatches"][0]["path"] == "/World/A"
    assert topology["native_type_mismatches"][0]["path"] == "/World/B"
    assert topology["child_order_mismatches"][0]["path"] == "/World"

    layers = {
        "available": True,
        "edit_target": "root.usda",
        "identifiers": ["root.usda"],
        "layers": {"root.usda": {"sublayers": ["a.usda", "b.usda"]}},
    }
    backing = {
        "available": True,
        "edit_target": "other.usda",
        "layers": {"root.usda": {"sublayers": ["b.usda", "a.usda"]}},
    }
    layer_result = _layer_state_parity(layers, backing)
    assert layer_result["matches"] is False
    assert layer_result["edit_target_matches"] is False
    assert layer_result["sublayer_mismatches"]


def test_topology_retains_unregistered_usd_type_while_accepting_native_xform() -> None:
    usd = {
        "prims": {
            "/World/Sensor": {
                "source_authored": True,
                "type_name": "OmniLidar",
                "schema_registered": False,
                "children": [],
            }
        }
    }
    adapter = {
        "prims": {
            "/World/Sensor": {
                "type_name": "OmniLidar",
                "children": [],
            }
        }
    }
    native = {"prims": {"/World/Sensor": {"type_name": "Xform"}}}

    result = _topology_value_parity(usd, native, adapter)

    assert result["matches"] is True
    assert result["adapter_type_mismatches"] == []
    assert result["native_type_mismatches"] == []
    assert result["representation_fallbacks"] == [
        {
            "path": "/World/Sensor",
            "usd": "OmniLidar",
            "ovstage": "Xform",
            "reason": "unregistered USD typed schema normalized to OVStage Xform",
        }
    ]

    adapter["prims"]["/World/Sensor"]["type_name"] = "Xform"
    adapter_drift = _topology_value_parity(usd, native, adapter)
    assert adapter_drift["matches"] is False
    assert adapter_drift["adapter_type_mismatches"] == [
        {
            "path": "/World/Sensor",
            "usd": "OmniLidar",
            "adapter": "Xform",
        }
    ]


def test_layer_parity_compares_exact_logical_stack_and_muted_set() -> None:
    layers = {
        "available": True,
        "root": "root.usda",
        "edit_target": "root.usda",
        "identifiers": ["root.usda", "muted.usda"],
        "layers": {
            "root.usda": {
                "anonymous": False,
                "dirty": False,
                "muted": False,
                "sublayers": ["muted.usda"],
            },
            "muted.usda": {
                "anonymous": False,
                "dirty": False,
                "muted": True,
                "sublayers": [],
            },
        },
    }
    backing = {
        "available": True,
        "source": "root.usda",
        "edit_target": "root.usda",
        "logical_identifiers": ["root.usda", "muted.usda"],
        "muted_identifiers": ["muted.usda"],
        "layers": {
            "root.usda": {
                "anonymous": False,
                "dirty": False,
                "resolved_sublayers": ["muted.usda"],
            },
            "muted.usda": {
                "anonymous": False,
                "dirty": False,
                "resolved_sublayers": [],
            },
        },
    }

    exact = _layer_state_parity(layers, backing)

    assert exact["matches"] is True
    assert exact["muted_matches"] is True
    assert exact["root_matches"] is True

    backing["muted_identifiers"] = []
    mute_drift = _layer_state_parity(layers, backing)
    assert mute_drift["matches"] is False
    assert mute_drift["adapter_muted"] == ["muted.usda"]
    assert mute_drift["backing_muted"] == []

    backing["muted_identifiers"] = ["muted.usda"]
    backing["logical_identifiers"].append("missing-in-adapter.usda")
    missing = _layer_state_parity(layers, backing)
    assert missing["matches"] is False
    assert missing["missing_in_adapter"] == ["missing-in-adapter.usda"]

    backing["logical_identifiers"].remove("missing-in-adapter.usda")
    layers["identifiers"].append("population-wrapper.usda")
    layers["layers"]["population-wrapper.usda"] = {
        "anonymous": True,
        "dirty": False,
        "muted": False,
        "sublayers": [],
    }
    # The backing snapshot may know about OVStage's synthetic wrapper, but it
    # is deliberately absent from the logical stack and must never leak into
    # the provider-neutral Layers adapter.
    backing["layers"]["population-wrapper.usda"] = {
        "anonymous": True,
        "dirty": False,
        "resolved_sublayers": [],
    }
    wrapper_leak = _layer_state_parity(layers, backing)
    assert wrapper_leak["matches"] is False
    assert wrapper_leak["missing_in_backing"] == ["population-wrapper.usda"]


def test_backing_layer_snapshot_retains_muted_logical_layers(tmp_path) -> None:
    child_path = tmp_path / "muted.usda"
    child_stage = Usd.Stage.CreateNew(str(child_path))
    assert child_stage is not None
    UsdGeom.Xform.Define(child_stage, "/MutedContent")
    assert child_stage.GetRootLayer().Save()
    child_identifier = child_stage.GetRootLayer().identifier

    root_path = tmp_path / "root.usda"
    stage = Usd.Stage.CreateNew(str(root_path))
    assert stage is not None
    stage.GetRootLayer().subLayerPaths = [str(child_path)]
    assert stage.GetRootLayer().Save()
    root_identifier = stage.GetRootLayer().identifier
    stage.MuteLayer(child_identifier)
    scene = SimpleNamespace(backing_usd_source_layer=stage.GetRootLayer())

    snapshot = _backing_layer_snapshot(stage, scene)

    assert snapshot["available"] is True
    assert snapshot["logical_identifiers"] == [root_identifier, child_identifier]
    assert snapshot["muted_identifiers"] == [child_identifier]
    assert child_identifier in snapshot["layers"]
    assert snapshot["layers"][root_identifier]["resolved_sublayers"] == [
        child_identifier
    ]
    assert snapshot["layers"][child_identifier]["content_size"] > 0
    assert snapshot["layers"][child_identifier]["content_sha256"]


def test_bridge_identity_is_fail_closed_for_incomplete_native_scene() -> None:
    result = _bridge_identity_snapshot(object(), object())

    assert result["required"] is True
    assert result["available"] is False
    assert result["matches"] is False


def test_file_fingerprint_streams_large_files(tmp_path) -> None:
    payload = (b"0123456789abcdef" * 200_000) + b"tail"
    path = tmp_path / "large.usda"
    path.write_bytes(payload)

    fingerprint = _file_fingerprint(str(path))

    assert fingerprint == {
        "exists": True,
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def test_viewport_projection_is_capped_for_large_stages() -> None:
    path_count = 400
    usd_snapshot = {
        "prims": {
            f"/World/P{index}": {
                "source_authored": True,
            }
            for index in range(path_count)
        }
    }
    calls: list[list[str]] = []

    def bounds(paths):
        calls.append(list(paths))
        return ((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))

    app = SimpleNamespace(
        _stage_adapter=SimpleNamespace(compute_world_aabb=bounds),
        _viewport_window=SimpleNamespace(
            _image=SimpleNamespace(
                computed_width=640,
                computed_height=480,
                screen_position_x=0.0,
                screen_position_y=0.0,
            ),
            _camera=SimpleNamespace(
                get_matrices=lambda _width, _height: (
                    Gf.Matrix4d(1.0),
                    Gf.Matrix4d(1.0),
                )
            ),
        ),
    )

    snapshot = _viewport_snapshot(app, usd_snapshot)

    assert len(calls) == 256
    assert snapshot["projection_path_limit"] == 256
    assert snapshot["projection_paths_truncated"] is True


# ── Native-only provider evidence (no backing USD stage) ──────────────────────


class _NativeStageStub:
    """Minimal native OVStage stage surface used by _ovstage_snapshot."""

    def __init__(self, prims=None, children=None):
        # path -> native type name; parent path -> ordered child paths.
        self._prims = dict(prims or {"/World": "Xform"})
        self._children = dict(children or {})

    def query_prims(self, ordinal):
        groups = []
        for handle, (path, type_name) in enumerate(self._prims.items(), start=1):
            groups.append(
                {
                    "prim_list_handle": handle,
                    "prim_type": type_name,
                    "applied_schemas": [],
                    "attributes": [],
                }
            )
        return {"groups": groups}

    def get_prim_paths(self, handle):
        return [list(self._prims)[handle - 1]]

    def get_child_paths(self, path):
        if path == "" and "" not in self._children:
            # Native root query convention: the pseudo-root's ordered
            # top-level children. Derive them from the prim table when a
            # fixture does not spell them out.
            return [p for p in self._prims if p.count("/") == 1]
        return list(self._children.get(path, ()))

    def get_topology_version(self):
        return 1


class _NativeAdapterItem:
    def __init__(self, path: str) -> None:
        self.path = path


class _NativeAdapterStub:
    """StageAdapter surface exposing the same hierarchy as the native scene."""

    def __init__(self, child_paths=("/World",), types=None, children=None) -> None:
        self._child_paths = list(child_paths)
        self._types = dict(types or {})
        self._children = dict(children or {})

    def get_root(self):
        return _NativeAdapterItem("/")

    def get_item_path(self, item):
        return item.path

    def get_children(self, item):
        if item.path == "/":
            return [_NativeAdapterItem(path) for path in self._child_paths]
        return [
            _NativeAdapterItem(path)
            for path in self._children.get(item.path, ())
        ]

    def get_display_name(self, item):
        return item.path.rsplit("/", 1)[-1] or "/"

    def get_type_name(self, item):
        return self._types.get(item.path, "Xform")

    def get_type_category(self, item):
        return "xform"

    def get_badge_flags(self, item):
        return 0

    def get_item_flags(self, item):
        return 0

    def compute_visibility(self, item):
        return "VISIBLE"


def _native_application(
    adapter_child_paths=("/World",),
    stage=None,
    adapter=None,
) -> SimpleNamespace:
    from ovui_data_adapters.ovstage.stage_adapter import (
        is_user_facing_scene_path,
    )

    scene = SimpleNamespace(
        _stage=stage or _NativeStageStub(),
        current_ordinal=3,
        source_path="/tmp/native-scene.usda",
        is_open=True,
    )
    # Expose the REAL production ownership rule through the same provider
    # session hook the OvstageProviderSession implements, so these tests
    # exercise the shared rule rather than a re-implementation.
    session = SimpleNamespace(
        current_scene=scene,
        inspector_user_facing_scene_path=lambda path: is_user_facing_scene_path(
            path, scene, scene._stage
        ),
    )
    return SimpleNamespace(
        _adapter_provider=SimpleNamespace(name="ovstage"),
        _adapter_session=session,
        _stage_adapter=adapter or _NativeAdapterStub(adapter_child_paths),
        _layer_adapter=None,
        _selection_bus=None,
        _undo_manager=None,
        _viewport_window=SimpleNamespace(_transform_model=None, _renderer=None),
        _current_file_path="/tmp/native-scene.usda",
    )


def test_native_only_session_parity_passes_without_backing_usd() -> None:
    """A valid native session must not fail parity because the retired
    backing-USD bridge, StageCache identity, and backing layers are absent."""

    state = capture_application_state(_native_application())
    parity = state["parity"]

    assert state["provider"] == "ovstage"
    assert state["usd"]["available"] is False
    assert state["ovstage"]["available"] is True
    assert parity["baseline"] == "ovstage"
    assert parity["comparable"] is True
    assert state["bridge_identity"]["required"] is False
    assert parity["bridge_identity_matches"] is True
    assert parity["layers_match"] is True
    assert parity["adapter_matches_baseline"] is True
    # Legacy USD-baseline fields are explicitly not applicable (None) when no
    # USD view exists — native evidence must never read as a USD match.
    assert parity["adapter_matches_usd"] is None
    assert parity["ovstage_matches_expected_usd"] is None
    assert parity["ok"] is True


def test_native_only_session_parity_fails_on_adapter_drift() -> None:
    """Native evidence stays fail-closed: an adapter view that diverges from
    the native scene must still fail parity."""

    state = capture_application_state(_native_application(adapter_child_paths=()))
    parity = state["parity"]

    assert parity["baseline"] == "ovstage"
    assert parity["missing_in_adapter"] == ["/World"]
    assert parity["ok"] is False


def test_bridge_identity_not_required_without_backing_stage() -> None:
    """The native provider has no backing-USD bridge, so its absence is not a
    parity failure; the fail-closed case with both views remains covered by
    test_bridge_identity_is_fail_closed_for_incomplete_native_scene."""

    result = _bridge_identity_snapshot(None, object())

    assert result["required"] is False
    assert result["matches"] is True


def test_layer_parity_vacuous_only_when_neither_view_exists() -> None:
    both_absent = _layer_state_parity({"available": False}, {"available": False})
    one_sided = _layer_state_parity({"available": True, "identifiers": []}, {"available": False})

    assert both_absent["comparable"] is False
    assert both_absent["matches"] is True
    assert one_sided["comparable"] is False
    assert one_sided["matches"] is False


def test_absent_authority_parity_is_indeterminate_not_success() -> None:
    """With neither a USD nor a native OVStage view, parity must be
    explicitly indeterminate — never an affirmative result — and adapter/UI
    evidence must be surfaced as unverified rather than silently discarded."""

    from ovui_widgets.app.inspector_state import _parity_snapshot

    usd = {"available": False, "paths": [], "prims": {}}
    native = {"available": False, "paths": [], "prims": {}}
    empty_adapter = {"available": True, "paths": [], "prims": {}}
    stale_adapter = {
        "available": True,
        "paths": ["/Stale"],
        "prims": {"/Stale": {"type_name": "Xform", "children": []}},
    }
    bridge = _bridge_identity_snapshot(None, None)
    layers = {"available": False}
    backing = {"available": False, "layers": {}}

    for adapter in (empty_adapter, stale_adapter):
        parity = _parity_snapshot(
            usd, native, adapter, {"mismatches": []}, layers, backing, bridge
        )
        assert parity["baseline"] is None
        assert parity["comparable"] is False
        assert parity["indeterminate_reason"]
        assert parity["adapter_matches_baseline"] is False
        assert parity["adapter_matches_usd"] is None
        assert parity["ovstage_matches_expected_usd"] is None
        assert parity["ok"] is False

    stale = _parity_snapshot(
        usd, native, stale_adapter, {"mismatches": []}, layers, backing, bridge
    )
    assert stale["unverified_adapter_paths"] == ["/Stale"]


def test_absent_authority_full_capture_is_indeterminate() -> None:
    """A full snapshot with no open scene (no provider view at all) must not
    affirm parity even though the adapter/UI side still reports content."""

    app = _native_application()
    app._adapter_session = SimpleNamespace(current_scene=None)

    state = capture_application_state(app)
    parity = state["parity"]

    assert state["usd"]["available"] is False
    assert state["ovstage"]["available"] is False
    assert parity["comparable"] is False
    assert parity["unverified_adapter_paths"] == ["/World"]
    assert parity["ok"] is False


def _native_hierarchy_fixtures(adapter_types=None, adapter_children=None):
    stage = _NativeStageStub(
        prims={"/World": "Xform", "/World/A": "Mesh", "/World/B": "Camera"},
        children={"/World": ("/World/A", "/World/B")},
    )
    adapter = _NativeAdapterStub(
        child_paths=("/World",),
        types=adapter_types
        or {"/World": "Xform", "/World/A": "Mesh", "/World/B": "Camera"},
        children=adapter_children or {"/World": ("/World/A", "/World/B")},
    )
    return _native_application(stage=stage, adapter=adapter)


def test_native_topology_matching_hierarchy_passes_non_vacuously() -> None:
    """Native-baseline topology parity actually compares types and ordered
    children — a fully matching hierarchy passes with a non-zero compared
    path count."""

    state = capture_application_state(_native_hierarchy_fixtures())
    parity = state["parity"]

    assert parity["baseline"] == "ovstage"
    assert parity["topology"]["compared_path_count"] == 3
    assert parity["topology_matches"] is True
    assert parity["ok"] is True


def test_native_equal_path_type_drift_fails() -> None:
    """The same path reported with different types by the native scene and
    the adapter must fail native parity with concrete evidence."""

    state = capture_application_state(
        _native_hierarchy_fixtures(
            adapter_types={"/World": "Mesh", "/World/A": "Mesh", "/World/B": "Camera"},
        )
    )
    parity = state["parity"]

    assert parity["topology"]["adapter_type_mismatches"] == [
        {"path": "/World", "ovstage": "Xform", "adapter": "Mesh"}
    ]
    assert parity["topology_matches"] is False
    assert parity["ok"] is False


def test_native_child_order_drift_fails() -> None:
    """Adapter child ordering that disagrees with the native scene's
    recorded ordered children must fail native parity."""

    state = capture_application_state(
        _native_hierarchy_fixtures(
            adapter_children={"/World": ("/World/B", "/World/A")},
        )
    )
    parity = state["parity"]

    assert parity["topology"]["child_order_mismatches"] == [
        {
            "path": "/World",
            "ovstage": ["/World/A", "/World/B"],
            "adapter": ["/World/B", "/World/A"],
        }
    ]
    assert parity["topology_matches"] is False
    assert parity["ok"] is False


# ── Native child-topology authority (fail-closed) ─────────────────────────────


def test_native_child_enumeration_exception_fails_closed() -> None:
    """A throwing native child enumeration must be surfaced as an authority
    error and prevent affirmative parity — not become an empty child list."""

    class _ThrowingStage(_NativeStageStub):
        def get_child_paths(self, path):
            raise RuntimeError("native enumeration failed")

    state = capture_application_state(_native_application(stage=_ThrowingStage()))
    parity = state["parity"]
    topology = parity["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "RuntimeError: native enumeration failed" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert parity["topology_matches"] is False
    assert parity["ok"] is False


def test_native_child_enumeration_missing_fails_closed() -> None:
    """A native stage without child enumeration cannot prove hierarchy
    parity; the missing authority is explicit evidence, not a silent skip."""

    class _NoEnumerationStage(_NativeStageStub):
        get_child_paths = None

    state = capture_application_state(
        _native_application(stage=_NoEnumerationStage())
    )
    parity = state["parity"]
    topology = parity["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "no callable get_child_paths" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert parity["ok"] is False


def test_native_child_enumeration_malformed_fails_closed() -> None:
    """Non-iterable/malformed enumeration output is an authority error."""

    class _MalformedStage(_NativeStageStub):
        def get_child_paths(self, path):
            return 42

    state = capture_application_state(_native_application(stage=_MalformedStage()))
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "non-iterable child enumeration result" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert state["parity"]["ok"] is False


def test_native_unknown_enumerated_child_is_surfaced_as_drift() -> None:
    """A child reported by native enumeration but absent from the adapter
    view (and the queried prim set) must surface as hierarchy drift instead
    of being silently discarded."""

    stage = _NativeStageStub(
        prims={"/World": "Xform"},
        children={"": ("/World",), "/World": ("/World/Ghost",)},
    )
    state = capture_application_state(_native_application(stage=stage))
    parity = state["parity"]

    assert parity["topology"]["child_order_mismatches"] == [
        {"path": "/World", "ovstage": ["/World/Ghost"], "adapter": []}
    ]
    assert parity["ok"] is False


def test_native_root_order_drift_fails() -> None:
    """Top-level ordering is compared against the native pseudo-root query
    (get_child_paths(\"\")); a reversed adapter root order must fail."""

    stage = _NativeStageStub(
        prims={"/A": "Xform", "/B": "Xform"},
        children={"": ("/A", "/B")},
    )
    adapter = _NativeAdapterStub(
        child_paths=("/B", "/A"),
        types={"/A": "Xform", "/B": "Xform"},
    )
    state = capture_application_state(
        _native_application(stage=stage, adapter=adapter)
    )
    parity = state["parity"]

    assert parity["topology"]["child_order_mismatches"] == [
        {"path": "/", "ovstage": ["/A", "/B"], "adapter": ["/B", "/A"]}
    ]
    assert parity["topology_matches"] is False
    assert parity["ok"] is False


def test_native_matching_hierarchy_includes_root_order_authority() -> None:
    """The passing case proves the authority is present and the root order
    was actually compared, not skipped."""

    state = capture_application_state(_native_hierarchy_fixtures())
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is True
    assert topology["authority_errors"] == []
    assert state["parity"]["ok"] is True


# ── Strict native child-path validation and scene ownership ───────────────────


class _BadItem:
    def __str__(self) -> str:
        raise ValueError("unconvertible child item")


@pytest.mark.parametrize(
    ("children", "fragment"),
    [
        (("/World/A", "/World/A"), "duplicate child path"),
        (("Child",), "relative child path"),
        (("",), "empty or root child path"),
        (("/",), "empty or root child path"),
        (("/Other/Kid",), "not a direct child"),
        (("/World/A/",), "non-canonical child path"),
        (("/World//A",), "non-canonical child path"),
        (("/World/A", "Child"), "relative child path"),
    ],
)
def test_native_invalid_child_enumeration_fails_closed(children, fragment) -> None:
    """Iterable-but-invalid native child lists (duplicates, relative, empty,
    root, wrong-parent, non-canonical, or mixed valid/invalid) are authority
    errors, never authoritative evidence."""

    stage = _NativeStageStub(
        prims={"/World": "Xform", "/World/A": "Xform"},
        children={"": ("/World",), "/World": children},
    )
    state = capture_application_state(_native_application(stage=stage))
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(fragment in entry["error"] for entry in topology["authority_errors"])
    assert state["parity"]["ok"] is False


def test_native_unconvertible_child_item_fails_closed() -> None:
    stage = _NativeStageStub(
        prims={"/World": "Xform"},
        children={"": ("/World",), "/World": (_BadItem(),)},
    )
    state = capture_application_state(_native_application(stage=stage))
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "non-string child item" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert state["parity"]["ok"] is False


def test_renderer_owned_presentation_content_is_not_drift() -> None:
    """Provider-owned presentation topology below a scene-registered
    presentation root is rightly hidden by the adapter and must not reject
    parity — the same ownership rule as the production adapter."""

    stage = _NativeStageStub(
        prims={
            "/World": "Xform",
            "/_OvuiRuntime": "Xform",
            "/_OvuiRuntime/Camera": "Camera",
        },
        children={
            "": ("/World", "/_OvuiRuntime"),
            "/_OvuiRuntime": ("/_OvuiRuntime/Camera",),
        },
    )
    app = _native_application(stage=stage)
    app._adapter_session.current_scene.presentation_root_paths = ("/_OvuiRuntime",)

    state = capture_application_state(app)
    parity = state["parity"]

    assert state["ovstage"]["prims"]["/_OvuiRuntime"]["user_facing"] is False
    assert parity["missing_in_adapter"] == []
    assert parity["topology"]["child_order_mismatches"] == []
    assert parity["ok"] is True


def test_user_authored_render_content_missing_from_adapter_is_drift() -> None:
    """/Render authored by the user (native birth record) is user-facing per
    the production ownership rule; hiding it in the adapter is drift."""

    stage = _NativeStageStub(
        prims={"/World": "Xform", "/Render": "Scope", "/Render/User": "Xform"},
        children={"": ("/World", "/Render"), "/Render": ("/Render/User",)},
    )
    stage._ovui_path_birth_ordinals = {"/Render": 1}

    state = capture_application_state(_native_application(stage=stage))
    parity = state["parity"]

    assert state["ovstage"]["prims"]["/Render"]["user_facing"] is True
    assert parity["missing_in_adapter"] == ["/Render", "/Render/User"]
    assert parity["ok"] is False


def test_unauthored_render_content_remains_provider_internal() -> None:
    """Without a user birth record, /Render stays provider-internal (the
    conditional-runtime-root rule) and its absence from the adapter is not
    drift — matching production filtering."""

    stage = _NativeStageStub(
        prims={"/World": "Xform", "/Render": "Scope", "/Render/Var": "Xform"},
        children={"": ("/World", "/Render"), "/Render": ("/Render/Var",)},
    )

    state = capture_application_state(_native_application(stage=stage))
    parity = state["parity"]

    assert state["ovstage"]["prims"]["/Render"]["user_facing"] is False
    assert parity["missing_in_adapter"] == []
    assert parity["ok"] is True


def test_missing_provider_ownership_hook_fails_closed() -> None:
    """Without the provider's inspector_user_facing_scene_path evidence hook,
    ownership cannot be decided and topology authority is unavailable."""

    app = _native_application()
    app._adapter_session = SimpleNamespace(
        current_scene=app._adapter_session.current_scene
    )

    state = capture_application_state(app)
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "inspector_user_facing_scene_path" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert state["parity"]["ok"] is False


@pytest.mark.parametrize(
    ("children", "fragment"),
    [
        (("/Render/.",), "dot-segment child path"),
        (("/Render/..",), "dot-segment child path"),
        (("/Render/./Nested",), "dot-segment child path"),
    ],
)
def test_native_dot_segment_children_fail_closed_even_when_provider_owned(
    children, fragment
) -> None:
    """Dot-segment children violate the production canonical-path contract
    and must fail authority BEFORE ownership filtering — a malformed child
    below a provider-owned root must not vanish into an ok=True result."""

    stage = _NativeStageStub(
        prims={"/World": "Xform", "/Render": "Scope"},
        children={"": ("/World", "/Render"), "/Render": children},
    )
    state = capture_application_state(_native_application(stage=stage))
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(fragment in entry["error"] for entry in topology["authority_errors"])
    assert state["parity"]["ok"] is False


def test_native_non_string_child_below_provider_owned_root_fails_closed() -> None:
    """A non-string enumeration item is rejected as such (production rejects
    non-strings outright), even when its string form looks provider-owned."""

    class _RenderLookalike:
        def __str__(self) -> str:
            return "/Render/Internal"

    stage = _NativeStageStub(
        prims={"/World": "Xform", "/Render": "Scope"},
        children={"": ("/World", "/Render"), "/Render": (_RenderLookalike(),)},
    )
    state = capture_application_state(_native_application(stage=stage))
    topology = state["parity"]["topology"]

    assert topology["child_topology_available"] is False
    assert any(
        "non-string child item of type _RenderLookalike" in entry["error"]
        for entry in topology["authority_errors"]
    )
    assert state["parity"]["ok"] is False


def test_native_unicode_child_names_remain_valid() -> None:
    """Valid Unicode prim names supported by production stay authoritative
    (NFC and NFD spellings are distinct, both acceptable paths)."""

    nfc = "/Wörld"
    nfd = "/Wörld"
    stage = _NativeStageStub(
        prims={nfc: "Xform", nfd: "Xform"},
        children={"": (nfc, nfd)},
    )
    adapter = _NativeAdapterStub(
        child_paths=(nfc, nfd),
        types={nfc: "Xform", nfd: "Xform"},
    )
    state = capture_application_state(
        _native_application(stage=stage, adapter=adapter)
    )
    parity = state["parity"]

    assert parity["topology"]["child_topology_available"] is True
    assert parity["topology"]["authority_errors"] == []
    assert parity["ok"] is True
