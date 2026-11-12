# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Relocatable imported targets for the SDK inside an installed/extracted wheel.
get_filename_component(_ovui_sdk "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
get_filename_component(_ovui_ui "${_ovui_sdk}/.." ABSOLUTE)
get_filename_component(_ovui_omni "${_ovui_ui}/.." ABSOLUTE)
file(READ "${_ovui_sdk}/build.json" _ovui_build)
string(JSON _ovui_core_library GET "${_ovui_build}" core_library)
string(JSON _ovui_imgui_library GET "${_ovui_build}" imgui_library)
string(JSON _ovui_scene_library GET "${_ovui_build}" scene_library)

if(NOT TARGET ovui::imgui)
    add_library(ovui::imgui SHARED IMPORTED)
    set_target_properties(ovui::imgui PROPERTIES
        IMPORTED_LOCATION "${_ovui_ui}/${_ovui_imgui_library}"
        INTERFACE_INCLUDE_DIRECTORIES "${_ovui_sdk}/third_party")
    if(WIN32)
        set_target_properties(ovui::imgui PROPERTIES
            IMPORTED_IMPLIB "${_ovui_sdk}/lib/imgui.lib"
            INTERFACE_COMPILE_DEFINITIONS "IMGUI_API=__declspec(dllimport);IMGUI_IMPL_API=")
    endif()
endif()
if(NOT TARGET ovui::core)
    add_library(ovui::core SHARED IMPORTED)
    set_target_properties(ovui::core PROPERTIES
        IMPORTED_LOCATION "${_ovui_ui}/${_ovui_core_library}"
        INTERFACE_INCLUDE_DIRECTORIES "${_ovui_sdk}/include;${_ovui_sdk}/src;${_ovui_sdk}/third_party"
        INTERFACE_LINK_LIBRARIES ovui::imgui
        INTERFACE_COMPILE_DEFINITIONS IMGUI_NVIDIA
        INTERFACE_COMPILE_FEATURES cxx_std_17)
    if(WIN32)
        # The wheel's modules use pybind11's type registry key without the compiler version (ovui/CMakeLists.txt).
        set_target_properties(ovui::core PROPERTIES IMPORTED_IMPLIB "${_ovui_sdk}/lib/ovui.lib"
            INTERFACE_COMPILE_DEFINITIONS "IMGUI_NVIDIA;PYBIND11_BUILD_ABI=\"\"")
    endif()
endif()
if(NOT TARGET ovui::scene)
    add_library(ovui::scene SHARED IMPORTED)
    set_target_properties(ovui::scene PROPERTIES
        IMPORTED_LOCATION "${_ovui_omni}/ui_scene/${_ovui_scene_library}"
        INTERFACE_LINK_LIBRARIES ovui::core)
    if(WIN32)
        set_target_properties(ovui::scene PROPERTIES IMPORTED_IMPLIB "${_ovui_sdk}/lib/omni.ui.scene.lib")
    endif()
endif()
