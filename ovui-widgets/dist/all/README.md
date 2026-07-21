# NVIDIA ovui-widgets-all

## 1. What is ovui-widgets-all?

**ovui-widgets-all** is the aggregate meta-package for ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. One install brings in the complete scene-tooling stack — the USD Viewer application, all widget panels, shared services, and the data-adapter contracts plus the OpenUSD provider with a supported standalone `usd-core` runtime. It runs standalone: **no Omniverse Kit installation required**.

The package contains no code of its own; it exists so a fresh environment can go from `pip install` to a working scene application in one step, while the underlying distributions remain independently installable for teams that want only part of the stack.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Install the complete stack in one step** — the USD Viewer application (`ovui-widgets-app`) with the Stage Browser, Layers panel, Content Browser, Property Inspector, and Viewport widgets.
- **Get a working USD backend immediately** — includes `ovui-data-adapters-openusd` with its `standalone` extra, so the supported `usd-core` runtime is installed too.
- **Run the viewer** — `ovui-widgets path/to/scene.usda` opens the application, or `ovui-widgets-headless` runs offscreen. The default rendered viewport requires the external ovrtx renderer, which is **not installed by this package**; with the included OpenUSD provider you can instead opt into its fallback renderer by setting `OVUI_WIDGETS_REQUIRE_OVRTX=0`.

**Who benefits:**

- **New users and evaluators** — the fastest path from an empty environment to a running standalone USD viewer.
- **Full-stack deployments** — projects that want the entire scene-tooling surface pinned as one coherent set.

**Installation:**

```bash
python -m pip install ovui-widgets-all
OVUI_WIDGETS_REQUIRE_OVRTX=0 ovui-widgets path/to/scene.usda
```

The one-line quick start above uses the OpenUSD provider's fallback renderer. For the default rendered path, supply the external ovrtx renderer and omit the variable. Kit and custom-USD environments that must retain their own matching `pxr` runtime should **not** install this aggregate (it pulls in the standalone `usd-core` wheel); install the component packages and plain `ovui-data-adapters-openusd` instead.

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

- **Python 3.10+** declared by the wheel; the `ovui` runtime underneath the stack requires **Python 3.12+**
- **Linux** (Ubuntu 22.04 / Debian) and **Windows** (Windows 11 / Windows Server 2022), x86_64 — the platforms supported by the ovui runtime
- Declared dependencies: `ovui-widgets-common`, `ovui-widgets-app`, `ovui-widgets-stage`, `ovui-widgets-layers`, `ovui-widgets-content`, `ovui-widgets-property`, `ovui-widgets-viewport` (each `>=0.1.0`), `ovui-data-adapters-common>=0.1.0`, and `ovui-data-adapters-openusd[standalone]>=0.2.0`
- **NVIDIA RTX-capable GPU + compatible driver** for rendered viewport output via ovrtx; the renderer is not provided by these packages, and the UI, widgets, and headless paths work without it

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.
- Installs additional third-party open-source components (for example `usd-core`) — review their license terms before use.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-all · one-step install of the complete ovui scene-tooling stack · Copyright (c) 2025 NVIDIA Corporation.*
