# NVIDIA ovui-data-adapters-ovstage

## 1. What is ovui-data-adapters-ovstage?

**ovui-data-adapters-ovstage** is the native OVStage provider of ovui-data-adapters, the backend boundary of the **[ovui](https://pypi.org/project/ovui/)** scene-tooling family — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. It connects ovui-widgets applications directly to the externally supplied native OVStage scene runtime and attaches the ovrtx renderer in BORROW mode for rendering and picking.

The provider is natively isolated: it has **no OpenUSD dependency**, does not import `pxr` or the `ovui-data-adapters-openusd` package, and does not open or mirror a backing `Usd.Stage`. Structural and runtime isolation tests enforce that boundary. Compatibility with the native runtime is verified at startup by a runtime preflight that names the exact missing module or API when a requirement fails.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Drive the widgets from native OVStage** — stage, property, transform, selection, and renderer adapters behind the common contracts, registered as the `ovstage` provider. Prim creation and deletion, property and transform authoring, rendering, picking, and undo/redo are supported natively.
- **Manage native scene lifetime** — a provider-owned session (`OvstageProviderSession`) handles scene open/replace/cleanup, and authoring adapters integrate with the application's undo manager.
- **Know the capability boundary** — durable workflows that need USD composition or default-value resolution are deliberately unavailable and fail closed rather than falling back: new-document creation, save/export, layer-stack and composition operations (edit targets, save/save-as, sublayer editing, mute/lock, prim specs), and clearing authored property values. Use the separate `ovui-data-adapters-openusd` provider for those workflows.
- **Render and pick through ovrtx** — the renderer adapter attaches ovrtx in BORROW mode; the provider does not fall back to a substitute renderer.
- **Control physics (optional)** — guarded Physics menu items (Enable PhysX, Play Simulation) register whenever the ovui-widgets menu subsystem is importable; the session always exposes `physics_controls`, the optional `ovphysx` runtime is imported lazily when physics is enabled, and a failed load or enable raises a structured error that is reported and re-raised.

**Who benefits:**

- **Teams deploying the native OVStage runtime** — run the ovui-widgets USD Viewer directly on OVStage-owned scenes without an OpenUSD layer in between.
- **Application developers needing strict backend isolation** — a provider whose no-`pxr` contract is enforced by tests, not convention.

**Installation:**

```bash
python -m pip install ovui-data-adapters-ovstage
```

Select the provider explicitly with `OVUI_DATA_ADAPTER_PROVIDER=ovstage` when running the ovui-widgets application. The native **ovstage** and **ovrtx** runtimes must be importable — from the active Python environment first, or resolved from `OVSTAGE_ROOT` / `OVRTX_ROOT` installs; they are supplied outside of pip and are not installed by this package.

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
- Declared dependency: `ovui-data-adapters-common>=0.1.0` — deliberately no `ovui-data-adapters-openusd`, `usd-core`, or `pxr` dependency
- External native runtimes, supplied outside of pip: **ovstage** (required; exposes a callable `ovstage.Stage`), **ovrtx** (required for rendering and picking), **ovphysx** (optional; loaded lazily for physics)
- Required ovrtx renderer APIs, verified by the startup preflight: a callable `ovrtx.RendererConfig` and a callable `ovrtx.Renderer` exposing `ovrtx.Renderer.attach_ovstage`, `ovrtx.Renderer.step`, and `ovrtx.Renderer.detach_ovstage`
- BORROW attachment is the supported mode: the current default-BORROW ovrtx API needs no `AttachMode` type; when an ovrtx build exposes `ovrtx.AttachMode.BORROW`, the provider passes that explicit mode to `ovrtx.RendererConfig` instead
- The renderer requirement is fail-closed: the provider has no read-only compatibility mode and never substitutes a fallback renderer — setting `OVUI_WIDGETS_REQUIRE_OVRTX=0` relaxes nothing when the `ovstage` provider is selected
- **NVIDIA RTX-capable GPU + compatible driver** for ovrtx rendering
- Installing the wheel does not prove native-runtime compatibility; the provider's startup preflight verifies the required modules and APIs and fails with a structured error naming what is missing

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release. OVStage, ovrtx, and ovphysx are external runtime components with their own availability and licensing.

---

*ovui-data-adapters-ovstage · native OVStage backend for the ovui scene-tooling family · Copyright (c) 2025 NVIDIA Corporation.*
