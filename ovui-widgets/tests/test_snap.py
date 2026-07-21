# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Tests for SnapSystem (Step 50)."""

import pytest

from ovui_widgets.common.snap import GridSnapProvider, SnapSystem, SurfaceSnapProvider


class TestSnapSystemDisabled:
    def test_passthrough_when_disabled(self):
        sys = SnapSystem()
        pos = [1.7, 2.3, 4.9]
        assert sys.snap(pos) == pytest.approx([1.7, 2.3, 4.9])

    def test_disabled_by_default_ignores_providers(self):
        sys = SnapSystem()
        sys.add_provider(GridSnapProvider(1.0))
        assert sys.snap([0.7, 0.7, 0.7]) == pytest.approx([0.7, 0.7, 0.7])


class TestGridSnapProvider:
    def test_snaps_to_nearest_grid_unit(self):
        p = GridSnapProvider(1.0)
        result = p.snap([0.6, 1.4, 2.7], None)
        assert result == pytest.approx([1.0, 1.0, 3.0])

    def test_grid_size_half(self):
        p = GridSnapProvider(0.5)
        result = p.snap([0.3, 0.7, 1.1], None)
        assert result == pytest.approx([0.5, 0.5, 1.0])

    def test_grid_size_two(self):
        p = GridSnapProvider(2.0)
        result = p.snap([0.9, 3.1, 5.9], None)
        assert result == pytest.approx([0.0, 4.0, 6.0])

    def test_constraint_axis_does_not_affect_result(self):
        p = GridSnapProvider(1.0)
        r1 = p.snap([0.6, 0.6, 0.6], "x")
        r2 = p.snap([0.6, 0.6, 0.6], None)
        assert r1 == pytest.approx(r2)

    def test_already_on_grid(self):
        p = GridSnapProvider(1.0)
        result = p.snap([2.0, 3.0, 0.0], None)
        assert result == pytest.approx([2.0, 3.0, 0.0])

    def test_live_grid_size_update_changes_subsequent_snap(self):
        provider = GridSnapProvider(1.0)

        provider.set_grid_size(0.25)

        assert provider.grid_size == pytest.approx(0.25)
        assert provider.snap([0.31, 0.62, 1.13], None) == pytest.approx(
            [0.25, 0.5, 1.25]
        )

    @pytest.mark.parametrize("value", [0.0, -1.0, float("inf"), float("nan")])
    def test_invalid_grid_sizes_are_rejected(self, value):
        with pytest.raises(ValueError, match="positive finite"):
            GridSnapProvider(value)


class TestSurfaceSnapProvider:
    def test_returns_none(self):
        p = SurfaceSnapProvider()
        assert p.snap([1.0, 2.0, 3.0], None) is None

    def test_returns_none_with_axis_constraint(self):
        p = SurfaceSnapProvider()
        assert p.snap([1.0, 2.0, 3.0], "y") is None

    def test_returns_none_for_any_position(self):
        p = SurfaceSnapProvider()
        assert p.snap([0.0, 0.0, 0.0], None) is None


class TestSnapSystemChain:
    def test_first_non_none_wins(self):
        sys = SnapSystem()
        sys.enable(True)
        sys.add_provider(SurfaceSnapProvider())
        sys.add_provider(GridSnapProvider(1.0))
        result = sys.snap([0.6, 0.4, 0.9])
        assert result == pytest.approx([1.0, 0.0, 1.0])

    def test_no_providers_passthrough(self):
        sys = SnapSystem()
        sys.enable(True)
        pos = [1.3, 2.7, 0.1]
        assert sys.snap(pos) == pytest.approx([1.3, 2.7, 0.1])

    def test_enable_disable_toggle(self):
        sys = SnapSystem()
        sys.add_provider(GridSnapProvider(1.0))
        pos = [0.7, 0.7, 0.7]
        assert sys.snap(pos) == pytest.approx([0.7, 0.7, 0.7])
        sys.enable(True)
        assert sys.snap(pos) == pytest.approx([1.0, 1.0, 1.0])
        sys.enable(False)
        assert sys.snap(pos) == pytest.approx([0.7, 0.7, 0.7])

    def test_grid_provider_alone_snaps(self):
        sys = SnapSystem()
        sys.enable(True)
        sys.add_provider(GridSnapProvider(0.5))
        assert sys.snap([0.3, 0.8, 1.2]) == pytest.approx([0.5, 1.0, 1.0])
