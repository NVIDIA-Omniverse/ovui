# NVIDIA ovui-data-adapters-common

## 1. What is ovui-data-adapters-common?

**ovui-data-adapters-common** is the contract-and-registry distribution of ovui-data-adapters, the backend boundary of the **[ovui](https://pypi.org/project/ovui/)** scene-tooling family — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It defines the provider-neutral adapter interfaces that keep the UI layer (ovui and ovui-widgets) cleanly separate from the data layer, so teams can build tools against OpenUSD, native OVStage, mock data, or their own backends.

This package deliberately contains no concrete scene backend and requires no OpenUSD, ovrtx, ovstream, or GPU runtime. Concrete providers such as `ovui-data-adapters-openusd` and `ovui-data-adapters-ovstage` register themselves through its entry-point group and are selected at runtime through its registry.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Program against stable contracts** — stage, property, transform, renderer, selection, command, subscription, undo, camera-pose, and GPU-frame interfaces and value records in `ovui_data_adapters.common`.
- **Discover and select providers** — `AdapterFactories`, `AdapterRegistry`, `discover_adapter_modules`, and `select_adapter`, backed by the `ovui_data_adapters.adapters` entry-point group; applications also honor `OVUI_DATA_ADAPTER_PROVIDER` for explicit selection.
- **Convert livestream frames** — a provider-neutral, NumPy-based host-frame conversion helper shared by concrete renderer adapters (`ovstream` stays a lazily imported, externally supplied runtime used only when streaming is enabled).

**Who benefits:**

- **Backend implementers** — fulfill the adapter contracts once and every ovui-widgets panel works against your data source.
- **Application developers** — select and swap providers by name without coupling application code to a concrete backend.

**Installation:**

```bash
python -m pip install ovui-data-adapters-common
```

```python
from ovui_data_adapters.common import discover_adapter_modules, select_adapter

registry = discover_adapter_modules()
provider = select_adapter(registry, "openusd")  # returns an AdapterProvider
factories = provider.factories                  # the provider's AdapterFactories
```

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
- Pure Python; declared dependency: `numpy>=1.20` (used by the shipped livestream frame-conversion helper)
- No OpenUSD, renderer, or GPU runtime required by this package itself; those arrive with the concrete provider you select

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui-data-adapters-common · provider-neutral adapter contracts and registry for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
