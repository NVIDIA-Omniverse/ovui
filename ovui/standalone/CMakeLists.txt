# ==============================================================================
# standalone/CMakeLists.txt - libomniui_standalone.so
# ==============================================================================

option(OMNIUI_HEADLESS_ONLY "Build only headless Vulkan support (no GLFW/OpenGL required)" OFF)
option(OMNIUI_HEADLESS_GL "Build EGL surfaceless headless OpenGL support" OFF)

if(NOT OMNIUI_HEADLESS_ONLY)
    find_package(OpenGL REQUIRED)
endif()
find_package(Vulkan QUIET)

# GLFW is optional when building headless-only
if(NOT OMNIUI_HEADLESS_ONLY)
    if(NOT TARGET glfw)
        find_package(glfw3 3.3 QUIET)
        if(NOT glfw3_FOUND)
            find_package(PkgConfig QUIET)
            if(PkgConfig_FOUND)
                pkg_check_modules(GLFW3 QUIET glfw3)
            endif()
        endif()
    else()
        set(glfw3_FOUND TRUE)
    endif()
endif()

# ImGui backend sources (GLFW + OpenGL3)
set(IMGUI_BACKEND_DIR ${CMAKE_SOURCE_DIR}/third_party/imgui/backends)

set(STANDALONE_SOURCES
    src/StandaloneSettings.cpp
    src/StandaloneFileIO.cpp
    src/OpenGLRenderer.cpp
    src/OpenGLByteImageGpu.cpp
    src/StandaloneRasterImageLoader.cpp
    src/GlfwPlatform.cpp
    src/StandaloneGlyphManager.cpp
    src/StandaloneInit.cpp
    src/StandaloneWindowCallbackManager.cpp
    ${IMGUI_BACKEND_DIR}/imgui_impl_glfw.cpp
    ${IMGUI_BACKEND_DIR}/imgui_impl_opengl3.cpp
)

# Vulkan backend sources (conditional)
if(Vulkan_FOUND)
    list(APPEND STANDALONE_SOURCES
        src/VulkanBackend.cpp
        src/VulkanByteImageGpu.cpp
        src/StreamingVulkan.cpp
        src/HeadlessVulkanPlatform.cpp
        ${IMGUI_BACKEND_DIR}/imgui_impl_vulkan.cpp
    )
    message(STATUS "Vulkan found - enabling Vulkan backend + streaming + headless")
else()
    message(STATUS "Vulkan not found - Vulkan backend disabled")
endif()

# CUDA-Vulkan interop (conditional -- requires both Vulkan and CUDA)
if(Vulkan_FOUND AND CUDAToolkit_FOUND)
    list(APPEND STANDALONE_SOURCES src/CudaVulkanInterop.cpp)
    message(STATUS "CUDA + Vulkan found - enabling CUDA-Vulkan interop")
endif()

# ---------------------------------------------------------------------------
# NVENC (Video Codec SDK) — optional hardware encoder
# ---------------------------------------------------------------------------
set(OMNIUI_HAS_NVENC OFF)
if(Vulkan_FOUND)
    # Allow user to specify Video_Codec_SDK_DIR
    find_path(NVENC_INCLUDE_DIR nvEncodeAPI.h
        HINTS
            ${Video_Codec_SDK_DIR}/Interface
            ${Video_Codec_SDK_DIR}/include
            $ENV{Video_Codec_SDK_DIR}/Interface
            $ENV{Video_Codec_SDK_DIR}/include
            /usr/include
            /usr/local/include
            /opt/nvidia/video-codec-sdk/include
    )
    if(NVENC_INCLUDE_DIR)
        set(OMNIUI_HAS_NVENC ON)
        message(STATUS "NVENC found: ${NVENC_INCLUDE_DIR}")
    else()
        message(STATUS "NVENC not found — streaming will use CPU fallback encoder. "
                       "Set Video_Codec_SDK_DIR to enable hardware encoding.")
    endif()
endif()

