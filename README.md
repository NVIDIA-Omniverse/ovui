# NVIDIA ovui

## 1. What is ovui?

**ovui** is a standalone Python UI toolkit for building native scene, viewport, and data applications, exposing the Omniverse UI framework through the familiar `omni.ui` (windows, layout, value models, widgets) and `omni.ui_scene` (SceneView, gestures, manipulators) Python APIs over a native C++ core. It loads and edits OpenUSD stages, presents rendered viewports from an external renderer such as ovrtx, runs headlessly for automation, and can be inspected by AI agents through a screenshot-first loop. Its defining trait is that it runs standalone — **no Omniverse Kit installation required**.

ovui is a disaggregated piece of the Omniverse platform: the `omni.ui` UI framework decoupled from the Kit extension system and shipped as an independently installable library, available as a peer to the other `ov` libraries (ovrtx, ovgraph, ovphysx, and more). It pairs the native runtime with **ovui-widgets** (production-shaped scene widgets) and **ovui-data-adapters** (a backend boundary for OpenUSD and custom data sources), keeping the UI layer cleanly separate from the data layer so teams can build tools against their own backends.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Build standalone Python UI apps** — windows, frames, stacks, fields, sliders, tree views, menus, markdown, images, styles, and frame-driven updates via `omni.ui`.
- **Author scene and viewport tools** — camera-aware drawing, gestures, manipulators, picking, selection outlines, and rendered-frame presentation via `omni.ui_scene`.
- **Reuse production USD workflows** — drop-in Stage Browser, Property Inspector, Layers panel, Content Browser, and Viewport widgets, plus shared `SelectionBus`, `UndoManager`, `Settings`, and recent-files services from ovui-widgets.
- **Stay backend-independent** — implement adapter contracts (`StageAdapter`, `PropertyAdapter`, `TransformAdapter`, `RendererAdapter`) to wire widgets to OpenUSD or your own data source; OpenUSD + ovrtx implementations are included.
- **Run headless and prove output remotely** — Vulkan/offscreen runs, programmatic screenshots, and frame-loop draining for CI and automation.
- **Drive it with AI coding agents** — the repo ships `AGENTS.md` and task-level skills (atomic UI APIs, widget composition, styling, screenshot-first inspection) so agents work from real patterns instead of inventing UI code.
- **Install in pieces** — a monorepo of independently installable distributions (`ovui`, `ovui-widgets-*`, `ovui-data-adapters-*`) that share one version, so you take only what you need.

**Who benefits:**

- **USD tool & application developers** — build scene browsers, property editors, and viewport tools in Python without standing up a full Kit stack.
- **Omniverse Kit developers** — reuse the same `omni.ui` / `omni.ui_scene` APIs you already know, now available standalone.
- **Headless automation & synthetic-data engineers** — run UI-driven workflows offscreen and capture screenshots/frames in CI or on remote GPUs.
- **AI coding agents (and the developers using them)** — scaffold, build, and inspect ovui apps through the shipped skills and screenshot-first inspector.

---

## 3. Documentation and reference links

- **Quickstart & install:** <https://github.com/NVIDIA-Omniverse/ovui#readme>
- **Native UI framework guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui/README.md>
- **USD Viewer app & widgets guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-widgets/README.md>
- **Data adapters guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-data-adapters/README.md>
- **Architecture overview:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/docs>
- **Source (GitHub):** <https://github.com/NVIDIA-Omniverse/ovui>
- **Package (PyPI):** <https://pypi.org/project/ovui/>
- **Releases (pre-built artifacts):** <https://github.com/NVIDIA-Omniverse/ovui/releases>
- **Skills for AI coding agents:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/skills>
- **Support:** [Issues](https://github.com/NVIDIA-Omniverse/ovui/issues)

---

## 4. System requirements

- **Python 3.12+**
- **Linux** (Ubuntu 22.04 / Debian) and **Windows** (Windows 11 / Windows Server 2022), x86_64
- **NVIDIA RTX-capable GPU + compatible driver** for rendered viewport output via ovrtx; a Vulkan-capable environment (including headless/Lavapipe) is supported for UI and offscreen paths
- **Build toolchain for source installs:** CMake with Visual Studio 2022 ("Desktop development with C++") on Windows, or `build-essential` on Linux; Vulkan headers + loader for the optional Vulkan backend
- **Current release:** ovui 0.2.0 (Early Access)
- The rendered viewport path depends on an external renderer (ovrtx), which is not provided by this repository. The OpenUSD data-adapter provider additionally requires OpenUSD (`pxr`) Python bindings — from its `standalone` extra or the environment — while the native OVStage provider uses the external native OVStage runtime and needs no OpenUSD bindings

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.
- Installs/downloads additional third-party open-source components — review their license terms (see `THIRD_PARTY_NOTICES.md`) before use.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release. The rendered viewport requires a separate ovrtx renderer install; the UI framework, widgets, and headless paths work without it.

---

*ovui · standalone distribution of Omniverse's `omni.ui` UI framework · Copyright (c) 2025 NVIDIA Corporation.*
