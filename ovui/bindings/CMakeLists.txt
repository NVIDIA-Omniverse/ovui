# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT TARGET pybind11::module)
    find_package(pybind11 2.11.1 CONFIG REQUIRED)
endif()

# The shared `_ui` module: the same binary in the wheel and in every host's
# omni.ui build. Host code reaches it only through omni/ui/bind/PlatformHooks.h.
# NO_EXTRAS: no LTO and no strip, as in the other builds (LTO changes which symbols are exported).
pybind11_add_module(_ui NO_EXTRAS Module.cpp BindCornerFlag.cpp PlatformBindings.cpp)

target_link_libraries(_ui PRIVATE ovui_shared_link)

target_include_directories(_ui PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/core/include
    ${CMAKE_SOURCE_DIR}/core/src
)

target_compile_definitions(_ui PRIVATE IMGUI_NVIDIA)
if(MSVC)
    # Export the style helpers other binding modules import from _ui.pyd.
    set_source_files_properties(Module.cpp PROPERTIES
        COMPILE_OPTIONS "/FI${CMAKE_CURRENT_SOURCE_DIR}/BindingExportBoundary.h")
endif()

# The standalone bridge (wheel only): installs the platform hooks that add
# the standalone entry points to `_ui`.
pybind11_add_module(_standalone StandalonePlatformBindings.cpp)

target_link_libraries(_standalone PRIVATE ovui omniui_standalone)

target_include_directories(_standalone PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/core/include
    ${CMAKE_SOURCE_DIR}/core/src
    ${CMAKE_SOURCE_DIR}/standalone/src
)

target_compile_definitions(_standalone PRIVATE IMGUI_NVIDIA)

if(APPLE)
    set_target_properties(_ui _standalone PROPERTIES
        # See ovui/core/CMakeLists.txt for rationale on this multi-entry
        # RPATH and BUILD_WITH_INSTALL_RPATH.
        INSTALL_RPATH "@loader_path;@loader_path/../core;@loader_path/../standalone;@loader_path/../ui;@loader_path/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
elseif(NOT WIN32)
    set_target_properties(_ui _standalone PROPERTIES
        # See ovui/core/CMakeLists.txt for rationale on this multi-entry
        # RPATH and BUILD_WITH_INSTALL_RPATH.
        INSTALL_RPATH "$ORIGIN:$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
endif()
ovui_shared_rpath(_ui "${OVUI_RPATH_UI_MODULE}")
ovui_shared_module(_ui)
if(WIN32)
    set_target_properties(_ui _standalone PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# Copy module to the Python package directory after every build so that
# ``python tests/run_tests.py`` always picks up the freshly-built binary.
set(_PY_PKG_DIR "${CMAKE_SOURCE_DIR}/python/omni/ui")

# Publish rebuilt runtime dependencies even when _standalone is up to date.
add_custom_target(stage_ui_runtime
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_PY_PKG_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:imgui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:omniui_standalone> "${_PY_PKG_DIR}/"
    COMMENT "Staging standalone runtime libraries to ${_PY_PKG_DIR}"
    VERBATIM
)
add_dependencies(stage_ui_runtime imgui ovui omniui_standalone)
if(WIN32)
    add_custom_command(TARGET stage_ui_runtime POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovui_forwarders> "${_PY_PKG_DIR}/"
        VERBATIM)
    add_dependencies(stage_ui_runtime ovui_forwarders)
endif()
add_dependencies(_standalone _ui stage_ui_runtime)

add_custom_command(TARGET _standalone POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:_ui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:_standalone> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:imgui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:omniui_standalone> "${_PY_PKG_DIR}/"
    COMMENT "Copying _ui, _standalone, ovui, omniui_standalone to ${_PY_PKG_DIR}"
)
# Also copy the SONAME and linker-name variants so the editable install's
# python/omni/ui/ matches the wheel layout. The dynamic linker resolves
# NEEDED libomni.ui.so against the link next to libovui.so.
if(NOT WIN32)
    add_custom_command(TARGET _standalone POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E create_symlink libovui.so "${_PY_PKG_DIR}/libomni.ui.so"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_SONAME_FILE:omniui_standalone> "${_PY_PKG_DIR}/"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_LINKER_FILE:omniui_standalone> "${_PY_PKG_DIR}/"
        COMMENT "Copying versioned variants of omniui_standalone to ${_PY_PKG_DIR}"
    )
endif()

# Install the extension modules next to the Python package
install(TARGETS _ui _standalone DESTINATION ${CMAKE_SOURCE_DIR}/python/omni/ui)

# ─── _scene pybind11 module ──────────────────────────────────────────────────
file(GLOB SCENE_BIND_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/scene/Bind*.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/scene/Module.cpp
)

pybind11_add_module(_scene NO_EXTRAS ${SCENE_BIND_SOURCES})

target_link_libraries(_scene PRIVATE ovui_shared_link ovuiscene)
if(UNIX AND NOT APPLE)
    # Shared dependency order: the UI core before the scene library. The core is
    # needed anyway; --no-as-needed records it here, ahead of the scene library.
    target_link_options(_scene PRIVATE
        "LINKER:--push-state,--no-as-needed" "$<TARGET_LINKER_FILE:ovui>" "LINKER:--pop-state")
endif()

target_include_directories(_scene PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/core/include
    ${CMAKE_SOURCE_DIR}/core/src
)

target_compile_definitions(_scene PRIVATE IMGUI_NVIDIA)

if(APPLE)
    set_target_properties(_scene PROPERTIES
        # See ovui/core/CMakeLists.txt for rationale on this multi-entry
        # RPATH and BUILD_WITH_INSTALL_RPATH.
        INSTALL_RPATH "@loader_path;@loader_path/../core;@loader_path/../standalone;@loader_path/../ui;@loader_path/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
elseif(NOT WIN32)
    set_target_properties(_scene PROPERTIES
        # See ovui/core/CMakeLists.txt for rationale on this multi-entry
        # RPATH and BUILD_WITH_INSTALL_RPATH.
        INSTALL_RPATH "$ORIGIN:$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
endif()
ovui_shared_rpath(_scene "${OVUI_RPATH_SCENE_MODULE}")
ovui_shared_module(_scene)
if(WIN32)
    set_target_properties(_scene PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# Copy _scene module and ovuiscene to the Python package dir after every build.
set(_SCENE_PY_DIR "${CMAKE_SOURCE_DIR}/python/omni/ui_scene")
add_custom_command(TARGET _scene POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_SCENE_PY_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:_scene>    "${_SCENE_PY_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovuiscene> "${_SCENE_PY_DIR}/"
    COMMENT "Copying _scene and ovuiscene to ${_SCENE_PY_DIR}"
)

install(TARGETS _scene DESTINATION ${CMAKE_SOURCE_DIR}/python/omni/ui_scene)
