# NVIDIA ovui-data-adapters-services

## 1. What is ovui-data-adapters-services?

**ovui-data-adapters-services** is the behavior-services distribution of ovui-data-adapters, the backend boundary of the **[ovui](https://pypi.org/project/ovui/)** scene-tooling family — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It packages complete, reusable service subsystems built above the provider-neutral adapter contracts from `ovui-data-adapters-common`.

The production services are deliberately frontend-neutral and provider-neutral: they hold no widget code and no OpenUSD- or OVStage-specific logic, so the same selection, settings, transform, undo, content, and layers behavior can back different frontends and different data providers. One scoped exception lives in the optional testing helpers: the mock renderer can lazily import `pxr.Usd` to open USD paths when a test supplies one; the non-testing service subsystems remain provider-neutral.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Reuse selection behavior** — selection services shared across frontends.
- **Persist and read settings** — settings services above the adapter contracts.
- **Transform consistently** — shared transform helpers.
- **Undo uniformly** — undo services decoupled from any concrete backend.
- **Drive content and layers flows** — complete content and layers behavior subsystems.
- **Test service consumers** — shipped testing support (mock backends and a mock renderer) for code built on these services; the mock renderer may import `pxr.Usd` when handed a USD path.

**Who benefits:**

- **Application developers** — reuse proven behavior subsystems instead of re-implementing them per frontend.
- **Backend implementers** — pair a concrete provider with ready-made behavior above the raw adapter contracts.

**Installation:**

```bash
python -m pip install ovui-data-adapters-services
```

Service subsystems are imported from `ovui_data_adapters.services` by applications and providers that want shared behavior above the adapter contracts.

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
- Pure Python; declared dependency: `ovui-data-adapters-common>=0.1.0`
- No OpenUSD, renderer, or GPU runtime required

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-data-adapters-services · frontend-neutral behavior services for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
