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
│   ├── test_markdown_fuzz.cpp
│   └── test_standalone_svg_rasterizer.cpp
├── markdown_fuzz_corpus/        # input corpus for the markdown fuzz harness
├── svg_corpus/                  # SVG files and the pictures Chrome made of them (standalone_svg_rasterizer_tests)
├── scene/                       # scene-graph fixtures consumed by Python tests
├── golden/                      # golden reference images (do not edit by hand)
│   ├── vulkan/                  # baselines captured under headless Vulkan
│   ├── egl/                     # baselines captured under headless EGL
│   ├── opengl/                  # baselines captured under windowed OpenGL
│   └── shared/                  # one reference image for tests that compare the platform screenshot on every backend
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
- `byte_image_upload_status_tests` — upload results of `ByteImageProvider`
  against a fake backend: rejected and stale uploads, no backend, device
  masks, completion events, failing subscribers, causes and the failure hook
  of one provider. CPU only. Also runs in the ASan job (B2).
- `byte_image_gpu_status_test` — the same checks on a real Vulkan + CUDA
  device: refused uploads (bad CUDA pitch, R8 or 3-channel GPU source, empty
  size) are reported and keep the old pixels byte for byte, a burst of
  asynchronous uploads gives consistent ids, completion is reported. Needs a
  GPU and the CUDA toolkit.
- `egl_upload_completion` — OpenGL upload ids: `eEnqueued` on submit,
  completed only behind a signaled fence, a second device refused. Built with
  `OMNIUI_HEADLESS_GL=ON`; it starts headless EGL like the other EGL tests
  (Mesa surfaceless works without a GPU) and fails when EGL does not start.
  Runs in the EGL surfaceless job.
- `standalone_svg_rasterizer_tests` — the standalone SVG rasterizer with a real
  `VectorImageProvider` and a fake GPU (CI leg B2 runs it). The `ui.Image`
  backend must load an `.svg` file through the same rasterizer: the same
  texture as `VectorImageProvider` for the same file and size, kept until its
  last user is gone, and no release after shutdown into the cache of a new
  rasterizer. It also paints each
  file of `svg_corpus/` (shapes, paths, arcs, fill rules, caps, joins, dashes,
  gradients, transforms, opacity, colors, CSS, `<use>`, clip paths, and in
  `svg_corpus/icons/` the icons of ovui-widgets) and compares the pixels with
  the picture Google Chrome made of the same file (`svg_corpus/chrome/`): for
  each file the mean difference of the premultiplied channels must be at most
  1.5 of 255, and at most 0.25% of the pixels may differ by more than 96
  (0.75% for `stroke_dash` and `gradient_linear`, where Chrome places short
  dashes on curves and samples the seam of a repeated gradient a little
  differently). Remake the Chrome pictures with
  `python tests/svg_corpus/make_chrome_pictures.py` after a file there changes.
  It also feeds cut-off and changed files to the SVG reader, which must refuse
  them or draw them without a crash, and files whose work multiplies (entity
  expansion, `<use>` fan-out, selectors over nested groups, style rule and
  declaration products, a large `style` attribute repeated by `<use>`, long
  gradient stop lists, deep nesting through `<use>`, nested layers, curves, many
  large shapes), which must be refused with the
  limit that they pass, each on its own thread within 20 s and 768 MiB of
  memory growth (past a bound the test ends at once). A test-only seam
  (`OVUI_SVG_TEST_SEAM`, compiled only into this test) throws `std::bad_alloc`
  and another exception while a file is read: the image must stay empty and the
  cause must be logged once. Other cases check malformed XML (refused with its
  line, column and cause), filters and masks on the root `<svg>` (one warning),
  fallbacks with their cause, and that an error is logged again after the file
  drew. The Python test
  `test_standalone_svg_image.py` draws an `.svg` through `ui.init` in
  `ui.ImageWithProvider` and in `ui.Image`, and compares each screenshot with
  the same reference image `golden/shared/StandaloneSvgImage.shapes.png`
  (legs B1, B3; the mean error limit is 0.05, the two backends differ by about
  0.02, a wrong shape, edge or scale differs by 0.13 or more). It also draws the
  file in `ui.MarkdownWidget`, which must show the shapes at the size of the
  file, log no error and match `golden/shared/StandaloneSvgImage.markdown.png`.
  The same picture must come from the other forms of the same SVG that the SVG
  reader accepts: a file whose elements have a namespace prefix
  (`<s:svg xmlns:s=...>`), and a `data:image/svg+xml;base64` URI that ends with
  one or with two `=`. It uses the
  platform screenshot request, not the GL read-back of `finalize_test`, which
  gave a frame of one grey color for this test on EGL. A second B1 job, "SVG
  option OFF", builds with `OMNIUI_CMAKE_ARGS="-DOMNIUI_ENABLE_SVG=OFF"` and
  runs the same file, where the same tests compare the screenshot with
  `golden/shared/StandaloneSvgImage.svg_off.png` (nothing is drawn) or, for
  Markdown, with `golden/shared/StandaloneSvgImage.markdown_svg_off.png` (the
  image placeholder), and check that the file logs one error that names the
  option. The tests never skip: they
  read the build state from the library
  (`_ui._is_svg_rasterizer_built_in()`), not from the environment, and check
  the behavior of that build.
  Regenerate the images with
  `OMNI_UI_GENERATE_GOLDEN=1 pytest tests/test_standalone_svg_image.py`, once
  on a default build and once on a build with the option OFF.
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
| `OMNI_UI_GENERATE_GOLDEN`         | `1` — overwrite the golden with the current capture. Use when intentionally rebaselining.    |
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
| `requires_cuda`  | Test needs a CUDA-capable GPU. Skipped on CPU CI legs; the full-GPU Windows job runs the headless export tests.                       |

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

