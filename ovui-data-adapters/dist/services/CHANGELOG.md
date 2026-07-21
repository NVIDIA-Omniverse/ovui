# Changelog

## 0.1.1 - 04-06-2026

Finalized the `ovui_data_adapters.services` migration boundary.

- Added frontend-neutral services for content backends, asset classification,
  undo/history, selection, settings, layer commands, transform commands,
  content navigation, file-operation policy, internal clipboard state, and
  reusable adapter/service testing fixtures.
- Preserved historical `ovui-widgets` import paths as compatibility shims or
  wrappers where ovui-widgets owns defaults and singleton policy.
- Kept viewport camera/render behavior, livestream/control-plane behavior,
  snap/manipulator policy, widgets, delegates, app runtime, status display,
  OS integration, transport integration, and renderer payloads out of the
  services package.
- Recorded the livestream/control-plane hold as an owner decision under the
  hard no-livestream-edit rule; `MessageDispatcher` was not moved.

## 0.1.0 - 04-06-2026

Initial package boundary.
