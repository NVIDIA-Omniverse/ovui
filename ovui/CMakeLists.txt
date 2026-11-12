# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.22)

# Allow FetchContent'd projects that specify old cmake_minimum_required
# (e.g. Freetype 2.13) to configure under CMake 4.x without error.
if(CMAKE_VERSION VERSION_GREATER_EQUAL "4.0")
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5 CACHE STRING "" FORCE)
endif()

project(ovui VERSION 0.1.1 LANGUAGES C CXX)

# macOS: the bundled GLFW Cocoa sources need the Objective-C languages,
# enabled here in the common parent of every target.
if(APPLE)
    enable_language(OBJC OBJCXX)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

enable_testing()

include(FetchContent)

# Folder that contains the vendored `imgui/` tree. ovui keeps it in
# third_party/; a host monorepo may keep the single ImGui copy elsewhere.
set(OVUI_IMGUI_ROOT "${CMAKE_SOURCE_DIR}/third_party" CACHE PATH "Directory containing the imgui/ source tree")
option(OMNIUI_USE_BUNDLED_FREETYPE "Build the pinned FetchContent FreeType as a static library" OFF)
option(OMNIUI_USE_BUNDLED_GLFW "Build the pinned FetchContent GLFW as a static library" OFF)
option(OMNIUI_REQUIRE_VULKAN "Fail configuration when the Vulkan SDK is unavailable" OFF)
option(OMNIUI_ENABLE_SVG "Build the standalone SVG reader and painter so that ui.ImageWithProvider can draw .svg files" ON)
option(OMNIUI_REQUIRE_CUDA "Fail configuration when the CUDA Toolkit is unavailable" OFF)

# The bundled dependency mode is used by binary-wheel builds. Both upstream
# projects honor BUILD_SHARED_LIBS, and GLFW also exposes an explicit library
# type override. ovui's own native libraries declare SHARED directly, so this
# does not change their linkage type.
if(OMNIUI_USE_BUNDLED_FREETYPE OR OMNIUI_USE_BUNDLED_GLFW)
    set(BUILD_SHARED_LIBS OFF CACHE BOOL "Build dependencies as static libraries" FORCE)
endif()

# --- FreeType: try system, fall back to FetchContent ---
if(NOT OMNIUI_USE_BUNDLED_FREETYPE)
    find_package(Freetype QUIET)
endif()
if(OMNIUI_USE_BUNDLED_FREETYPE OR (NOT Freetype_FOUND AND NOT FREETYPE_FOUND))
    message(STATUS "Using bundled static FreeType 2.13.2")
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
    get_target_property(_omniui_freetype_type freetype TYPE)
    if(NOT _omniui_freetype_type STREQUAL "STATIC_LIBRARY")
        message(FATAL_ERROR "Bundled FreeType must be static, got ${_omniui_freetype_type}")
    endif()
endif()

option(OMNIUI_HEADLESS_ONLY "Build only headless Vulkan support (no GLFW/OpenGL required)" OFF)
option(OMNI_UI_BUILD_PYODIDE_BINDINGS "Removed legacy browser side-module build option; enabling this is a fatal error" OFF)
option(OMNI_UI_BUILD_WEB_RUNTIME "Build the browser WebAssembly app with embedded CPython" OFF)

# --- GLFW: try system; FetchContent fallback only for non-headless-only builds ---
if(NOT EMSCRIPTEN)
    if(NOT OMNIUI_USE_BUNDLED_GLFW)
        find_package(glfw3 3.3 QUIET)
    endif()
    if(OMNIUI_USE_BUNDLED_GLFW OR NOT glfw3_FOUND)
        if(NOT OMNIUI_HEADLESS_ONLY)
            message(STATUS "Using bundled static GLFW 3.4")
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
            set(GLFW_LIBRARY_TYPE STATIC CACHE STRING "" FORCE)
            FetchContent_MakeAvailable(glfw)
            get_target_property(_omniui_glfw_type glfw TYPE)
            if(NOT _omniui_glfw_type STREQUAL "STATIC_LIBRARY")
                message(FATAL_ERROR "Bundled GLFW must be static, got ${_omniui_glfw_type}")
            endif()
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
if(OMNIUI_REQUIRE_VULKAN AND NOT Vulkan_FOUND)
    message(FATAL_ERROR "OMNIUI_REQUIRE_VULKAN=ON but the Vulkan SDK was not found")