Only the listed tests get rewritten. `OMNI_UI_GENERATE_GOLDEN=1` does
**not** loop over backends — you must re-run the
command on each backend whose goldens you want to regenerate.

The `.github/workflows/generate-goldens.yml` workflow does this on a CI
runner for the headless backends (Vulkan-Lavapipe and EGL-surfaceless),
then commits and pushes the regenerated baselines directly to the
dispatched branch.

### Missing goldens and failed captures

A missing golden fails the test. A failed screenshot capture fails the
test. Only `OMNI_UI_GENERATE_GOLDEN=1` creates a golden, so a random local
run cannot create one that is then committed without review.

On B1 and B3, existing baselines are compared on every PR. Regenerate backend
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

### Native frame pacing with a fake frame source

`test_native_frame_pacing_upload.py` drives native frame pacing with the fake
frame source in `standalone/tests/fake_frame_source.cpp` (target
`omniui_fake_frame_source`, built when the CUDA toolkit is found). The test
finds `libomniui_fake_frame_source.so` in the ovui build folder;
`OMNIUI_FAKE_FRAME_SOURCE` can name another one. It skips only on a computer
that has no NVIDIA GPU (none listed by the driver tools and no CUDA device). On a
computer with an NVIDIA GPU every other problem fails the test with its cause: a
CUDA error, a missing library, no native frame pacing, or an ovui that cannot
import Vulkan memory into CUDA. Run this test separately on a compatible
GPU machine; public hosted CI does not provide that hardware.

### Transparent headless export on a full GPU

On Windows, run `TestHeadlessClearColor`, `TestClearColorBeforeInit` and
`TestHeadlessFrameEndToEnd` against the compiled wheel on a compatible
full GPU, with headless Vulkan selected explicitly. This checks
PNG and BMP files through Pillow and the real CUDA `copy_to_linear` buffer,
including transparent and partial-alpha clear colors. Require a normal
process exit and all seven checks to pass, without skips, and retain the
test report. Headless Vulkan tests call `standalone.shutdown()` at session
teardown and let Python exit normally. Use a full GPU because the existing
CUDA/Vulkan device match can refuse MIG slices.
