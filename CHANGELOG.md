# Changelog

## 0.3.1

- ovui works with the newest and the previous renderer and stage libraries.
- If the renderer and stage libraries do not match, the app tells you to
  install a matched pair.
- Viewport navigation is smoother.
- One wheel for each platform works with all supported Python versions.
- `ui.Image` and the Markdown widget show SVG files.
- You can select a light when you click its gizmo in the viewport.
- Save, Save As and Exit keep your edits and layers.
- Memory grows less when the app is idle or when you open the same file again.
- The app no longer crashes sometimes when it opens a large scene with the
  ovstage data source.

- `import omni.ui` no longer imports the Kit modules `carb` and `omni.kit.app`
  when they are installed. A host such as Kit gives its mouse-button and
  modifier constants, logging and settings store to the new
  `omni.ui_scene.gesture_bindings.set_host()`. `ui.RpResource` and
  `ui.TextureFormat` are unchanged.
- `omni.ui.get_frame_pacing_status()` has the new key `renderer_version`.
  **Announced for removal:** the old key `ovrtx_version`. It still holds the
  same value in this release.

## 0.3.0

- Publish the framework, widgets, adapters, and packaged agent skills as the
  synchronized 0.3.0 release, with first-party wheel dependencies pinned to
  the same version.
- Distribute NVIDIA-authored source under Apache 2.0 and include the license
  and third-party notices in published packages.
- Add clean-wheel installation and application regression coverage, including
  renderer loading, viewport resize/selection, and numeric-field keyboard input.

- Restore embedded scene-widget frames in Kit through the existing virtual-window,
  renderer, GPU resource and input services; preserve standalone backend behavior.
- Return Kit's registered Python GPU resource, image format and application-window
  types, so the viewport presents native frames after a library/binding replacement.
- Supply the existing host binding entry points for upload status, docking flags
  and the native legacy slider. Keep all mapped shared sources unchanged.
- Include pinned, unmodified host interface headers in source packages.
- Synchronize the complete ImGui dependency and drawing configuration with Kit;
  deliver it as one shared native library.
- Pin native and browser binding builds to Kit's pybind11 2.11.1.
- Ship the native UI/scene SDK, dependency headers, Windows link libraries,
  notices and source/file manifests in the wheel.
- Synchronize Workspace callback ownership with Kit and release standalone
  callback owners before shutdown.
- Update 38 ovui image references only after pixel-identical comparison with
  unchanged Kit-mainline ImGui; retain all existing tests and acceptance settings.

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
  - selected borrowed objects may have correct logical selection without a
    visible selection outline;
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
