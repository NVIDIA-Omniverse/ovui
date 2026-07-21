# ovui Tests

This directory contains the Python and native-C++ test suites for ovui along
with the golden-image baselines they compare against.

The suites run in three configurations on CI ("legs B1, B2, B3"; see below)
and locally on a developer workstation. B1 and B3 run the Python suite via
`pytest tests/` — their *behavior* is selected by environment variables and
pytest markers. B2 runs the native C++ tests via CTest and does not invoke
pytest at all.

---

## Layout

```
tests/
├── conftest.py                  # marker skip logic for requires_gl / requires_glfw / requires_cuda
├── test_base.py                 # OmniUiTest base class + golden compare wrapper
├── compare_utils.py             # Pillow-based image comparison (Kit-compatible)
├── generate_golden.py           # helper that flips OMNI_UI_GENERATE_GOLDEN=1
├── run_tests.py                 # legacy direct runner (use pytest instead)
├── test_*.py                    # pytest test modules
├── cpp/                         # native C++ test sources
│   ├── test_markdown_model.cpp
│   └── test_markdown_fuzz.cpp
├── markdown_fuzz_corpus/        # input corpus for the markdown fuzz harness
├── scene/                       # scene-graph fixtures consumed by Python tests
├── golden/                      # golden reference images (do not edit by hand)
│   ├── vulkan/                  # baselines captured under headless Vulkan
│   ├── egl/                     # baselines captured under headless EGL
│   └── opengl/                  # baselines captured under windowed OpenGL
└── captured/                    # latest test captures + diffs (gitignored)
```

---

## Running tests locally

The Python suites need the ovui extension built and importable. The simplest
way is the same `pip install -e .` invocation CI uses.

### Headless Vulkan (matches CI leg B1)

```bash
source ~/dev/ovui/ovui-widgets/_venv312/bin/activate
export OMNIUI_HEADLESS=1
export OMNIUI_BACKEND=vulkan
pytest tests/ --forked -m "not requires_gl and not requires_cuda" -q
```

`--forked` runs each test in its own subprocess so a crash in one test cannot
take the whole run down. `-m "not requires_gl"` skips tests that need a real
OpenGL context (Vulkan-only headless cannot satisfy them).

### Headless EGL (matches CI leg B3)

```bash
export OMNIUI_HEADLESS=1
export OMNIUI_HEADLESS_GL=1
export OMNIUI_EGL_FORCE_SURFACELESS=1
export MESA_GL_VERSION_OVERRIDE=3.3
pytest tests/ --forked -m "not requires_cuda" -q
```

EGL provides a real GL context with no display server, so `requires_gl`
tests do run on this leg. `requires_cuda` is still skipped — there's no GPU.

### Native C++ tests (CTest)

After `cmake --build` finishes, the C++ tests run via CTest:

```bash
ctest --test-dir build/pip --output-on-failure
```

Currently registered:

- `markdown_model_tests` — unit tests for the MarkdownWidget data model.
- `markdown_fuzz_tests`  — corpus-driven fuzz harness for the markdown
  parser. Reads `tests/markdown_fuzz_corpus/`.
- `headless_test`        — smoke test that brings up the standalone
  compositor and renders one frame.

---

## Environment variables

| Variable                          | Effect                                                                                       |
| --------------------------------- | -------------------------------------------------------------------------------------------- |
| `OMNIUI_HEADLESS`                 | `1`/`true` — run without a window. Required for B1 and B3 (B2 is native C++ and does not use it). |
| `OMNIUI_HEADLESS_GL`              | `1` — when combined with `OMNIUI_HEADLESS=1`, picks the EGL surfaceless GL backend.          |
| `OMNIUI_BACKEND`                  | `vulkan`/`vk` — explicitly request the Vulkan compositor.                                    |
| `OMNIUI_LAVAPIPE`                 | `1` — pin the Vulkan ICD to Mesa Lavapipe (CPU rasterizer, used in CI for reproducibility).  |
| `OMNIUI_EGL_FORCE_SURFACELESS`    | `1` — force `EGL_MESA_platform_surfaceless`, no display server.                              |
| `MESA_GL_VERSION_OVERRIDE`        | `3.3` — what Mesa advertises to the application.                                             |
| `OMNI_UI_GOLDEN_STRICT`           | `1` — fail on missing goldens instead of silently generating them. CI sets this on B1 and B3 so PRs cannot silently create or drift baselines. |
| `OMNI_UI_GENERATE_GOLDEN`         | `1` — overwrite the golden with the current capture. Use when intentionally rebaselining.    |
| `OMNI_UI_SKIP_GOLDEN_TESTS`       | `1` — render normally but skip the image comparison. This is for temporary local diagnostics only; PR CI should not set it.       |
| `OMNI_UI_GOLDEN_DIR`              | Override the golden root. Defaults to `tests/golden/`.                                       |

The `_backend_tag()` helper in `tests/test_base.py` derives the backend
subdirectory (`vulkan`, `egl`, or `opengl`) from these variables. On AArch64,
the test helper also looks for an approved per-image override under an
`aarch64/` child directory. See `tests/test_backend_tag.py` for the canonical
backend mapping.

