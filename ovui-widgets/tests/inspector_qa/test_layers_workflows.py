# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Ledger partition guard for the native-only OVStage layer surface.

The exact OVStage 0.1 API exposes no logical USD layer stack, so the layer
adapter is truthfully inert and every ``layers.*`` ledger entry is an accepted
limitation closed by contract evidence. The former hybrid Inspector layer
scenarios and their backing-USD fixtures were removed together with the
OpenUSD bridge.
"""

from __future__ import annotations

import json
from pathlib import Path


def test_layer_scenario_contracts_partition_supported_ledger() -> None:
    """Every layer feature is an accepted limitation of the native provider."""

    matrix_path = Path(__file__).with_name("feature-matrix.json")
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    layer_features = [
        feature for feature in matrix["features"] if feature["id"].startswith("layers.")
    ]
    assert layer_features
    for feature in layer_features:
        # The exact OVStage 0.1 API exposes no logical USD layer stack; the
        # native layer adapter is truthfully inert, so no layer feature may
        # claim support or Inspector coverage.
        assert feature["support_status"] == "accepted_unsupported", feature["id"]
        assert feature["evidence_status"] == "contract_covered", feature["id"]
        assert feature.get("scope_note", "").strip(), feature["id"]
        assert feature.get("contract_evidence"), feature["id"]
        assert "scenarios" not in feature, feature["id"]
