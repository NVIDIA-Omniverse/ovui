# NVIDIA ovui-widgets-viewport

## 1. What is ovui-widgets-viewport?

**ovui-widgets-viewport** is the Viewport distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It combines rendered-frame presentation, camera controls, and interactive manipulation into the viewport surface used by the USD Viewer application, and it runs standalone: **no Omniverse Kit installation required**.

The viewport receives renderer, stage, transform, selection, snapping, and undo objects from the hosting application, so rendering and scene data can be swapped behind the same visible interaction model. Rendered frames come from an external renderer such as ovrtx through the `RendererAdapter` contract; the renderer itself is not part of this package.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Present rendered frames** — display output from an adapter-connected renderer with HUD state.
- **Fly the camera** — orbit, pan, zoom, and keyboard flight through the built-in camera controller.
- **Manipulate the scene** — transform manipulators, picking, and selection outline feedback built on `omni.ui_scene`.
- **Overlay scene UI** — camera-aware overlays drawn in scene space above the rendered image.
- **Snap and undo** — snapping support and undo integration provided by the hosting application's services.

**Who benefits:**

- **USD tool & application developers** — embed a production-shaped 3D viewport with manipulation in Python.
- **Teams with their own renderer or data source** — implement the renderer/stage adapter contracts and keep the identical interaction model.

**Installation:**

```bash
python -m pip install ovui-widgets-viewport
```

The viewport is normally hosted by the `ovui-widgets-app` USD Viewer application; it can also be embedded directly in a custom ovui application that supplies the adapter objects.

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
- Declared dependencies: `ovui-widgets-common>=0.1.0`, `ovui-data-adapters-common>=0.1.0`, `numpy>=1.20`
- **NVIDIA RTX-capable GPU + compatible driver** for rendered viewport output via an external renderer such as ovrtx; the renderer is not provided by this package, and UI-only paths work without it

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-viewport · Viewport widget for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
