# NVIDIA ovui-widgets-common

## 1. What is ovui-widgets-common?

**ovui-widgets-common** is the shared-infrastructure distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. Every other `ovui-widgets-*` wheel depends on this package for shared state and common services instead of importing sibling widget packages directly, and it runs standalone: **no Omniverse Kit installation required**.

It defines the `WidgetServices` protocol and the service layer — settings, selection, undo, scheduling, error reporting — that lets the Stage Browser, Layers panel, Content Browser, Property Inspector, and Viewport cooperate inside one application while remaining independently installable.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Share application services** — the `WidgetServices` protocol plus settings, selection, undo, scheduled callbacks, and error reporting used by all widget packages.
- **Build consistent windows** — managed windows, dialogs, and snap support.
- **Style once** — icon resources and style helpers resolved through `importlib.resources.files("ovui_widgets.common")`.
- **Test without a backend** — mock adapters and testing helpers (the mock renderer requires NumPy, provided by the `testing` extra).

**Who benefits:**

- **USD tool & application developers** — reuse the widget family's service layer when composing widgets into custom applications.
- **Widget authors** — build new panels on the same shared types and services the shipped widgets use.

**Installation:**

```bash
python -m pip install ovui-widgets-common
```

Add the `testing` extra (`python -m pip install "ovui-widgets-common[testing]"`) when using the shipped mock renderer and testing helpers. Most users install this package indirectly as a dependency of `ovui-widgets-app` or one of the widget distributions.

---

## 3. Documentation and reference links

- **Quickstart & install:** <https://github.com/NVIDIA-Omniverse/ovui#readme>
- **Architecture overview:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/docs>
- **Data adapters guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-data-adapters/README.md>
- **Core toolkit (PyPI):** <https://pypi.org/project/ovui/>
- **Source (GitHub):** <https://github.com/NVIDIA-Omniverse/ovui>
- **Support:** [Issues](https://github.com/NVIDIA-Omniverse/ovui/issues)

---

## 4. System requirements

- **Python 3.10+** declared by the wheel; the `ovui` runtime underneath the widget family requires **Python 3.12+**
- **Linux** (Ubuntu 22.04 / Debian) and **Windows** (Windows 11 / Windows Server 2022), x86_64 — the platforms supported by the ovui runtime
- Declared dependencies: `ovui>=0.1.0`, `ovui-data-adapters-common>=0.1.0`
- Optional `testing` extra: `numpy` (required only by the shipped mock renderer and testing helpers)

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-common · shared services and types for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
