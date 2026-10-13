# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

if(NOT TARGET _ui OR NOT TARGET _standalone OR NOT TARGET omniui_standalone OR OMNIUI_HEADLESS_ONLY)
    message(FATAL_ERROR "ovrtx_ui_app requires the Python bindings and windowed standalone backend")
endif()

# Use the SDK path actually resolved by the standalone backend, including an
# explicit OMNIUI_OVRTX_* CMake override.
get_directory_property(_app_OVRTX_INCLUDE_DIR DIRECTORY "${CMAKE_SOURCE_DIR}/standalone"
    DEFINITION OMNIUI_OVRTX_INCLUDE_DIR)
get_filename_component(_ovrtx_public "${_app_OVRTX_INCLUDE_DIR}" DIRECTORY)
get_filename_component(_rendering_root "${_ovrtx_public}/../.." ABSOLUTE)
get_filename_component(_kit_root "${_rendering_root}/.." ABSOLUTE)
get_filename_component(_repo_root "${CMAKE_SOURCE_DIR}/.." ABSOLUTE)

# ovui itself has no scene provider. The developer app installs one data
# adapter from this checkout; OpenUSD needs nothing beyond the renderer SDK, so
# it is the default. Another provider is selected by name and brings its own
# PYTHONPATH and environment through the EXTRA_* entries below.
set(OMNIUI_OVRTX_UI_APP_PROVIDER "openusd"
    CACHE STRING "ovui-data-adapters provider the ovrtx_ui_app environment installs and selects")

set(OMNIUI_OVRTX_UI_APP_RUNTIME_DIR "${_rendering_root}/_build/windows-x86_64/release"
    CACHE PATH "Kit runtime directory for the renderer")
set(OMNIUI_OVRTX_UI_APP_ARGUMENTS "" CACHE STRING "Additional ovui_widgets.app debugger arguments")

foreach(_required
    "${_ovrtx_public}/python/ovrtx/__init__.py"
    "${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR}/ovrtx-dynamic.dll")
    if(NOT EXISTS "${_required}")
        message(FATAL_ERROR "ovrtx_ui_app requires the Kit development SDK/runtime: ${_required}")
    endif()
endforeach()

set(_app_dir "${CMAKE_CURRENT_BINARY_DIR}")
set(_app_python "${_app_dir}/venv/Scripts/python.exe")
set(_app_pythonpath "${_app_dir}/venv/native-metadata;${CMAKE_SOURCE_DIR}/python;${_ovrtx_public}/python")
# Install local distributions together so pip resolves their dependencies from
# this checkout. The renderer SDK/runtime stays supplied by the selected Kit
# checkout. ovui knows no scene provider: the data adapter, its PYTHONPATH and
# its environment are selected below and default to OpenUSD. A provider-specific
# recipe lives with that provider's own adapter package.
set(_app_projects
    ovui-data-adapters/dist/common
    ovui-data-adapters/dist/services
    ovui-data-adapters/dist/${OMNIUI_OVRTX_UI_APP_PROVIDER}
    ovui-widgets/dist/common
    ovui-widgets/dist/content
    ovui-widgets/dist/stage
    ovui-widgets/dist/layers
    ovui-widgets/dist/property
    ovui-widgets/dist/viewport
    ovui-widgets/dist/app
)
# Optional development packages (repository-relative project folders) and
# Python roots that the generated environment also installs and uses.
set(OMNIUI_OVRTX_UI_APP_EXTRA_PROJECTS "" CACHE STRING "Additional local projects to install into the ovrtx_ui_app environment")
set(OMNIUI_OVRTX_UI_APP_EXTRA_PYTHONPATH "" CACHE STRING "Additional PYTHONPATH entries for ovrtx_ui_app")
set(OMNIUI_OVRTX_UI_APP_EXTRA_ENVIRONMENT "" CACHE STRING "Additional NAME=VALUE debugger environment entries for ovrtx_ui_app")
list(APPEND _app_projects ${OMNIUI_OVRTX_UI_APP_EXTRA_PROJECTS})
foreach(_path IN LISTS OMNIUI_OVRTX_UI_APP_EXTRA_PYTHONPATH)
    string(APPEND _app_pythonpath ";${_path}")