---

## Pytest markers

| Marker           | Meaning                                                                                |
| ---------------- | -------------------------------------------------------------------------------------- |
| `requires_gl`    | Test needs a real OpenGL context. Skipped on pure-Vulkan headless legs.                |
| `requires_glfw`  | Test needs the GLFW windowing platform (streaming pipeline). Skipped under any `OMNIUI_HEADLESS=1` run (Vulkan or EGL surfaceless). |
| `requires_cuda`  | Test needs a CUDA-capable GPU. Skipped on every CI leg (no GPU).                       |

Markers are registered in `pyproject.toml` and enforced in
`tests/conftest.py`. To run only the GL tests locally on a real desktop:

```bash
pytest tests/ -m "requires_gl"
```

---

## Golden-image workflow

### Reading
`finalize_test()` in `OmniUiTest` saves a screenshot to
`tests/captured/<ImageName>.png` and compares it to
`tests/golden/<backend_tag>/<ImageName>.png`. On AArch64 it first checks
`tests/golden/<backend_tag>/aarch64/<ImageName>.png`, allowing only images with
proven architecture-specific rasterization to override the shared baseline. A
legacy untagged path (`tests/golden/<ImageName>.png`) is read as a transitional
fallback when no tagged baseline exists yet. Writes target the architecture
override on AArch64 and the shared backend path on other architectures; they
never target the legacy path.

The comparison metric is mean per-channel absolute difference (range
`[0, 255]`). On mismatch the failure message has the format

```
Golden image mismatch for <test>: error=<value> >= threshold=<value> (metric=mean_error)
```

CI parsers depend on that exact format — see `tests/test_base.py:392`.

### Regenerating

After an *intentional* rendering change, regenerate the affected backend's
baselines under that exact backend and architecture environment. An AArch64
run writes to the `aarch64/` override directory and leaves shared x86_64
baselines untouched:

```bash
# from a workstation with the right backend env exported
OMNI_UI_GENERATE_GOLDEN=1 pytest tests/test_label.py::TestLabel::test_color
```

Only the listed tests get rewritten. `OMNI_UI_GENERATE_GOLDEN=1` overrides
strict mode but does **not** loop over backends — you must re-run the
command on each backend whose goldens you want to regenerate.

The `.github/workflows/generate-goldens.yml` workflow does this on a CI
runner for the headless backends (Vulkan-Lavapipe and EGL-surfaceless),
then commits and pushes the regenerated baselines directly to the
dispatched branch.

### Strict vs lax mode

| Mode    | `OMNI_UI_GOLDEN_STRICT` | Missing golden behavior        |
| ------- | ----------------------- | ------------------------------ |
| Strict  | `1`                     | Test fails                     |
| Lax     | unset                   | First run silently generates   |

Strict mode prevents goldens from being created accidentally during a
random local run and committed without review.

B1 and B3 run with `OMNI_UI_GOLDEN_STRICT=1`. Missing baselines fail the
run, and existing baselines are compared on every PR. Regenerate backend
baselines with `generate-goldens.yml` after intentional visual changes,
then review and commit the resulting PNG diff like any other source
change.

---

## CI legs

The CI matrix has three test legs plus two helper workflows. Each leg
runs on stock `ubuntu-22.04` with no GPU. B1 and B3 run pytest; B2 runs
native C++ tests via ctest because mixing ASan-built `.so`s into a
non-instrumented CPython aborts at import time on hosted runners.

| Leg | Workflow                            | Runner / framework            | Backend          | Goldens     | Markers excluded            |
| --- | ----------------------------------- | ----------------------------- | ---------------- | ----------- | --------------------------- |
| B1  | `.github/workflows/test-b1-vulkan.yml`      | pytest                        | Vulkan + Lavapipe        | strict compare against `tests/golden/vulkan/` | `requires_gl`, `requires_cuda` (auto: `requires_glfw`) |
| B2  | `.github/workflows/test-b2-vulkan-asan.yml` | ctest (native C++)            | none (CPU)               | n/a (no pytest) | n/a (runs `markdown_model_tests`, `markdown_fuzz_tests` only)  |
| B3  | `.github/workflows/test-b3-egl.yml`         | pytest                        | EGL surfaceless          | strict compare against `tests/golden/egl/` | `requires_cuda` (auto: `requires_glfw`) |

Helper workflows:

- `generate-goldens.yml` — manual `workflow_dispatch` to regenerate the
  Vulkan or EGL baselines on a clean runner and commit/push them
  directly back to the dispatched branch.
- `headless-egl.yml`, `headless-lavapipe.yml` — the older legs from before
  the issue-#36 split; kept for now to also exercise the native C++ tests.

B2 runs the native C++ tests (`markdown_model_tests`, `markdown_fuzz_tests`)
under AddressSanitizer via CTest. No renderer or compositor is involved, so
golden comparison does not apply. B1 owns golden enforcement.

B3 owns EGL-surfaceless golden enforcement.
