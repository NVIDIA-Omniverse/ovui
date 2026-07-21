# NVIDIA ovui-widgets-content

## 1. What is ovui-widgets-content?

**ovui-widgets-content** is the Content Browser distribution of ovui-widgets, the production-shaped scene-widget family built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It provides the file-navigation surface used to find and open scene content, and it runs standalone: **no Omniverse Kit installation required**.

The browser is backend-oriented: a local filesystem backend ships with the package, and storage behavior can be replaced behind the same visible widget surface. It is the Content Browser hosted by the ovui-widgets USD Viewer application and supplies that app's explicit open-file handoff.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Navigate content** — file browsing with bookmarks, recent files, and search.
- **Present flexibly** — grid and list presentation of folders and files.
- **Manage files** — rename and delete flows plus import/export helpers.
- **Pick files from dialogs** — reusable file picker dialogs for open/save flows.
- **Hand off explicitly** — a deliberate open-file handoff so the hosting application controls what opening a file means.

**Who benefits:**

- **USD tool & application developers** — add production-shaped content browsing and file pickers to ovui applications.
- **Teams with custom storage** — swap the backend (asset services, databases, virtual filesystems) while keeping the identical browsing UI.

**Installation:**

```bash
python -m pip install ovui-widgets-content
```

The browser is normally hosted by the `ovui-widgets-app` USD Viewer application, which routes chosen files into its stage-open flow; it can also be embedded directly in a custom ovui application.

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
- Declared dependency: `ovui-widgets-common>=0.1.0`

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-widgets-content · Content Browser widget for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
