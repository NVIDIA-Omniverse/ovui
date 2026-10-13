# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Search paths of the four shared binaries (Linux). The same files are placed
# in the omni.ui / omni.ui.scene extensions and in the wheel, so each carries
# the extension entries followed by the wheel and build-tree entries, as
# DT_RPATH. Any other build of these binaries must write the same lists.
set(_ovui_rpath_library "$ORIGIN/../third_party:$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene")
set(_ovui_rpath_module "$ORIGIN/../core:$ORIGIN/../standalone:$ORIGIN/../ui:$ORIGIN/../ui_scene")
set(OVUI_RPATH_CORE "$ORIGIN:$ORIGIN/../../omni.usd.libs/bin:${_ovui_rpath_library}")
set(OVUI_RPATH_SCENE "$ORIGIN/../../omni.ui/bin:$ORIGIN:$ORIGIN/../../omni.usd.libs/bin:${_ovui_rpath_library}")
set(OVUI_RPATH_UI_MODULE "$ORIGIN/../../bin:$ORIGIN:$ORIGIN/../../omni.usd.libs/bin:${_ovui_rpath_module}")
set(OVUI_RPATH_SCENE_MODULE "$ORIGIN/../../../omni.ui/bin:$ORIGIN/../../bin:$ORIGIN:$ORIGIN/../../omni.usd.libs/bin:${_ovui_rpath_module}")

# Applies one of the lists above to a shared binary.
function(ovui_shared_rpath target rpath)
    if(UNIX AND NOT APPLE AND NOT EMSCRIPTEN)
        set_target_properties(${target} PROPERTIES INSTALL_RPATH "${rpath}" BUILD_WITH_INSTALL_RPATH ON)
        target_link_options(${target} PRIVATE "-Wl,--disable-new-dtags")
    endif()
endfunction()

# The shared Python modules as every build makes them: inline functions hidden and,
# on Linux, the file name as internal name.
function(ovui_shared_module target)
    set_target_properties(${target} PROPERTIES VISIBILITY_INLINES_HIDDEN ON)
    if(MSVC)
        target_compile_options(${target} PRIVATE /bigobj)
    endif()
    if(UNIX AND NOT APPLE AND NOT EMSCRIPTEN)
        target_link_options(${target} PRIVATE "-Wl,-soname,$<TARGET_FILE_NAME:${target}>")
    endif()
endfunction()
