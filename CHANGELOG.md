# Changelog

## 0.2.0 - 16-06-2026

### Added

- CycloneDX SBOM generation (`sbom.cdx.json`) is now produced automatically as part of the wheel build.
  - `ovui/tools/sbom/conanfile.py` declares the C++ dependency graph for Conan to resolve.
  - `ovui/tools/sbom/enrich_sbom_licenses.py` post-processes the Conan output to add full license text, CPE identifiers, corrected PURLs, and Python build/optional dependencies.
  - `sbom.cdx.json` is bundled inside the `omni.ui` package alongside `THIRD_PARTY_NOTICES.md`.
- `conan>=2.14` and `cyclonedx-python-lib>=5.0.0,<6` added to `ovui/pyproject.toml` build-system requirements.

To regenerate the SBOM manually from the repository root:

```bash
conan cyclonedx --format 1.4_json ovui/tools/sbom/conanfile.py --no-build-requires --out-file sbom.cdx.json
python3 ovui/tools/sbom/enrich_sbom_licenses.py --sbom sbom.cdx.json
```

### Runtime validation boundaries and known limitations

- Pull-request package CI builds the affected wheels and checks two clean
  installs: the common adapter with NumPy, and `ovui-widgets-all` with standalone
  OpenUSD. These checks prove package metadata, installation, and imports on
  supported hosted runners. They do not run Kit, OVStage, OVRTX, or a GPU.
- The OVStage provider is native-only: it drives the external native `ovstage`
  runtime directly, depends only on the common adapter contracts, and never
  imports `pxr` or the OpenUSD adapter package (isolation tests enforce the
  boundary). It requires one matching Kit/OVStage/OVRTX runtime exposing
  callable `ovstage.Stage` and the public Python BORROW methods
  `Renderer.attach_ovstage`, `Renderer.detach_ovstage`, and `Renderer.step`
  with an `ordinal` keyword while attached. Startup preflight rejects an
  incompatible runtime and names the missing module or API; it does not fall
  back to a read-only path, scene replication, or an OpenUSD stage.
- The native OVStage/OVRTX BORROW path still has these limits:
  - durable new-document creation, save/export, layer-stack and composition
    operations, and clearing authored property values are unavailable with the
    native provider; the standalone `openusd` provider covers those workflows;
  - selected objects receive a renderer-owned selection outline on the
    supported attach-capable ovrtx 0.4 path; a runtime that does not expose the
    outline-membership API degrades honestly (selection still synchronizes, no
    outline appears);
  - point-cloud request and error handling is partial, and real payload parity
    plus radar support are not claimed;
  - physics requires a matching `ovphysx` runtime (loaded lazily when physics
    is enabled) and reports a structured error without it;
  - picking has no completed multi-GPU policy or validation result;
  - private renderer settings do not yet have a defined persistence owner; and
  - the complete native open/edit/render/pick/drag/shutdown flow has not been
    validated on Windows.

## 0.1.0 - 22-05-2026

Initial release.