# ---------------------------------------------------------------------------
# CUDA interop — optional zero-copy VkImage→CUDA path
# ---------------------------------------------------------------------------
set(OMNIUI_HAS_CUDA_INTEROP OFF)
if(Vulkan_FOUND)
    find_package(CUDAToolkit QUIET)
    if(CUDAToolkit_FOUND)
        set(OMNIUI_HAS_CUDA_INTEROP ON)
        message(STATUS "CUDA Toolkit found — enabling Vulkan-CUDA interop")
    else()
        message(STATUS "CUDA Toolkit not found — streaming will use CPU readback path")
    endif()
endif()

list(APPEND STANDALONE_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/src/scene/StandaloneWidget.cpp
)

add_library(omniui_standalone SHARED ${STANDALONE_SOURCES})

# StandaloneWidget.cpp must be compiled with OMNIUI_SCENE_EXPORTS so that the
# scene::Widget class typeinfo (RTTI) and vtable are exported with default
# visibility. Pybind11 requires them to be in the dynamic symbol table when
# _scene.so is loaded. The class is declared OMNIUI_SCENE_CLASS_API which
# expands to __attribute__((visibility("default"))) iff OMNIUI_SCENE_EXPORTS
# is defined, overriding the CXX_VISIBILITY_PRESET hidden on this library.
set_source_files_properties(
    ${CMAKE_CURRENT_SOURCE_DIR}/src/scene/StandaloneWidget.cpp
    PROPERTIES
    COMPILE_DEFINITIONS "OMNIUI_SCENE_EXPORTS"
)

# glad is provided by FetchContent (Dav1dde/glad@v0.1.36) as a STATIC library
target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_GLAD=1)

target_include_directories(omniui_standalone
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    PRIVATE
        ${CMAKE_SOURCE_DIR}/third_party/imgui/backends
        ${CMAKE_SOURCE_DIR}/third_party/imgui
        # Access to internal core headers (IRasterImageLoader etc.) which live
        # in core/src and are otherwise private to libovui.
        ${CMAKE_SOURCE_DIR}/core/src
)

# Inherit ovui's public includes (platform interfaces)
# Link ovuiscene so Widget stub symbols resolve and scene types are visible
target_link_libraries(omniui_standalone
    PUBLIC
        ovui
        ovuiscene
    PRIVATE
        glad
        OpenGL::GL
        stb
)
if(NOT WIN32)
    target_link_libraries(omniui_standalone PRIVATE ${CMAKE_DL_LIBS})
endif()

# Link GLFW (resolved via system libglfw3-dev; headless-only builds still need
# the headers/symbols because StandaloneInit.cpp includes GlfwPlatform.h)
if(glfw3_FOUND)
    target_link_libraries(omniui_standalone PRIVATE glfw)
elseif(GLFW3_FOUND)
    target_include_directories(omniui_standalone PRIVATE ${GLFW3_INCLUDE_DIRS})
    target_link_libraries(omniui_standalone PRIVATE ${GLFW3_LIBRARIES})
else()
    message(WARNING "GLFW3 not found - standalone backend will not build correctly. "
                    "Install libglfw3-dev or equivalent.")
endif()

# Vulkan support
if(Vulkan_FOUND)
    target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_VULKAN=1)
    target_include_directories(omniui_standalone PRIVATE ${Vulkan_INCLUDE_DIRS})
    target_link_libraries(omniui_standalone PRIVATE Vulkan::Vulkan)
endif()

# NVENC support (optional)
if(OMNIUI_HAS_NVENC)
    target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_NVENC=1)
    target_include_directories(omniui_standalone PRIVATE ${NVENC_INCLUDE_DIR})
    # NVENC is loaded dynamically (via NvEncodeAPICreateInstance), no link lib needed
    # on Linux; on Windows we'd link nvcuvid.lib / nvEncodeAPI.lib
    if(WIN32)
        find_library(NVENC_LIB nvEncodeAPI
            HINTS ${Video_Codec_SDK_DIR}/Lib/x64 $ENV{Video_Codec_SDK_DIR}/Lib/x64)
        if(NVENC_LIB)
            target_link_libraries(omniui_standalone PRIVATE ${NVENC_LIB})
        endif()
    endif()
endif()

# CUDA interop support (optional)
if(OMNIUI_HAS_CUDA_INTEROP)
    target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_CUDA_INTEROP=1)
    target_link_libraries(omniui_standalone PRIVATE CUDA::cuda_driver CUDA::cudart)
