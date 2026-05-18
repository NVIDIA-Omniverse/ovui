# ovui monorepo

Three independently-built but co-developed Python projects in one
repository. The merge from the standalone `ovui` and USD Viewer (`ovgear`) repos
preserves the full history of both.

## Layout

```
.
├── ovui/                  ← UI framework: omni.ui + omni.ui_scene + native libs
├── ovwidgets/             ← Application widgets layer (stage / layers / property /
│                            content / viewport / app) with per-component dists
└── ovui-data-adapters/    ← Adapter contracts (common) + OpenUSD adapters (openusd)
```

Each top-level directory is a self-contained project root. They are
co-located so a single PR can change framework code, widget code, and
adapter code in lock-step, but they install and ship as independent
distributions:

- `ovui/setup.py` builds the native UI framework (cmake + ninja
  + setuptools) and ships as the `ovui` wheel.
- `ovwidgets/dist/{all,app,common,content,layers,property,stage,viewport}/pyproject.toml`
  ship as `ovwidgets-<sub>` distributions; per-component install
  uses `where = ["../.."]`.
- `ovui-data-adapters/dist/{common,openusd}/pyproject.toml` ship
  as `ovui-data-adapters-{common,openusd}`; same `where = ["../.."]`
  pattern, source under the unified
  `ovui-data-adapters/ovui_data_adapters/` import-package root.

## Per-component documentation

- [`ovui/README.md`](ovui/README.md) — UI framework
- [`ovwidgets/README.md`](ovwidgets/README.md) — application widgets
- [`ovui-data-adapters/README.md`](ovui-data-adapters/README.md) — adapter contracts and OpenUSD adapters

## Development workflow

For a fresh dev venv:

```bash
python3.12 -m venv ovwidgets/_venv312
ovwidgets/_venv312/bin/pip install -U pip setuptools wheel build pytest pytest-asyncio ruff mypy
ovwidgets/_venv312/bin/pip install -e ovui/
ovwidgets/_venv312/bin/pip install -e /path/to/ovrtx/python      # external dep
ovwidgets/_venv312/bin/pip install -e ovui-data-adapters/dist/common
ovwidgets/_venv312/bin/pip install -e ovui-data-adapters/dist/openusd
# then install ovwidgets/dist/<sub>/ packages in dependency order.
```

Windows source installs need the Windows prerequisites in
[`ovui/README.md`](ovui/README.md#windows-11--windows-server-2022) before
`pip install -e ovui/`. Install the CUDA Toolkit before building if you need
the CUDA-Vulkan byte-image path used by `ovui/examples/byte_image_gpu_demo.py`,
then verify with:

```bash
python -c "import omni.ui as ui; print(ui.has_gpu_byte_image())"
```

## CI

The active automation lives under `.github/workflows/`:

- `build-wheel.yml` builds ovui wheels for Linux x64, Linux ARM64, and
  Windows x64, then smoke-imports the installed wheel.
- `headless-lavapipe.yml` and `headless-egl.yml` build and run the headless
  CTest lanes.
- `test-b1-vulkan.yml`, `test-b2-vulkan-asan.yml`, and `test-b3-egl.yml` run
  the Vulkan pytest, native ASan, and EGL pytest lanes.
- `generate-goldens.yml` regenerates golden images on demand.

## Merge context

The repository was merged from two sources:

- `ovui` — relocated under `ovui/`.
- USD Viewer (`ovgear`) — split into `ovwidgets/` (the import package + its dist
  packages) and `ovui-data-adapters/` (the unified adapter package).

Merge history is preserved in git; the runtime and packaging docs above are the
current source of truth.
