# NVIDIA ovui-widgets-stage

## 1. What is ovui-widgets-stage?

**ovui-widgets-stage** is the Stage Browser distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It turns scene hierarchy data into a searchable, expandable tree view for USD-style scenes, and it runs standalone: **no Omniverse Kit installation required**.

The widget reads hierarchy data exclusively through the `StageAdapter` contract from `ovui-data-adapters-common`, keeping the UI layer cleanly separate from the data layer. The same browser UI therefore works against OpenUSD, mock, or project-specific backends, and it is the Stage Browser hosted by the ovui-widgets USD Viewer application.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Browse large scene hierarchies** — an expandable tree with type labels, badges, and lazy child loading.
- **Search and filter** — narrow deep hierarchies through the built-in filter pipeline.
- **Control visibility** — per-item visibility toggles synchronized with the scene backend.
- **Rename and reorganize** — rename support and drag/drop reparent feedback.
- **Stay selection-synchronized** — tree selection follows and drives the shared application selection.

**Who benefits:**

- **USD tool & application developers** — embed a production-shaped scene browser without writing tree UI from scratch.
- **Teams with custom backends** — implement `StageAdapter` once and reuse the identical browser surface.

**Installation:**

```bash
python -m pip install ovui-widgets-stage
```

The browser is normally hosted by the `ovui-widgets-app` USD Viewer application, which wires it to the shared selection bus, undo manager, and the selected data-adapter provider; it can also be embedded directly in a custom ovui application.

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
- A concrete data-adapter provider (for example `ovui-data-adapters-openusd`) supplies the scene data at runtime

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-stage · Stage Browser widget for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