endif()

# ---------------------------------------------------------------------------
# EGL headless OpenGL support (OMNIUI_HEADLESS_GL — issue #24)
# All CMakeLists.txt if() guards use if(OMNIUI_HEADLESS_GL), not if(OMNIUI_HAS_EGL).
# OMNIUI_HAS_EGL=1 is a C++ compile definition only, not a CMake variable.
# ---------------------------------------------------------------------------
if(OMNIUI_HEADLESS_GL)
    find_package(OpenGL COMPONENTS EGL QUIET)
    if(OpenGL_EGL_FOUND)
        # push-state/pop-state bracket only EGL and restore whatever state was in effect before.
        target_link_libraries(omniui_standalone PRIVATE
            -Wl,--push-state,--no-as-needed OpenGL::EGL -Wl,--pop-state)
    else()
        find_package(PkgConfig QUIET)
        if(PkgConfig_FOUND)
            pkg_check_modules(EGL QUIET IMPORTED_TARGET egl)
        endif()
        if(TARGET PkgConfig::EGL)
            target_link_libraries(omniui_standalone PRIVATE
                -Wl,--push-state,--no-as-needed PkgConfig::EGL -Wl,--pop-state)
        else()
            message(FATAL_ERROR "OMNIUI_HEADLESS_GL=ON requires EGL. Install libegl1-mesa-dev.")
        endif()
    endif()
    target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_EGL=1)
    target_sources(omniui_standalone PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src/HeadlessEglPlatform.cpp)
    message(STATUS "OMNIUI_HAS_EGL: enabled")
endif()

# Optional CUDA support for streaming (CUDA-GL interop / NVENC zero-copy)
# Hint paths from environment (CUDA_PATH, CUDAToolkit_ROOT, CUDA_HOME)
list(APPEND CMAKE_PREFIX_PATH "$ENV{CUDA_PATH}" "$ENV{CUDAToolkit_ROOT}" "$ENV{CUDA_HOME}")
find_package(CUDAToolkit QUIET)
if(NOT CUDAToolkit_FOUND)
  # Try manual detection from common install locations
  find_path(CUDAToolkit_INCLUDE_DIR cuda_runtime.h
    HINTS "$ENV{CUDA_PATH}/include" "$ENV{CUDAToolkit_ROOT}/include" "$ENV{CUDA_HOME}/include"
          "/usr/local/cuda/include")
  find_library(CUDA_CUDART cudart
    HINTS "$ENV{CUDA_PATH}/lib64" "$ENV{CUDAToolkit_ROOT}/lib64" "$ENV{CUDA_HOME}/lib64"
          "/usr/local/cuda/lib64")
  if(CUDAToolkit_INCLUDE_DIR AND CUDA_CUDART)
    set(CUDAToolkit_FOUND TRUE)
    message(STATUS "CUDA found manually: ${CUDAToolkit_INCLUDE_DIR}")
  endif()
endif()
if(CUDAToolkit_FOUND)
    if(TARGET CUDA::cudart)
        target_link_libraries(omniui_standalone PRIVATE CUDA::cudart)
    else()
        target_include_directories(omniui_standalone PRIVATE ${CUDAToolkit_INCLUDE_DIR})
        target_link_libraries(omniui_standalone PRIVATE ${CUDA_CUDART})
    endif()
    target_compile_definitions(omniui_standalone PRIVATE OMNIUI_HAS_CUDA=1)
    message(STATUS "CUDA found (${CUDAToolkit_VERSION}) -- streaming CUDA-GL interop enabled")
else()
    message(STATUS "CUDA not found -- streaming will work without CUDA (GL texture only, no zero-copy)")
endif()

target_compile_definitions(omniui_standalone
    PRIVATE
        OMNIUI_STANDALONE_EXPORTS
        OMNIUI_STANDALONE
        IMGUI_NVIDIA
)

set_target_properties(omniui_standalone PROPERTIES
    OUTPUT_NAME omniui_standalone
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON
)
if(NOT WIN32)
    set_target_properties(omniui_standalone PROPERTIES
        VERSION ${PROJECT_VERSION}
        SOVERSION 3
    )
endif()
if(APPLE)
    set_target_properties(omniui_standalone PROPERTIES
        INSTALL_RPATH "@loader_path"
    )
