# Native SDK in the ovui wheel

Every native wheel includes `omni/ui/sdk/`:

- `include/`: public UI and scene headers, unchanged from the producing source.
- `src/`: source-side platform/image headers needed by the Kit bridge, preserving relative includes.
- `third_party/`: the exact ImGui, GLM, Boost.Preprocessor and pybind11 headers used by the producer.
- `lib/`: Windows core and scene import libraries from the same build.
- `licenses/`: project license and dependency notices.
- `build.json` and `manifest.json`: build identity, source revision and SDK file hashes.
- `cmake/ovui-sdk-config.cmake`: relocatable `ovui::core` and `ovui::scene` imported targets.

For CMake consumers, set `ovui-sdk_DIR` to the extracted `omni/ui/sdk/cmake` directory and link `ovui::core` or `ovui::scene`. Preserve the wheel's `omni/ui` and `omni/ui_scene` relative layout. The consumer supplies its own compiler and matching Python development environment. Header availability alone does not establish compatibility with a different ImGui configuration, pybind11 version or C++ runtime.

Build the real artifact with `python -m pip wheel ./ovui --no-deps -w ./dist`.
The packaged manifest records each SDK file and its producing source revision.
The SDK uses Kit's pybind11 2.11.1 and shared ImGui configuration. The imported
`ovui::imgui` target resolves the same drawing library used by `ovui::core`;
Windows includes its `imgui.lib` alongside the core and scene import libraries.
No additional test or example consumer is installed in the repository.
