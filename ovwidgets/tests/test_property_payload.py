# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for PropertyPayload — Step 0.2.

Covers the six done-signal cases (equality, len, bool, scheme default,
large-selection threshold, iter) plus a handful of high-value extras
(paths defensive copy, compute_shared_attrs delegation).
"""

from ovwidgets.property import PropertyPayload
from ovwidgets.property.payload import PropertyPayload as PropertyPayloadDirect


class TestPublicExport:
    def test_reexport_from_package(self):
        assert PropertyPayload is PropertyPayloadDirect


class TestConstruction:
    def test_scheme_default(self):
        p = PropertyPayload(["/World/Cube"])
        assert p.get_scheme() == "default"

    def test_scheme_custom(self):
        p = PropertyPayload(["/World/Cube"], scheme="material")
        assert p.get_scheme() == "material"

    def test_paths_defensive_copy(self):
        src = ["/World/A", "/World/B"]
        p = PropertyPayload(src)
        src.append("/World/C")
        assert list(p) == ["/World/A", "/World/B"]

    def test_paths_property_returns_copy(self):
        p = PropertyPayload(["/World/A"])
        out = p.paths
        out.append("/World/B")
        assert list(p) == ["/World/A"]


class TestBool:
    def test_empty_is_falsy(self):
        assert not PropertyPayload([])

    def test_nonempty_is_truthy(self):
        assert PropertyPayload(["/World/Cube"])


class TestLen:
    def test_len_zero(self):
        assert len(PropertyPayload([])) == 0

    def test_len_matches_paths(self):
        assert len(PropertyPayload(["/a", "/b", "/c"])) == 3


class TestIter:
    def test_iter_yields_paths_in_order(self):
        paths = ["/World/A", "/World/B", "/World/C"]
        assert list(PropertyPayload(paths)) == paths

    def test_iter_empty(self):
        assert list(PropertyPayload([])) == []


class TestEquality:
    def test_eq_same_paths_and_scheme(self):
        a = PropertyPayload(["/x", "/y"], scheme="default")
        b = PropertyPayload(["/x", "/y"], scheme="default")
        assert a == b

    def test_neq_different_paths(self):
        assert PropertyPayload(["/x"]) != PropertyPayload(["/y"])

    def test_neq_different_scheme(self):
        a = PropertyPayload(["/x"], scheme="default")
        b = PropertyPayload(["/x"], scheme="material")
        assert a != b

    def test_neq_different_order(self):
        assert PropertyPayload(["/a", "/b"]) != PropertyPayload(["/b", "/a"])

    def test_neq_non_payload(self):
        assert PropertyPayload(["/x"]) != ["/x"]


class TestLargeSelection:
    def test_default_threshold_boundary(self):
        assert not PropertyPayload([f"/p/{i}" for i in range(99)]).is_large_selection()
        assert PropertyPayload([f"/p/{i}" for i in range(100)]).is_large_selection()

    def test_custom_threshold(self):
        p = PropertyPayload([f"/p/{i}" for i in range(5)])
        assert p.is_large_selection(threshold=3)
        assert not p.is_large_selection(threshold=10)

    def test_empty_not_large(self):
        assert not PropertyPayload([]).is_large_selection()


class TestComputeSharedAttrs:
    def test_delegates_to_adapter(self):
        class FakeAdapter:
            def get_attribute_names(self):
                return ["xformOp:translate", "visibility"]

        p = PropertyPayload(["/World/Cube"])
        assert p.compute_shared_attrs(FakeAdapter()) == [
            "xformOp:translate",
            "visibility",
        ]

    def test_returns_independent_list(self):
        class FakeAdapter:
            def __init__(self):
                self.canonical = ["a", "b"]

            def get_attribute_names(self):
                return self.canonical

        adapter = FakeAdapter()
        out = PropertyPayload(["/x"]).compute_shared_attrs(adapter)
        out.append("c")
        assert adapter.canonical == ["a", "b"]