elseif(NOT WIN32)
    set_target_properties(omniui_standalone PROPERTIES
        INSTALL_RPATH "$ORIGIN"
    )
endif()
if(WIN32)
    set_target_properties(omniui_standalone PROPERTIES
        WINDOWS_EXPORT_ALL_SYMBOLS OFF
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# ==============================================================================
# CUDA-Vulkan interop test executable (only when both Vulkan + CUDA are present)
# ==============================================================================
if(Vulkan_FOUND AND CUDAToolkit_FOUND)
    add_executable(cuda_interop_test
        tests/cuda_interop_test.cpp
        ${IMGUI_BACKEND_DIR}/imgui_impl_vulkan.cpp
    )
    target_compile_definitions(cuda_interop_test PRIVATE
        OMNIUI_HAS_VULKAN=1
        OMNIUI_HAS_CUDA=1
        IMGUI_NVIDIA
    )
    target_include_directories(cuda_interop_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/third_party/imgui/backends
        ${CMAKE_SOURCE_DIR}/third_party/imgui
    )
    target_link_libraries(cuda_interop_test PRIVATE
        omniui_standalone
        imgui
        Vulkan::Vulkan
        CUDA::cudart
        glfw
        stb
    )
    message(STATUS "CUDA interop test: cuda_interop_test target added")

    # ByteImageProvider fromGpu round-trip test — verifies the wiring added
    # for ovui#17 (CUDA dev pointer → VkImage via importVkImageMemoryToCuda).
    add_executable(byte_image_gpu_test
        tests/byte_image_gpu_test.cpp
    )
    target_compile_definitions(byte_image_gpu_test PRIVATE
        OMNIUI_HAS_VULKAN=1
        OMNIUI_HAS_CUDA=1
    )
    target_include_directories(byte_image_gpu_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )
    target_link_libraries(byte_image_gpu_test PRIVATE
        omniui_standalone
        Vulkan::Vulkan
        CUDA::cudart
    )
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(byte_image_gpu_test PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    message(STATUS "byte_image_gpu_test target added (ovui#17 helper-layer test)")

    # Dispatch-layer pixel-verifying test that goes through the public
    # ByteImageProvider::setBytesDataFromGPU API — ensures the actual
    # production caller works, not just the helper.
    add_executable(byte_image_gpu_dispatch_test
        tests/byte_image_gpu_dispatch_test.cpp
    )
    target_compile_definitions(byte_image_gpu_dispatch_test PRIVATE
        OMNIUI_HAS_VULKAN=1
        OMNIUI_HAS_CUDA=1
        IMGUI_NVIDIA
    )
    target_include_directories(byte_image_gpu_dispatch_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/third_party/imgui
    )
    target_link_libraries(byte_image_gpu_dispatch_test PRIVATE
        omniui_standalone
        ovui
        imgui
        Vulkan::Vulkan
        CUDA::cudart
    )
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(byte_image_gpu_dispatch_test PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    message(STATUS "byte_image_gpu_dispatch_test target added (ovui#17 dispatch-layer test)")

    # All-format pixel round-trip test — loops a 128x128 CUDA buffer
    # through every supported PixelFormat (8-bit + R/RG/RGB/RGBA float)
    # and verifies the bytes that come back out of the VkImage.
    add_executable(byte_image_gpu_format_test
        tests/byte_image_gpu_format_test.cpp
    )
    target_compile_definitions(byte_image_gpu_format_test PRIVATE
        OMNIUI_HAS_VULKAN=1
        OMNIUI_HAS_CUDA=1
        IMGUI_NVIDIA
    )
    target_include_directories(byte_image_gpu_format_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/third_party/imgui
    )
    target_link_libraries(byte_image_gpu_format_test PRIVATE
        omniui_standalone
        ovui
        imgui
        Vulkan::Vulkan
        CUDA::cudart
    )
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(byte_image_gpu_format_test PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    message(STATUS "byte_image_gpu_format_test target added (all-format fromGpu test)")

    # Register with CTest so headless CI runs them via `ctest`. All three
    # tests use VulkanBackend::initHeadless and need no DISPLAY.
    add_test(NAME byte_image_gpu_test COMMAND byte_image_gpu_test)
    add_test(NAME byte_image_gpu_dispatch_test COMMAND byte_image_gpu_dispatch_test)
    add_test(NAME byte_image_gpu_format_test COMMAND byte_image_gpu_format_test)
    set_tests_properties(byte_image_gpu_test byte_image_gpu_dispatch_test byte_image_gpu_format_test
        PROPERTIES TIMEOUT 120)

    # Headless linear-buffer export test — issue-34 Step 0.7. Renders a
    # checker pattern via VulkanBackend, imports it as a cudaArray_t,
    # copies the array into a caller-owned cudaMallocPitch buffer, and
    # verifies the result byte-for-byte against vk.readbackPixels.
    add_executable(test_headless_linear_export
        tests/test_headless_linear_export.cpp
    )
    target_compile_definitions(test_headless_linear_export PRIVATE
        OMNIUI_HAS_VULKAN=1
        OMNIUI_HAS_CUDA=1
    )
    target_include_directories(test_headless_linear_export PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )
    target_link_libraries(test_headless_linear_export PRIVATE
        omniui_standalone
        Vulkan::Vulkan
        CUDA::cudart
    )
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(test_headless_linear_export PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    add_test(NAME test_headless_linear_export COMMAND test_headless_linear_export)
    set_tests_properties(test_headless_linear_export PROPERTIES TIMEOUT 60)
    message(STATUS "test_headless_linear_export target added (issue-34 Step 0.7)")
endif()

# ---------------------------------------------------------------------------
# Vulkan streaming test executable
# ---------------------------------------------------------------------------
if(Vulkan_FOUND)
    add_executable(test_vulkan_streaming
        ${CMAKE_SOURCE_DIR}/tests/test_vulkan_streaming.cpp
    )
    target_link_libraries(test_vulkan_streaming PRIVATE omniui_standalone Vulkan::Vulkan)
    target_include_directories(test_vulkan_streaming PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
    )
    if(OMNIUI_HAS_NVENC)
        target_compile_definitions(test_vulkan_streaming PRIVATE OMNIUI_HAS_NVENC=1)
        target_include_directories(test_vulkan_streaming PRIVATE ${NVENC_INCLUDE_DIR})
    endif()
    if(OMNIUI_HAS_CUDA_INTEROP)
        target_compile_definitions(test_vulkan_streaming PRIVATE OMNIUI_HAS_CUDA_INTEROP=1)
    endif()
    set_target_properties(test_vulkan_streaming PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
    )
endif()

# ==============================================================================
# Headless Vulkan test executable
# ==============================================================================
if(Vulkan_FOUND)
    add_executable(headless_test src/headless_test.cpp)
    target_link_libraries(headless_test PRIVATE omniui_standalone Vulkan::Vulkan stb)
    target_include_directories(headless_test PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/third_party/imgui
        ${CMAKE_SOURCE_DIR}/third_party/imgui/backends
    )
    target_compile_definitions(headless_test PRIVATE OMNIUI_HAS_VULKAN=1)
    set_target_properties(headless_test PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    )
    if(APPLE)
        set_target_properties(headless_test PROPERTIES
            INSTALL_RPATH "@loader_path"
        )
    elseif(NOT WIN32)
        set_target_properties(headless_test PROPERTIES
            INSTALL_RPATH "$ORIGIN"
        )
    endif()
    message(STATUS "headless_test target added (DISPLAY= OMNIUI_HEADLESS=1 ./headless_test)")
    add_test(NAME headless_test
        COMMAND headless_test
        WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# ==============================================================================
# EGL headless unit test (only when OMNIUI_HEADLESS_GL is ON — issue #24 E2)
# ==============================================================================
if(OMNIUI_HEADLESS_GL)
    add_executable(test_egl_platform_unit tests/test_egl_platform_unit.cpp)
    target_link_libraries(test_egl_platform_unit PRIVATE omniui_standalone)
    target_compile_definitions(test_egl_platform_unit PRIVATE OMNIUI_HAS_EGL=1)
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(test_egl_platform_unit PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    add_test(NAME egl_platform_unit COMMAND test_egl_platform_unit)
    set_tests_properties(egl_platform_unit PROPERTIES
        WILL_FAIL FALSE
        ENVIRONMENT "OMNIUI_EGL_FORCE_SURFACELESS=1")
    message(STATUS "test_egl_platform_unit target added (WILL_FAIL=FALSE, surfaceless active)")

    # E7: screenshot error-contract test — scheduleScreenshot to an unwritable path
    # must set done=true + error=true without hanging.
    add_executable(test_egl_screenshot_error tests/test_egl_screenshot_error.cpp)
    target_link_libraries(test_egl_screenshot_error PRIVATE omniui_standalone)
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(test_egl_screenshot_error PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    add_test(NAME egl_screenshot_error COMMAND test_egl_screenshot_error)
    set_tests_properties(egl_screenshot_error PROPERTIES
        ENVIRONMENT "OMNIUI_HEADLESS=1;OMNIUI_HEADLESS_GL=1;OMNIUI_EGL_FORCE_SURFACELESS=1")
    message(STATUS "test_egl_screenshot_error target added (E7 error-contract test)")

    # E8: texture upload / readback test — verifies OpenGLByteImageGpu under EGL context.
    add_executable(test_egl_texture_upload
        tests/test_egl_texture_upload.cpp
        tests/test_utils.cpp)
    target_link_libraries(test_egl_texture_upload PRIVATE omniui_standalone glad)
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(test_egl_texture_upload PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    add_test(NAME egl_texture_upload COMMAND test_egl_texture_upload)
    set_tests_properties(egl_texture_upload PROPERTIES
        ENVIRONMENT "OMNIUI_HEADLESS=1;OMNIUI_HEADLESS_GL=1;OMNIUI_EGL_FORCE_SURFACELESS=1")
    message(STATUS "test_egl_texture_upload target added (E8 texture upload test)")

    # All-format fromGpu test for OpenGLByteImageGpu — loops a 128x128 CUDA
    # buffer through every supported PixelFormat (8-bit + R/RG/RGB/RGBA
    # float) across both direct-interop and PBO paths, verifying the bytes
    # that come back out of glGetTexImage.
    if(CUDAToolkit_FOUND)
        add_executable(test_egl_texture_upload_formats
            tests/test_egl_texture_upload_formats.cpp)
        target_compile_definitions(test_egl_texture_upload_formats PRIVATE
            OMNIUI_HAS_CUDA=1)
        target_include_directories(test_egl_texture_upload_formats PRIVATE
            ${CMAKE_CURRENT_SOURCE_DIR}/src)
        target_link_libraries(test_egl_texture_upload_formats PRIVATE
            omniui_standalone glad CUDA::cudart)
        if(NOT WIN32 AND NOT APPLE)
            set_target_properties(test_egl_texture_upload_formats PROPERTIES INSTALL_RPATH "$ORIGIN")
        endif()
        add_test(NAME egl_texture_upload_formats COMMAND test_egl_texture_upload_formats)
        set_tests_properties(egl_texture_upload_formats PROPERTIES
            ENVIRONMENT "OMNIUI_HEADLESS=1;OMNIUI_HEADLESS_GL=1;OMNIUI_EGL_FORCE_SURFACELESS=1"
            TIMEOUT 120)
        message(STATUS "test_egl_texture_upload_formats target added (all-format fromGpu test)")
    endif()

    # C1: EGL headless integration test — init, render, screenshot, verify non-blank.
    add_executable(headless_egl_test src/headless_egl_test.cpp)
    target_link_libraries(headless_egl_test PRIVATE omniui_standalone stb)
    target_include_directories(headless_egl_test PRIVATE
        ${CMAKE_SOURCE_DIR}/third_party/imgui)
    if(NOT WIN32 AND NOT APPLE)
        set_target_properties(headless_egl_test PROPERTIES INSTALL_RPATH "$ORIGIN")
    endif()
    add_test(NAME headless_egl COMMAND headless_egl_test /tmp/egl_ctest.png)
    set_tests_properties(headless_egl PROPERTIES
        ENVIRONMENT "OMNIUI_HEADLESS=1;OMNIUI_HEADLESS_GL=1;OMNIUI_EGL_FORCE_SURFACELESS=1")
    message(STATUS "headless_egl_test target added (C1 EGL integration test)")
endif()
