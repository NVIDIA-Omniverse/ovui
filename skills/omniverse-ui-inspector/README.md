# NVIDIA ovui Inspector

## 1. What is the ovui Inspector?

The **ovui Inspector** is the screenshot-first inspection server for applications built on **[ovui](https://pypi.org/project/ovui/)** — NVIDIA's standalone distribution of the Omniverse `omni.ui` UI framework. The Inspector skill and its `ovuiinspect` module are embedded in the `ovui` application wheel; there is no standalone Inspector distribution. It lets an AI coding agent, test harness, or developer drive a running ovui application from outside the process: the application imports the embedded `ovuiinspect` module, attaches itself, and drains queued mouse, keyboard, wait, and screenshot commands on the ovui frame loop.

The design is deliberately screenshot-first: automation captures a screenshot, issues one user-like action at a time, and verifies the result from the next screenshot, without reaching into application internals. This is the server side of the `ovui-inspect` workflow shipped with ovui's skills for AI coding agents.

> *ovui is pre-release software and is not enterprise-supported.*
---

## 2. What functionalities are available, and who are the target users?

**What you can do with it:**

- **Make a running app inspectable** — a local FastAPI server plus a frame-loop command queue executed inside the application process.
- **Capture proof** — programmatic screenshots of the live application.
- **Act like a user** — mouse, keyboard, and wait commands, issued one at a time so each step can be verified from the next screenshot.
- **Opt into state endpoints for QA** — setting `OVUIINSPECT_ENABLE_STATE=1` exposes state-bearing endpoints; using that geometry to choose targets is state-guided automation, not screenshot-first proof.

**Who benefits:**

- **AI coding agents (and the developers using them)** — scaffold, run, and visually verify ovui and ovui-widgets applications through the shipped skills.
- **QA and automation engineers** — drive UI-level workflows and capture evidence in CI or on remote GPUs.

**Installation:**

```bash
python -m pip install ovui
ovui-skill install omniverse-ui-inspector --target ./skills
python -m pip install -r ./skills/omniverse-ui-inspector/requirements.txt
```

```python
import ovuiinspect

ovuiinspect.attach_application(app)  # make the running ovui app inspectable
```

Add `./skills/omniverse-ui-inspector` to `PYTHONPATH` when running from the installed skill directory. Application wheelhouses embed this same skill in `ovui`; CI/CD does not build, publish, count, install, or describe a separate Inspector wheel.

---

## 3. Documentation and reference links

- **Quickstart & install:** <https://github.com/NVIDIA-Omniverse/ovui#readme>
- **Skills for AI coding agents:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/skills>
- **Architecture overview:** <https://github.com/NVIDIA-Omniverse/ovui/tree/main/docs>
- **Core toolkit (PyPI):** <https://pypi.org/project/ovui/>
- **Source (GitHub):** <https://github.com/NVIDIA-Omniverse/ovui>
- **Support:** [Issues](https://github.com/NVIDIA-Omniverse/ovui/issues)

---

## 4. System requirements

- **Python 3.10+**
- Declared dependencies: `fastapi>=0.100.0`, `python-multipart>=0.0.7`, `uvicorn[standard]>=0.23.0`, `httpx>=0.25.0`
- An ovui-based application to inspect (the application environment provides ovui; see its requirements for platform and GPU support)
- The server binds to `127.0.0.1` by default for same-machine automation (`OVUIINSPECT_HOST` / `OVUIINSPECT_PORT` configurable)

---

## 5. Licensing

- Governed by the **[NVIDIA Software License Agreement](https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-software-license-agreement/)** and the **[Product Specific Terms for NVIDIA Omniverse](https://www.nvidia.com/en-us/agreements/enterprise-software/product-specific-terms-for-omniverse/)**.
- Source-available for inspection; pre-release versions are provided **AS-IS** and are **not currently open to external contributions**.
- Depends on third-party open-source components (FastAPI, uvicorn, httpx, python-multipart) — review their license terms before use.

> **Note:** ovui is pre-release Early Access software and is not enterprise-supported. APIs may change before the 1.0 release.

---

*ovui Inspector · screenshot-first inspection server for ovui applications · Copyright (c) 2025 NVIDIA Corporation.*
