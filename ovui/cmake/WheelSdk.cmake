# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
# Keep the SDK beside the wheel libraries. Install the headers from the actual
# configured dependency trees, including FetchContent source overrides.
install(DIRECTORY "${CMAKE_SOURCE_DIR}/core/include/" DESTINATION include
    COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp")
install(DIRECTORY "${CMAKE_SOURCE_DIR}/core/src/" DESTINATION src
    COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp")
install(DIRECTORY "${OVUI_IMGUI_ROOT}/imgui/" DESTINATION third_party/imgui
    COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h")

FetchContent_GetProperties(glm)
FetchContent_GetProperties(boost_preprocessor)
install(DIRECTORY "${glm_SOURCE_DIR}/glm" DESTINATION third_party
    COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp" PATTERN "*.inl")
install(DIRECTORY "${boost_preprocessor_SOURCE_DIR}/include/boost" DESTINATION third_party
    COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h" PATTERN "*.hpp")
if(pybind11_FOUND)
    find_path(OVUI_SDK_PYBIND11_INCLUDE pybind11/pybind11.h
        PATHS ${pybind11_INCLUDE_DIRS} NO_DEFAULT_PATH NO_CMAKE_FIND_ROOT_PATH REQUIRED)
    install(DIRECTORY "${OVUI_SDK_PYBIND11_INCLUDE}/pybind11" DESTINATION third_party
        COMPONENT ovui-sdk FILES_MATCHING PATTERN "*.h")
endif()

install(FILES "${CMAKE_SOURCE_DIR}/../LICENSE" "${CMAKE_SOURCE_DIR}/../THIRD_PARTY_NOTICES.md"
    DESTINATION licenses COMPONENT ovui-sdk)
if(WIN32)
    # DLLs are already staged by setup.py; native consumers also need the
    # import libraries produced by this exact build/configuration.
    install(FILES "$<TARGET_LINKER_FILE:ovui>" "$<TARGET_LINKER_FILE:ovui_forwarders>" "$<TARGET_LINKER_FILE:ovuiscene>" "$<TARGET_LINKER_FILE:imgui>"
        DESTINATION lib COMPONENT ovui-sdk)
endif()

file(GENERATE OUTPUT "${CMAKE_BINARY_DIR}/sdk-build-$<CONFIG>.json" CONTENT
"{\n  \"configuration\": \"$<CONFIG>\",\n  \"compiler_id\": \"${CMAKE_CXX_COMPILER_ID}\",\n  \"compiler_version\": \"${CMAKE_CXX_COMPILER_VERSION}\",\n  \"cxx_standard\": ${CMAKE_CXX_STANDARD},\n  \"pybind11_version\": \"${pybind11_VERSION}\",\n  \"core_library\": \"$<TARGET_FILE_NAME:ovui>\",\n  \"imgui_library\": \"$<TARGET_FILE_NAME:imgui>\",\n  \"scene_library\": \"$<TARGET_FILE_NAME:ovuiscene>\"\n}\n")
install(FILES "${CMAKE_BINARY_DIR}/sdk-build-$<CONFIG>.json"
    DESTINATION . RENAME build.json COMPONENT ovui-sdk)
install(FILES "${CMAKE_CURRENT_LIST_DIR}/ovui-sdk-config.cmake"
    DESTINATION cmake COMPONENT ovui-sdk)
