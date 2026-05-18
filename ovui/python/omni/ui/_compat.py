# SPDX-FileCopyrightText: Copyright (c) 2018-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: LicenseRef-NvidiaProprietary
#
# NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
# property and proprietary rights in and to this material, related
# documentation and any modifications thereto. Any use, reproduction,
# disclosure or distribution of this material and related documentation
# without an express license agreement from NVIDIA CORPORATION or
# its affiliates is strictly prohibited.

"""
Compatibility shim for running omni.ui inside Kit or standalone.

Provides unified helpers for:
- Logging (Kit: carb.log_*, standalone: Python logging)
- Settings access (Kit: carb.settings, standalone: in-memory dict)
- Frame stepping (Kit: omni.kit.app update, standalone: no-op)
"""

import importlib.util
import logging as _logging

_IN_KIT = (importlib.util.find_spec("carb") is not None
           and importlib.util.find_spec("omni.kit.app") is not None)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

if _IN_KIT:
    import carb  # type: ignore

    log_info = carb.log_info
    log_warn = carb.log_warn
    log_error = carb.log_error
else:
    _logger = _logging.getLogger("omni.ui")

    log_info = _logger.info
    log_warn = _logger.warning
    log_error = _logger.error

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

if _IN_KIT:
    import carb.settings  # type: ignore

    def get_setting(path, default=None):
        """Read a setting value (Kit: carb.settings)."""
        settings = carb.settings.get_settings()
        val = settings.get(path)
        return val if val is not None else default

    def set_setting(path, value):
        """Write a setting value (Kit: carb.settings)."""
        settings = carb.settings.get_settings()
        settings.set(path, value)

    def subscribe_to_change(path, callback):
        """Subscribe to setting changes. Returns a subscription object."""
        settings = carb.settings.get_settings()
        return settings.subscribe_to_node_change_events(path, callback)

    def unsubscribe_to_change(subscription):
        """Unsubscribe from setting changes."""
        settings = carb.settings.get_settings()
        settings.unsubscribe_to_change_events(subscription)
else:
    _standalone_settings: dict = {}

    def get_setting(path, default=None):
        """Read a setting value (standalone: in-memory dict)."""
        return _standalone_settings.get(path, default)

    def set_setting(path, value):
        """Write a setting value (standalone: in-memory dict)."""
        _standalone_settings[path] = value

    def subscribe_to_change(path, callback):
        """No-op in standalone mode. Returns None."""
        return None

    def unsubscribe_to_change(subscription):
        """No-op in standalone mode."""
        pass

# ---------------------------------------------------------------------------
# Frame stepping
# ---------------------------------------------------------------------------

if _IN_KIT:
    def step_frame(count=1):
        """Advance Kit by *count* update frames."""
        import omni.kit.app  # type: ignore
        app = omni.kit.app.get_app()
        for _ in range(count):
            app.next_update_async()  # pragma: no cover – Kit runtime only
else:
    def step_frame(count=1):
        """No-op frame step for standalone mode."""
        pass
