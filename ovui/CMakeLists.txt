cmake_minimum_required(VERSION 3.22)

# Allow FetchContent'd projects that specify old cmake_minimum_required
# (e.g. Freetype 2.13) to configure under CMake 4.x without error.
if(CMAKE_VERSION VERSION_GREATER_EQUAL "4.0")
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "" FORCE)
endif()

project(ovui VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

enable_testing()

include(FetchContent)

# --- Freetype: try system, fall back to FetchContent ---
find_package(Freetype QUIET)
if(NOT Freetype_FOUND AND NOT FREETYPE_FOUND)
    message(STATUS "Freetype not found on system - downloading via FetchContent")
    FetchContent_Declare(
        freetype
        GIT_REPOSITORY https://github.com/freetype/freetype.git
        GIT_TAG        VER-2-13-2
        GIT_SHALLOW    TRUE
    )
    set(FT_DISABLE_ZLIB ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_BZIP2 ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_PNG ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_HARFBUZZ ON CACHE BOOL "" FORCE)
    set(FT_DISABLE_BROTLI ON CACHE BOOL "" FORCE)
    FetchContent_MakeAvailable(freetype)
    # Create Freetype::Freetype alias if not already defined
    if(NOT TARGET Freetype::Freetype)
        add_library(Freetype::Freetype ALIAS freetype)
    endif()
endif()

option(OMNIUI_HEADLESS_ONLY "Build only headless Vulkan support (no GLFW/OpenGL required)" OFF)
option(OMNI_UI_BUILD_PYODIDE_BINDINGS "Removed legacy browser side-module build option; enabling this is a fatal error" OFF)
option(OMNI_UI_BUILD_WEB_RUNTIME "Build the browser WebAssembly app with embedded CPython" OFF)

# --- GLFW: try system; FetchContent fallback only for non-headless-only builds ---
if(NOT EMSCRIPTEN)
    find_package(glfw3 3.3 QUIET)
    if(NOT glfw3_FOUND)
        if(NOT OMNIUI_HEADLESS_ONLY)
            message(STATUS "GLFW3 not found on system - downloading via FetchContent")
            FetchContent_Declare(
                glfw
                GIT_REPOSITORY https://github.com/glfw/glfw.git
                GIT_TAG        3.4
                GIT_SHALLOW    TRUE
            )
            set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
            set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
            set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
            set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
            FetchContent_MakeAvailable(glfw)
            set(glfw3_FOUND TRUE)
        else()
            message(STATUS "GLFW3 not found - skipped (OMNIUI_HEADLESS_ONLY=ON)")
        endif()
    endif()
endif()

if(NOT EMSCRIPTEN)
    find_package(OpenGL QUIET)
    find_package(Vulkan QUIET)
    find_package(CUDAToolkit QUIET)
endif()
if(NOT (EMSCRIPTEN AND (OMNI_UI_BUILD_PYODIDE_BINDINGS OR OMNI_UI_BUILD_WEB_RUNTIME)))
    find_package(pybind11 QUIET)
endif()
if(CUDAToolkit_FOUND)
    message(STATUS "CUDA Toolkit ${CUDAToolkit_VERSION} found at ${CUDAToolkit_TARGET_DIR}")
else()
    message(STATUS "CUDA Toolkit not found - CUDA-Vulkan interop will be disabled")
    if(WIN32 AND Vulkan_FOUND)
        message(WARNING
            "CUDA Toolkit was not found, so ovui will build without CUDA-Vulkan "
            "byte-image support. Windows source builds that need "
            "omni.ui.has_gpu_byte_image() or examples/byte_image_gpu_demo.py "
            "must install NVIDIA CUDA Toolkit before configuring/installing ovui. "
            "See ovui/README.md, Windows 11 / Windows Server 2022 section."
        )
    endif()
endif()

add_subdirectory(third_party)
add_subdirectory(core)

option(OMNI_UI_BUILD_MARKDOWN_TESTS "Build native MarkdownWidget model tests" ON)
if(OMNI_UI_BUILD_MARKDOWN_TESTS)
    add_executable(markdown_model_tests
        tests/cpp/test_markdown_model.cpp
    )
    target_include_directories(markdown_model_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
            $<TARGET_PROPERTY:md4c,INTERFACE_INCLUDE_DIRECTORIES>
    )
    target_link_libraries(markdown_model_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(markdown_model_tests PRIVATE -fpermissive -Wno-error)
    endif()

    add_executable(markdown_fuzz_tests
        tests/cpp/test_markdown_fuzz.cpp
    )
    target_include_directories(markdown_fuzz_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
            $<TARGET_PROPERTY:md4c,INTERFACE_INCLUDE_DIRECTORIES>
    )
    target_link_libraries(markdown_fuzz_tests PRIVATE ovui)
    # Allow fuzz runner to locate the in-tree corpus when invoked from the
    # build directory without having to set environment variables.
    target_compile_definitions(markdown_fuzz_tests PRIVATE
        OMNI_UI_MARKDOWN_FUZZ_CORPUS_DEFAULT=\"${CMAKE_SOURCE_DIR}/tests/markdown_fuzz_corpus\"
    )
    if(NOT MSVC)
        target_compile_options(markdown_fuzz_tests PRIVATE -fpermissive -Wno-error)
    endif()

    add_test(NAME markdown_model_tests COMMAND markdown_model_tests)
    add_test(NAME markdown_fuzz_tests COMMAND markdown_fuzz_tests)
endif()

if(EMSCRIPTEN AND OMNI_UI_BUILD_WEB_RUNTIME)
    add_subdirectory(web/runtime)
elseif(EMSCRIPTEN AND OMNI_UI_BUILD_PYODIDE_BINDINGS)
    message(FATAL_ERROR "OMNI_UI_BUILD_PYODIDE_BINDINGS has been removed from the shipped browser runtime; use OMNI_UI_BUILD_WEB_RUNTIME")
elseif(OMNIUI_HEADLESS_ONLY AND Vulkan_FOUND)
    # Headless-only: only need Vulkan, GLFW is optional
    add_subdirectory(standalone)
elseif(glfw3_FOUND AND OpenGL_FOUND)
    add_subdirectory(standalone)
else()
    message(WARNING "GLFW3 or OpenGL not found - standalone backend skipped. "
                    "Use -DOMNIUI_HEADLESS_ONLY=ON for headless Vulkan without GLFW.")
endif()

if(EMSCRIPTEN AND OMNI_UI_BUILD_WEB_RUNTIME)
    # The web runtime builds the bindings into the Emscripten application.
elseif(EMSCRIPTEN AND OMNI_UI_BUILD_PYODIDE_BINDINGS)
    # Fatal above.
elseif(pybind11_FOUND)
    add_subdirectory(bindings)
else()
    message(WARNING "pybind11 not found - Python bindings skipped")
endif()

if(glfw3_FOUND AND OpenGL_FOUND)
    add_subdirectory(benchmarks)
endif()
