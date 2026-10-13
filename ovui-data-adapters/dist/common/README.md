# ovui-data-adapters-common

`ovui-data-adapters-common` is the adapter contract and registry wheel for
ovui and ovui-widgets data providers. It contains the abstract adapter records and
the provider registry used by the application to select a concrete backend.

## What It Provides

- Common adapter ABCs and value records in `ovui_data_adapters.common`.
- The provider-neutral livestream frame conversion helper shared by concrete
  renderer adapters.
- `AdapterFactories`, `AdapterRegistry`, `discover_adapter_modules`, and
  `select_adapter`.
- The adapter entry-point group name:
  `ovui_data_adapters.adapters`.

This package does not provide a concrete scene backend. Concrete providers such
as OpenUSD and ovstage register factories through the common entry-point group.

## Installation

Editable install from the repository:

```bash
python -m pip install -e ovui-data-adapters/dist/common
```

Wheel build from the repository:

```bash
python -m build ovui-data-adapters/dist/common
```

The `pyproject.toml` uses `where = ["../.."]` so the wheel sources resolve to
`ovui-data-adapters/ovui_data_adapters/common`.

## Dependencies

The common wheel requires Python 3.10 or newer and `numpy>=1.20`, which its
shipped livestream helper imports for host-frame conversion. `ovstream` remains
optional and is imported lazily only when livestream is enabled; deployments
using that feature must supply the matching ovstream runtime separately.

## Usage

Application code discovers providers through the common registry:

```python
from ovui_data_adapters.common import discover_adapter_modules, select_adapter

registry = discover_adapter_modules()
factories = select_adapter(registry, "ovstage")
```

Provider packages are selected by name through the registry. The application
also supports provider selection with `OVUI_DATA_ADAPTER_PROVIDER`.