endforeach()
set(_app_metadata_inputs "${_repo_root}/VERSION.md" "${CMAKE_SOURCE_DIR}/setup.py" "${CMAKE_SOURCE_DIR}/pyproject.toml")
foreach(_project IN LISTS _app_projects)
    list(APPEND _app_metadata_inputs "${_repo_root}/${_project}/pyproject.toml" "${_repo_root}/${_project}/setup.py")
endforeach()

# A package with a native part needs the ovui SDK and the folder that holds
# the built ovui libraries. This build makes both in place, so stage the SDK
# here and give the environment their paths.
# The SDK's CMake package expects the shared libraries one folder above it,
# the same as inside an installed ovui wheel. Stage that shape.
set(_app_sdk_root "${_app_dir}/sdk-root")
set(_app_sdk_dir "${_app_sdk_root}/sdk")
add_custom_command(
    OUTPUT "${_app_dir}/venv/ready.stamp"
    COMMAND "${CMAKE_COMMAND}" -E rm -rf "${_app_sdk_root}"
    COMMAND "${CMAKE_COMMAND}" --install "${CMAKE_BINARY_DIR}"
        --component ovui-sdk --prefix "${_app_sdk_dir}" --config $<CONFIG>
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "$<TARGET_FILE:ovui>" "$<TARGET_FILE:imgui>" "${_app_sdk_root}"
    COMMAND "${Python_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/prepare_environment.py"
        --repo "${_repo_root}" --environment "${_app_dir}/venv"
        --build-env "OVUI_SDK_DIR=${_app_sdk_dir}"
        --build-env "OVUI_UI_DIR=$<TARGET_FILE_DIR:_ui>"
        --require-renderer-factory "${OMNIUI_OVRTX_UI_APP_PROVIDER}"
        ${_app_projects}
    COMMAND "${CMAKE_COMMAND}" -E touch "${_app_dir}/venv/ready.stamp"
    DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/prepare_environment.py" "${CMAKE_CURRENT_SOURCE_DIR}/CMakeLists.txt"
        ${_app_metadata_inputs}
    COMMENT "Preparing the ovrtx_ui_app Python environment and provider registrations"
    VERBATIM
)
add_custom_target(ovrtx_ui_app ALL DEPENDS "${_app_dir}/venv/ready.stamp")
add_dependencies(ovrtx_ui_app _ui _standalone _scene ovui imgui)

set(_app_environment
"PYTHONPATH=${_app_pythonpath}
PYTHONNOUSERSITE=1
PATH=${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR};${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR}/plugins;${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR}/plugins/rtx;$(Path)
KIT_ROOT=${_kit_root}
OVRTX_ROOT=${_ovrtx_public}
OVRTX_BIN_DIR=${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR}
OVRTX_LIBRARY_PATH_HINT=${OMNIUI_OVRTX_UI_APP_RUNTIME_DIR}
OVUI_DATA_ADAPTER_PROVIDER=${OMNIUI_OVRTX_UI_APP_PROVIDER}
OVUI_WIDGETS_REQUIRE_OVRTX=1
OVRTX_SKIP_USD_CHECK=1")
if(CUDAToolkit_FOUND)
    string(APPEND _app_environment "\nCUDA_PATH=${CUDAToolkit_LIBRARY_ROOT}")
endif()
foreach(_entry IN LISTS OMNIUI_OVRTX_UI_APP_EXTRA_ENVIRONMENT)
    string(APPEND _app_environment "\n${_entry}")
endforeach()
set_target_properties(ovrtx_ui_app PROPERTIES
    VS_DEBUGGER_COMMAND "${_app_python}"
    VS_DEBUGGER_COMMAND_ARGUMENTS "-m ovui_widgets.app ${OMNIUI_OVRTX_UI_APP_ARGUMENTS}"
    VS_DEBUGGER_WORKING_DIRECTORY "${_repo_root}"
    VS_DEBUGGER_ENVIRONMENT "${_app_environment}"
    VS_DEBUGGER_FLAVOR WindowsLocalDebugger
)
