# NVIDIA ovui-widgets-property

## 1. What is ovui-widgets-property?

**ovui-widgets-property** is the Property Inspector distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It builds type-appropriate editors for the attributes and metadata of whatever is selected, and it runs standalone: **no Omniverse Kit installation required**.

The inspector follows application selection and reads through the `PropertyAdapter` contract from `ovui-data-adapters-common`, so it works identically against OpenUSD, mock, or project-specific property data. It is the Property Inspector hosted by the ovui-widgets USD Viewer application.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Edit typed properties** — type-dispatched editors for scalar values, vectors, colors, tokens, relationships, assets, matrices, and arrays, plus specialized property sections.
- **Handle multi-selection** — ambiguity presentation when selected objects disagree, with well-defined reset behavior.
- **Author safely** — edit begin/set/end calls that integrate with the shared application undo manager.
- **Extend the surface** — add new editor types and sections through the property scheme registry.

**Who benefits:**

- **USD tool & application developers** — ship a production-shaped property editor without hand-building per-type widgets.
- **Teams with custom data models** — expose project-specific attributes through `PropertyAdapter` and reuse the identical inspector.

**Installation:**

```bash
python -m pip install ovui-widgets-property
```

The inspector is normally hosted by the `ovui-widgets-app` USD Viewer application, which wires it to app selection and the selected data-adapter provider; it can also be embedded directly in a custom ovui application.

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
- A concrete data-adapter provider (for example `ovui-data-adapters-openusd`) supplies the property data at runtime

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-property · Property Inspector widget for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
