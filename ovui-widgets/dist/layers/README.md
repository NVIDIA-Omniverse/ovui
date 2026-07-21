# NVIDIA ovui-widgets-layers

## 1. What is ovui-widgets-layers?

**ovui-widgets-layers** is the Layers panel distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It presents a scene's layer and composition stack with full authoring controls, and it runs standalone: **no Omniverse Kit installation required**.

The panel reads layer and composition data through adapter objects from `ovui-data-adapters-common`, keeping it independent from the concrete scene backend. It is the Layers panel hosted by the ovui-widgets USD Viewer application and can equally back custom layer-management tools.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Inspect the composition stack** — layer order, authoring-target state, dirty/save state, and missing-file signals, with optional prim-spec rows.
- **Author the stack** — command-backed save, reload, insert, remove, move, merge, and flatten operations.
- **Control layer state** — mute and lock toggles and authoring-target switching.
- **Undo safely** — every operation is command-backed and integrates with the shared application undo manager.

**Who benefits:**

- **USD tool & application developers** — ship a production-shaped layer editor without rebuilding composition UI.
- **Teams with custom backends** — reuse the identical panel over any backend that fulfills the layer adapter contracts.

**Installation:**

```bash
python -m pip install ovui-widgets-layers
```

The panel is normally hosted by the `ovui-widgets-app` USD Viewer application, which wires it to the shared selection bus, undo manager, and the selected data-adapter provider; it can also be embedded directly in a custom ovui application.

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
- Declared dependencies: `ovui-widgets-common>=0.1.0`, `ovui-data-adapters-common>=0.1.0`
- A concrete data-adapter provider (for example `ovui-data-adapters-openusd`) supplies the layer data at runtime

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-layers · Layers panel widget for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
