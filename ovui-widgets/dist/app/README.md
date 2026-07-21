# NVIDIA ovui-widgets-app

## 1. What is ovui-widgets-app?

**ovui-widgets-app** is the runnable USD Viewer application of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. Installing it gives you a complete desktop (and headless) scene application: it owns startup, menu and status chrome, settings, recent files, theme application, selection, undo, frame timing, and file-open routing, and it wires together the Stage Browser, Layers panel, Content Browser, Property Inspector, and Viewport. It runs standalone: **no Omniverse Kit installation required**.

The application selects its scene backend at runtime through the `ovui-data-adapters` registry rather than hard-depending on a specific data source, and it loads optional UI components from the `ovui_widgets.components` entry-point group, so installed component wheels appear in the app automatically.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Run the USD Viewer** — `ovui-widgets path/to/scene.usda` opens the full application with browser, layers, property, content, and viewport panels (`ovgear` remains as a compatibility alias).
- **Run headless** — `ovui-widgets-headless` drives the same application offscreen for automation, CI, and remote GPUs.
- **Choose the scene backend** — set `OVUI_DATA_ADAPTER_PROVIDER` (for example `openusd` or `ovstage`) to select any installed data-adapter provider.
- **Extend with components** — packages that register `ovui_widgets.components` entry points are discovered and loaded at startup.
- **Drive it with AI agents** — `ovui-widgets-skill` exposes the packaged widget/styling/application skills to AI coding agents.

**Who benefits:**

- **USD tool & application developers** — a reference scene application to use directly or study when composing the widgets yourself.
- **Headless automation & synthetic-data engineers** — a ready-made offscreen application for scripted scene workflows.

**Installation:**

```bash
python -m pip install ovui-widgets-app
ovui-widgets path/to/scene.usda
```

The rendered viewport uses an external renderer (ovrtx) by default; ovrtx is not installed by this package. Setting `OVUI_WIDGETS_REQUIRE_OVRTX=0` opts into a fallback renderer **only when the selected provider supports one** — the OpenUSD provider does; the native OVStage provider fails closed and always requires ovrtx in BORROW mode. The selected provider package must be installed so it is discoverable through the `ovui_data_adapters.adapters` entry-point group.

---

## 3. Documentation and reference links

- **Quickstart & install:** <https://github.com/NVIDIA-Omniverse/ovui#readme>
- **Architecture overview:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/docs>
- **Data adapters guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-data-adapters/README.md>
- **Core toolkit (PyPI):** <https://pypi.org/project/ovui/>
- **Source (GitHub):** <https://github.com/NVIDIA-Omniverse/ovui>
- **Skills for AI coding agents:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/skills>
- **Support:** [Issues](https://github.com/NVIDIA-Omniverse/ovui/issues)

---

## 4. System requirements

- **Python 3.10+** declared by the wheel; the `ovui` runtime underneath the application requires **Python 3.12+**
- **Linux** (Ubuntu 22.04 / Debian) and **Windows** (Windows 11 / Windows Server 2022), x86_64 — the platforms supported by the ovui runtime
- Declared dependencies: `ovui>=0.1.0`, `ovui-widgets-common[testing]>=0.1.0`, `ovui-widgets-stage>=0.1.0`, `ovui-widgets-layers>=0.1.0`, `ovui-widgets-content>=0.1.0`, `ovui-widgets-property>=0.1.0`, `ovui-widgets-viewport>=0.1.0`, `ovui-data-adapters-common>=0.1.0`
- **NVIDIA RTX-capable GPU + compatible driver** for rendered viewport output via ovrtx; a Vulkan-capable environment (including headless/Lavapipe) is supported for UI and offscreen paths
- A concrete data-adapter provider wheel (for example `ovui-data-adapters-openusd`) supplies the scene data

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release. The rendered viewport requires a separate ovrtx renderer install; the UI framework, widgets, and headless paths work without it.

---

*ovui-widgets-app · USD Viewer application for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
