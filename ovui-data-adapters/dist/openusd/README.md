# NVIDIA ovui-data-adapters-openusd

## 1. What is ovui-data-adapters-openusd?

**ovui-data-adapters-openusd** is the OpenUSD provider of ovui-data-adapters, the backend boundary of the **[ovui](https://pypi.org/project/ovui/)** scene-tooling family — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It implements the provider-neutral adapter contracts from `ovui-data-adapters-common` on top of the OpenUSD (`pxr`) API, giving ovui-widgets applications a complete standalone USD backend: **no Omniverse Kit installation required**.

The provider owns its own `Usd.Stage` opened from the scene file you pass it. The `pxr` runtime comes either from the optional `standalone` extra (which installs the supported `usd-core` wheel) or from an environment that already supplies a compatible `pxr`, so the same wheel serves both standalone and embedded deployments.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Drive every widget from USD** — stage hierarchy, property, transform, and layer/composition adapters behind the common contracts.
- **Author with undo** — undoable USD-mutation commands (visibility, delete, namespace edits, camera pose, prim creation) plus session-layer authoring support.
- **Present rendered viewports** — a renderer adapter with camera handling, picking, and selection highlighting; rendered output uses an external renderer such as ovrtx resolved from the active environment or `OVRTX_ROOT`.
- **Stream frames (optional)** — the `livestream` extra adds `ovstream` for livestream frame delivery.
- **Register automatically** — installing the wheel registers the `openusd` provider through the `ovui_data_adapters.adapters` entry-point group.

**Who benefits:**

- **USD tool & application developers** — a working, production-shaped USD backend for the ovui-widgets USD Viewer and custom apps.
- **Teams embedding into existing USD environments** — reuse the environment's own `pxr` runtime by installing the plain wheel without the `standalone` extra.

**Installation:**

```bash
python -m pip install "ovui-data-adapters-openusd[standalone]"
```

Install the plain wheel (`python -m pip install ovui-data-adapters-openusd`) when the environment already provides a compatible `pxr` runtime; do not combine the `standalone` extra with an environment-supplied `pxr`. Select the provider explicitly with `OVUI_DATA_ADAPTER_PROVIDER=openusd`, or let the common registry selection rules choose it.

---

## 3. Documentation and reference links

- **Quickstart & install:** <https://github.com/NVIDIA-Omniverse/ovui#readme>
- **Data adapters guide:** <https://github.com/NVIDIA-Omniverse/ovui/blob/main/ovui-data-adapters/README.md>
- **Architecture overview:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/docs>
- **Core toolkit (PyPI):** <https://pypi.org/project/ovui/>
- **Source (GitHub):** <https://github.com/NVIDIA-Omniverse/ovui>
- **Support:** [Issues](https://github.com/NVIDIA-Omniverse/ovui/issues)

---

## 4. System requirements

- **Python 3.10+**
- Declared dependencies: `ovui-data-adapters-common>=0.1.0`, `numpy>=1.20`
- Optional extras: `standalone` installs `usd-core==25.11`; `livestream` installs `ovstream`
- A `pxr` runtime is required at run time — from the `standalone` extra or supplied by the environment
- **NVIDIA RTX-capable GPU + compatible driver** for rendered viewport output via ovrtx; ovrtx is external to this package (resolved from the active environment or `OVRTX_ROOT`), and non-rendered adapter paths work without it

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.
- The `standalone` extra installs the third-party open-source `usd-core` package — review its license terms before use.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-data-adapters-openusd · standalone OpenUSD backend for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
