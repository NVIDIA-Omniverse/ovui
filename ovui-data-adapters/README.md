# ovui-data-adapters

Adapter layer that decouples `ovwidgets` from concrete scene-graph
backends. Two distributions:

- **`ovui-data-adapters-common`** — abstract adapter contracts
  (`StageAdapter`, `TransformAdapter`, `LayerStackAdapter`,
  `PropertyAdapter`, `RendererAdapter`, …). No external runtime
  dependencies — pure Python protocols + small dataclasses.

- **`ovui-data-adapters-openusd`** — concrete OpenUSD adapters that
  implement the contracts above. Hard-deps `usd-core==25.11`, `numpy`,
  `ovrtx`.

## Layout

```
ovui-data-adapters/
├── dist/
│   ├── common/pyproject.toml      ← ovui-data-adapters-common
│   └── openusd/pyproject.toml     ← ovui-data-adapters-openusd
└── ovui_data_adapters/            ← unified Python import-package root
    ├── common/                    ← imports as ovui_data_adapters.common
    │   ├── __init__.py
    │   └── adapters.py …
    └── openusd/                   ← imports as ovui_data_adapters.openusd
        ├── __init__.py
        └── stage_adapter.py …
```

**Why dash-form folder, underscore-form package?** The visible
repository folder is `ovui-data-adapters/` (Victor's requirement).
Python identifiers cannot contain dashes, so the import package
inside is `ovui_data_adapters/`. The two distributions
(`ovui-data-adapters-common`, `ovui-data-adapters-openusd`) share
that single import-package root via PEP 420 namespace packages.

## Install

Editable installs use the same `dist/<sub>/pyproject.toml` +
`where = ["../.."]` pattern as `ovwidgets/dist/`:

```bash
pip install -e ovui-data-adapters/dist/common
pip install -e ovui-data-adapters/dist/openusd      # also pulls usd-core==25.11, numpy
```

`ovrtx` (a hard dep of `ovui-data-adapters-openusd`) is NOT on PyPI
— install it separately from its own checkout.

## Sdist support — intentionally absent

The `dist/<sub>/pyproject.toml` + `where = ["../.."]` pattern
supports editable installs and in-tree wheel builds, but **NOT**
sdist publishing: setuptools cannot package source two levels above
the project root in a self-contained tarball. The
`ovwidgets/tests/test_data_adapters_install.py` test enforces that
editable installs work; sdist regenerate is unsupported by design.
If sdist publishing is ever needed, restructure to co-located
pyprojects (`ovui-data-adapters/<sub>/pyproject.toml` next to
source with `where = ["."]`).

## Install checks

The active GitHub Actions workflows live under `.github/workflows/` at the
repository root and currently cover the `ovui/` package build/test lanes.
For adapter packaging changes, run
`ovwidgets/tests/test_data_adapters_install.py`; it verifies the
`ovui-data-adapters-common` editable install in a fresh venv. The OpenUSD
adapter still requires a separately installed `ovrtx` checkout plus
`usd-core==25.11` and `numpy`, as described above.