endif()
if(OMNIUI_REQUIRE_CUDA AND NOT CUDAToolkit_FOUND)
    message(FATAL_ERROR "OMNIUI_REQUIRE_CUDA=ON but the CUDA Toolkit was not found")
endif()
if(NOT (EMSCRIPTEN AND (OMNI_UI_BUILD_PYODIDE_BINDINGS OR OMNI_UI_BUILD_WEB_RUNTIME)))
    find_package(pybind11 2.11.1 CONFIG QUIET)
endif()
if(MSVC)
    # pybind11 2.13.6, unlike 2.11.1, adds the compiler version to the key of the shared type registry on Windows.
    # Without it the key is the one of pybind11 2.11.1 (Kit's), so the modules share types with Kit's, as on Linux.
    add_compile_definitions("PYBIND11_BUILD_ABI=\"\"")
endif()
if(CUDAToolkit_FOUND)
    message(STATUS "CUDA Toolkit ${CUDAToolkit_VERSION} found at ${CUDAToolkit_TARGET_DIR}")
else()
    message(STATUS "CUDA Toolkit not found - CUDA-Vulkan interop disabled (omni.ui.has_gpu_byte_image() will be False)")
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

include(cmake/SharedRpath.cmake)

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

option(OMNI_UI_BUILD_IMAGE_PROVIDER_TESTS "Build native image provider contract tests" ON)
if(OMNI_UI_BUILD_IMAGE_PROVIDER_TESTS)
    # Drives RasterImageProvider against a fake loader: no GPU, window or
    # filesystem, so every load outcome (including the asynchronous failure the
    # synchronous standalone loader cannot produce) is reachable and deterministic.
    add_executable(raster_image_provider_contract_tests
        tests/cpp/test_raster_image_provider_contract.cpp
    )
    target_include_directories(raster_image_provider_contract_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    target_link_libraries(raster_image_provider_contract_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(raster_image_provider_contract_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME raster_image_provider_contract_tests COMMAND raster_image_provider_contract_tests)

    # Upload results of ByteImageProvider against a fake backend: rejected and
    # stale uploads, device masks, completion events and the failure hook.
    add_executable(byte_image_upload_status_tests
        tests/cpp/test_byte_image_upload_status.cpp
    )
    target_include_directories(byte_image_upload_status_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    target_link_libraries(byte_image_upload_status_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(byte_image_upload_status_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME byte_image_upload_status_tests COMMAND byte_image_upload_status_tests)

    # Drives presentation-key mode of ImageProvider with a fake renderer and a
    # fake byte-image GPU: failed and good key entry, the exit from key mode,
    # byte-upload transitions, independent feeds and the draw-side guard.
    add_executable(presentation_key_tests
        tests/cpp/test_presentation_key_modes.cpp
    )
    target_include_directories(presentation_key_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
            ${OVUI_IMGUI_ROOT}/imgui
    )
    target_link_libraries(presentation_key_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(presentation_key_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME presentation_key_tests COMMAND presentation_key_tests)

    # A ui::Window and its callback with a fake window callback manager whose app
    # window lookup can fail: a failed move keeps the callback's app window, and
    # a callback is removed after its set lost its app window. No GPU or window.
    add_executable(window_callback_owner_tests
        tests/cpp/test_window_callback_owner.cpp
    )
    target_link_libraries(window_callback_owner_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(window_callback_owner_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME window_callback_owner_tests COMMAND window_callback_owner_tests)

    # Thread rules of ImageProvider: changes given from another thread run on
    # the UI thread, and a changing call on another thread is reported.
    add_executable(image_provider_thread_tests
        tests/cpp/test_image_provider_threads.cpp
    )
    target_include_directories(image_provider_thread_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    find_package(Threads REQUIRED)
    target_link_libraries(image_provider_thread_tests PRIVATE ovui Threads::Threads)
    if(NOT MSVC)
        target_compile_options(image_provider_thread_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME image_provider_thread_tests COMMAND image_provider_thread_tests)

    # Drives the standalone loader's sharing contract with the loader source
    # compiled in and a counting fake IByteImageGpu: several consumers of one
    # file share one upload, closing one of them keeps that sharing, and a
    # reload still reads the replaced file. No GPU or window is involved.
    add_executable(standalone_raster_image_loader_tests
        tests/cpp/test_standalone_raster_image_loader.cpp
        standalone/src/StandaloneRasterImageLoader.cpp
    )
    target_include_directories(standalone_raster_image_loader_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    target_link_libraries(standalone_raster_image_loader_tests PRIVATE ovui stb)
    if(NOT MSVC)
        target_compile_options(standalone_raster_image_loader_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME standalone_raster_image_loader_tests COMMAND standalone_raster_image_loader_tests)

    # PNG export compresses with the standalone pngZlibCompress instead of
    # stb_image_write's built-in compressor. This compares both byte for byte,
    # with the pinned stb compiled in as the reference, and checks that the
    # export one is faster and holds no more memory. CPU only.
    add_executable(png_zlib_compress_tests
        tests/cpp/test_png_zlib_compress.cpp
        standalone/src/PngZlibCompress.cpp
    )
    target_link_libraries(png_zlib_compress_tests PRIVATE stb)
    if(NOT MSVC)
        target_compile_options(png_zlib_compress_tests PRIVATE -Wno-error)
    endif()
    if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        # The memory check counts what each compressor asks the allocator for.
        # --wrap is a GNU ld and lld option, so the count is compiled in where
        # the native tests run; elsewhere the test says that it is not counting.
        target_compile_definitions(png_zlib_compress_tests PRIVATE OMNIUI_PNG_TEST_COUNT_ALLOCATIONS=1)
        # -fno-builtin-*: an optimizing build calls the compiler's own malloc,
        # which --wrap does not see.
        target_compile_options(png_zlib_compress_tests PRIVATE
            -fno-builtin-malloc -fno-builtin-calloc -fno-builtin-realloc -fno-builtin-free)
        target_link_options(png_zlib_compress_tests PRIVATE
            -Wl,--wrap=malloc -Wl,--wrap=calloc -Wl,--wrap=realloc -Wl,--wrap=free)
    endif()

    add_test(NAME png_zlib_compress_tests COMMAND png_zlib_compress_tests)

    # Drives the standalone file IO's asynchronous reads with its source
    # compiled in: destroying it waits for a running read, and a failed read
    # reports the cause. No GPU, window or running application is involved.
    add_executable(standalone_file_io_tests
        tests/cpp/test_standalone_file_io.cpp
        standalone/src/StandaloneFileIO.cpp
    )
    target_include_directories(standalone_file_io_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    target_link_libraries(standalone_file_io_tests PRIVATE ovui stb ${CMAKE_DL_LIBS})
    # Compiles a test-only seam into this binary that arms a one-shot read
    # failure; the product library is built without it.
    target_compile_definitions(standalone_file_io_tests PRIVATE OVUI_FILE_IO_TEST_SEAM)
    if(NOT MSVC)
        target_compile_options(standalone_file_io_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME standalone_file_io_tests COMMAND standalone_file_io_tests)

    # Drives VectorImageProvider with the standalone SVG rasterizer compiled in
    # (when OMNIUI_ENABLE_SVG is ON) and a counting fake IByteImageGpu: the SVG
    # is drawn with the right pixels, textures are shared and freed, and a bad
    # file is logged once. The ui.Image backend must share the texture of an
    # .svg file with VectorImageProvider. It also paints each file of
    # tests/svg_corpus and compares the pixels with the picture that Google
    # Chrome made of the same
    # file (tests/svg_corpus/chrome/). In both builds it checks the rasterizer
    # that `init` registers with the option OFF: a provider has no image, and
    # each URL logs one error that names the option. Files that multiply work
    # (entities, <use>, selectors, style rules, gradient stops, nesting, layers,
    # curves) must be refused with their limit within a time and memory bound.
    # No GPU or window is involved.
    set(_svg_test_sources
        tests/cpp/test_standalone_svg_rasterizer.cpp
        standalone/src/StandaloneSvgOffRasterizer.cpp
    )
    if(OMNIUI_ENABLE_SVG)
        list(APPEND _svg_test_sources
            standalone/src/StandaloneSvgRasterizer.cpp
            standalone/src/StandaloneSvgDocument.cpp
            standalone/src/StandaloneSvgRender.cpp
            standalone/src/StandaloneImageBackend.cpp
            standalone/src/StandaloneRasterImageLoader.cpp
        )
    endif()
    add_executable(standalone_svg_rasterizer_tests ${_svg_test_sources})
    target_include_directories(standalone_svg_rasterizer_tests
        PRIVATE
            ${CMAKE_SOURCE_DIR}/core/src
    )
    target_link_libraries(standalone_svg_rasterizer_tests PRIVATE ovui stb)
    # OVUI_SVG_TEST_SEAM compiles a test-only seam into this binary that makes
    # the next SVG read throw (std::bad_alloc or another exception), so that
    # the catch in the rasterizer is tested; the product library is built
    # without it.
    target_compile_definitions(standalone_svg_rasterizer_tests PRIVATE
        OVUI_SVG_CORPUS_DIR="${CMAKE_SOURCE_DIR}/tests/svg_corpus"
        OVUI_SVG_TEST_SEAM)
    if(OMNIUI_ENABLE_SVG)
        target_compile_definitions(standalone_svg_rasterizer_tests PRIVATE OMNIUI_HAS_SVG=1)
        target_include_directories(standalone_svg_rasterizer_tests PRIVATE
            ${CMAKE_SOURCE_DIR}/standalone/src)
    endif()
    if(NOT MSVC)
        target_compile_options(standalone_svg_rasterizer_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME standalone_svg_rasterizer_tests COMMAND standalone_svg_rasterizer_tests)
endif()
option(OMNI_UI_BUILD_OPENGL3_RENDERER_TESTS "Build the native ImGui OpenGL3 renderer upload tests" ON)
if(OMNI_UI_BUILD_OPENGL3_RENDERER_TESTS AND NOT EMSCRIPTEN)
    # Runs the vendored ImGui OpenGL3 renderer against fake OpenGL entry points
    # (its imgl3w table): no GPU, window or driver. Checks one vertex and one
    # index upload for each frame and the draw offsets.
    add_executable(opengl3_renderer_upload_tests
        tests/cpp/test_opengl3_renderer_upload.cpp
        ${OVUI_IMGUI_ROOT}/imgui/backends/imgui_impl_opengl3.cpp
    )
    target_include_directories(opengl3_renderer_upload_tests
        PRIVATE
            ${OVUI_IMGUI_ROOT}/imgui
            ${OVUI_IMGUI_ROOT}/imgui/backends
    )
    target_link_libraries(opengl3_renderer_upload_tests PRIVATE imgui ${CMAKE_DL_LIBS})
    if(NOT MSVC)
        target_compile_options(opengl3_renderer_upload_tests PRIVATE -Wno-error)
    endif()
    add_test(NAME opengl3_renderer_upload_tests COMMAND opengl3_renderer_upload_tests)
endif()

option(OMNI_UI_BUILD_RASTER_CONTRACT_TESTS "Build native raster-invalidation contract tests" ON)
if(OMNI_UI_BUILD_RASTER_CONTRACT_TESTS)
    # Counts the invalidations that reach a probe frame when a multi-field's model changes. Widgets lay
    # themselves out with an ImGui context and its default font; nothing is drawn, no window or GPU.
    add_executable(multifield_raster_contract_tests
        tests/cpp/test_multifield_raster_contract.cpp
    )
    target_link_libraries(multifield_raster_contract_tests PRIVATE ovui)
    if(NOT MSVC)
        target_compile_options(multifield_raster_contract_tests PRIVATE -Wno-error)
    endif()

    add_test(NAME multifield_raster_contract_tests COMMAND multifield_raster_contract_tests)
endif()

option(OMNI_UI_BUILD_WORKSPACE_TESTS "Build native Workspace callback tests" ON)
if(OMNI_UI_BUILD_WORKSPACE_TESTS)
    # A first-interaction callback that unregisters or replaces itself while it runs.
    add_executable(workspace_first_interaction_tests
        tests/cpp/test_workspace_first_interaction.cpp
    )
    target_link_libraries(workspace_first_interaction_tests PRIVATE ovui)

    add_test(NAME workspace_first_interaction_tests COMMAND workspace_first_interaction_tests)
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

# Native wheel consumers need the exact headers and link files used above.
if(NOT EMSCRIPTEN)
    include(cmake/WheelSdk.cmake)
endif()
