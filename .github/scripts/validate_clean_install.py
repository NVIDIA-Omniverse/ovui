# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""Validate one clean-install package contract from built wheels."""

from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path
from types import ModuleType

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _assert_requirement(distribution: str, requirement: str) -> None:
    requirements = metadata.requires(distribution) or []
    assert requirement in requirements, (
        f"{distribution} does not declare {requirement!r}: {requirements!r}"
    )


def _assert_installed_module(module: ModuleType) -> Path:
    module_path = Path(module.__file__).resolve()
    assert not module_path.is_relative_to(_REPOSITORY_ROOT), (
        f"{module.__name__} was imported from the source checkout: {module_path}"
    )
    return module_path


def _validate_common() -> None:
    import numpy
    import ovui_data_adapters.common as common
    import ovui_data_adapters.common._livestream_tap as livestream

    _assert_requirement("ovui-data-adapters-common", "numpy>=1.20")
    assert "ovstream" not in sys.modules, (
        "common import eagerly loaded optional ovstream"
    )

    try:
        metadata.version("ovui-data-adapters-openusd")
    except metadata.PackageNotFoundError:
        pass
    else:
        raise AssertionError(
            "common-only environment unexpectedly contains the OpenUSD adapter"
        )

    print(
        "common clean install OK:",
        _assert_installed_module(common),
        _assert_installed_module(livestream),
        _assert_installed_module(numpy),
    )


def _validate_aggregate() -> None:
    import ovui_data_adapters.openusd as openusd
    import ovui_widgets.app as app
    from pxr import Usd

    _assert_requirement(
        "ovui-widgets-all",
        "ovui-data-adapters-openusd[standalone]>=0.2.0",
    )
    assert metadata.version("usd-core") == "25.11"
    assert Usd.Stage.CreateInMemory() is not None

    print(
        "ovui-widgets-all clean install OK:",
        _assert_installed_module(openusd),
        _assert_installed_module(app),
        Path(Usd.__file__).resolve(),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contract", choices=("common", "aggregate"))
    args = parser.parse_args()

    if args.contract == "common":
        _validate_common()
    else:
        _validate_aggregate()


if __name__ == "__main__":
    main()
