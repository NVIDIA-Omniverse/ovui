# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# core/CMakeLists.txt - libovui.so (omni.ui core)
# ==============================================================================

file(GLOB CORE_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/src/*.cpp
)
file(GLOB PLATFORM_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/src/platform/*.cpp
)
file(GLOB IMGPROVIDER_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/src/ImageProvider/*.cpp
)
file(GLOB MARKDOWN_SRC
    ${CMAKE_CURRENT_SOURCE_DIR}/src/markdown/*.cpp
)

set(OVUI_CORE_LIBRARY_TYPE SHARED)
if(EMSCRIPTEN)
    # Browser wasm builds link ovui into the consuming module instead of
    # producing a second wasm dynamic library.
    set(OVUI_CORE_LIBRARY_TYPE STATIC)
endif()

add_library(ovui ${OVUI_CORE_LIBRARY_TYPE}
    ${CORE_SRC}
    ${PLATFORM_SRC}
    ${IMGPROVIDER_SRC}
    ${MARKDOWN_SRC}
)

target_include_directories(ovui
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${OVUI_IMGUI_ROOT}/imgui   # for imgui_freetype.h -> "imgui.h"
)

# Inherit imgui's include directories (for <imgui/imgui.h>)
target_include_directories(ovui PUBLIC
    $<TARGET_PROPERTY:imgui,INTERFACE_INCLUDE_DIRECTORIES>
)

# md4c headers (private -- only needed by markdown/*.cpp inside ovui)
target_include_directories(ovui PRIVATE
    $<TARGET_PROPERTY:md4c,INTERFACE_INCLUDE_DIRECTORIES>
)

target_compile_definitions(ovui
    PRIVATE
        OMNIUI_EXPORTS
        IMGUI_NVIDIA
        # The common NVIDIA shadow extension uses bit zero (see PATCHES.md).
        ImDrawFlags_ShadowCutOutShapeBackground=\(1<<0\)
)

# Relax strictness for ImGui and third-party API type mismatches
if(MSVC)
    target_compile_options(ovui PRIVATE /W3 /wd4244 /wd4267 /wd4305 /wd4996)
else()
    target_compile_options(ovui PRIVATE -fpermissive -Wno-error)
endif()

target_link_libraries(ovui
    PUBLIC
        imgui
        # Header-only deps used in ovui's public headers (must propagate to consumers)
        glm
        boost_preprocessor
    PRIVATE
        stb
        glad
        md4c
        Freetype::Freetype
)

set_target_properties(ovui PROPERTIES
    OUTPUT_NAME ovui
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
if(NOT WIN32 AND NOT EMSCRIPTEN)
    # The file is libovui.so; its internal name is libomni.ui.so, which
    # every consumer records, and a libomni.ui.so link sits next to it.
    set_target_properties(ovui PROPERTIES NO_SONAME ON)
    target_link_options(ovui PRIVATE "-Wl,-soname,libomni.ui.so")
    add_custom_command(TARGET ovui POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E create_symlink libovui.so "$<TARGET_FILE_DIR:ovui>/libomni.ui.so")
endif()
if(APPLE)
    set_target_properties(ovui PROPERTIES
        # Cover both the wheel layout (omni/ui, omni/ui_scene) and the build
        # tree (build/pip/core, build/pip/standalone). Non-existent entries
        # are silently skipped by the loader. BUILD_WITH_INSTALL_RPATH bakes
        # this in at build time so wheels don't carry leaked build-dir paths.
        INSTALL_RPATH "@loader_path;@loader_path/../third_party;@loader_path/../core;@loader_path/../standalone;@loader_path/../ui;@loader_path/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
elseif(NOT WIN32 AND NOT EMSCRIPTEN)
    set_target_properties(ovui PROPERTIES
        # Cover both the wheel layout (omni/ui, omni/ui_scene) and the build
        # tree (build/pip/core, build/pip/standalone). Non-existent entries
        # are silently skipped by the loader. BUILD_WITH_INSTALL_RPATH bakes
        # this in at build time so wheels don't carry leaked build-dir paths.
        INSTALL_RPATH "$ORIGIN:$ORIGIN/../third_party:$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene"
        BUILD_WITH_INSTALL_RPATH ON
    )
endif()
ovui_shared_rpath(ovui "${OVUI_RPATH_CORE}")
if(WIN32)
    # Exports: the OMNIUI_API declarations plus SimpleListModel::create.
    set_target_properties(ovui PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
    target_compile_options(ovui PRIVATE /permissive-)
    target_link_options(ovui PRIVATE
        "/EXPORT:?create@SimpleListModel@ui@omni@@SA?AV?$shared_ptr@VSimpleListModel@ui@omni@@@std@@XZ")

    # omni.ui.dll: forwards every omni::ui export to ovui.dll. The shared
    # binaries (scene library, _ui, _scene) import the UI core through this
    # name, as in hosts where omni.ui.dll is a plugin with the same
    # forwarders. Generated from the finished ovui.dll by tools/forwarders.
    find_package(Python3 COMPONENTS Interpreter REQUIRED)
    set(_ovui_fwd_dir "${CMAKE_CURRENT_BINARY_DIR}/forwarders")
    set(_ovui_fwd_script "${CMAKE_SOURCE_DIR}/tools/forwarders/generate_ui_forwarders.py")
    add_custom_command(
        OUTPUT "${_ovui_fwd_dir}/omni.ui.forwarders.def" "${_ovui_fwd_dir}/omni.ui.forwarders.json"
        COMMAND Python3::Interpreter "${_ovui_fwd_script}"
            --input "$<TARGET_FILE:ovui>"
            --output "${_ovui_fwd_dir}/omni.ui.forwarders.def"
            --manifest "${_ovui_fwd_dir}/omni.ui.forwarders.json"
        DEPENDS ovui "${_ovui_fwd_script}"
        COMMENT "Generating omni.ui.dll forwarders to ovui.dll"
        VERBATIM)
    file(GENERATE OUTPUT "${_ovui_fwd_dir}/forwarders.c"
        CONTENT "/* omni.ui.dll only forwards to ovui.dll; see omni.ui.forwarders.def. */\nint ovui_forwarders_only;\n")
    add_library(ovui_forwarders SHARED
        "${_ovui_fwd_dir}/forwarders.c" "${_ovui_fwd_dir}/omni.ui.forwarders.def")
    set_target_properties(ovui_forwarders PROPERTIES
        OUTPUT_NAME omni.ui
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
    add_dependencies(ovui_forwarders ovui)
endif()

# What the shared binaries link for the UI core: ovui itself, or on Windows
# its headers plus the omni.ui.dll import library.
add_library(ovui_shared_link INTERFACE)
if(WIN32)
    target_include_directories(ovui_shared_link INTERFACE $<TARGET_PROPERTY:ovui,INTERFACE_INCLUDE_DIRECTORIES>)
    target_link_libraries(ovui_shared_link INTERFACE ovui_forwarders imgui glm boost_preprocessor)
else()
    target_link_libraries(ovui_shared_link INTERFACE ovui)
endif()

if(NOT (EMSCRIPTEN AND (OMNI_UI_BUILD_PYODIDE_BINDINGS OR OMNI_UI_BUILD_WEB_RUNTIME)))
    # ==========================================================================
    # ovuiscene: carb-free scene core (mirrors ovui for omni.ui.scene)
    # ==========================================================================
    file(GLOB OVUISCENE_SOURCES
        ${CMAKE_CURRENT_SOURCE_DIR}/src/scene/*.cpp
    )

    add_library(ovuiscene SHARED ${OVUISCENE_SOURCES})

    target_compile_definitions(ovuiscene
        PRIVATE
            OMNIUI_SCENE_EXPORTS
            IMGUI_NVIDIA
    )

    target_include_directories(ovuiscene
        PUBLIC
            ${CMAKE_CURRENT_SOURCE_DIR}/include
        PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/src
    )

    target_link_libraries(ovuiscene
        PUBLIC
            ovui_shared_link
        PRIVATE
            glm
            boost_preprocessor
    )

    if(MSVC)
        target_compile_options(ovuiscene PRIVATE /W3 /wd4244 /wd4267 /wd4305 /wd4996)
    else()
        target_compile_options(ovuiscene PRIVATE -fpermissive -Wno-error)
    endif()

    # Shared name: libomni.ui.scene.so / omni.ui.scene.dll.
    set_target_properties(ovuiscene PROPERTIES
        OUTPUT_NAME omni.ui.scene
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN ON
    )
    if(NOT WIN32)
        set_target_properties(ovuiscene PROPERTIES
            # See ovui target above for rationale on this multi-entry RPATH
            # and BUILD_WITH_INSTALL_RPATH.
            INSTALL_RPATH "$ORIGIN:$ORIGIN/../third_party:$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene"
            BUILD_WITH_INSTALL_RPATH ON
        )
    endif()
    ovui_shared_rpath(ovuiscene "${OVUI_RPATH_SCENE}")
    if(WIN32)
        # Exports: the OMNIUI_SCENE_API declarations.
        target_compile_options(ovuiscene PRIVATE /permissive-)
        set_target_properties(ovuiscene PROPERTIES
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
            ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        )
    endif()
endif()
