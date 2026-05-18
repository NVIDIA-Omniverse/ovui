# ==============================================================================
# benchmarks/CMakeLists.txt - GL vs Vulkan performance benchmark
# ==============================================================================

set(IMGUI_BACKEND_DIR ${CMAKE_SOURCE_DIR}/third_party/imgui/backends)

set(BENCHMARK_IMGUI_SOURCES
    ${IMGUI_BACKEND_DIR}/imgui_impl_glfw.cpp
    ${IMGUI_BACKEND_DIR}/imgui_impl_opengl3.cpp
)
if(Vulkan_FOUND)
    list(APPEND BENCHMARK_IMGUI_SOURCES
        ${IMGUI_BACKEND_DIR}/imgui_impl_vulkan.cpp
    )
endif()

add_executable(vk_gl_benchmark
    vk_gl_benchmark.cpp
    ${BENCHMARK_IMGUI_SOURCES}
)

target_link_libraries(vk_gl_benchmark
    PRIVATE
        omniui_standalone
        ovui
        glad
        OpenGL::GL
        glfw
)

if(Vulkan_FOUND)
    target_compile_definitions(vk_gl_benchmark PRIVATE OMNIUI_HAS_VULKAN=1)
    target_include_directories(vk_gl_benchmark PRIVATE ${Vulkan_INCLUDE_DIRS})
    target_link_libraries(vk_gl_benchmark PRIVATE Vulkan::Vulkan)
endif()

target_include_directories(vk_gl_benchmark PRIVATE
    ${CMAKE_SOURCE_DIR}/standalone/src
    ${CMAKE_SOURCE_DIR}/third_party/imgui
    ${CMAKE_SOURCE_DIR}/third_party/imgui/backends
)

target_compile_definitions(vk_gl_benchmark PRIVATE
    IMGUI_NVIDIA
)

set_target_properties(vk_gl_benchmark PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/benchmarks
)
if(APPLE)
    set_target_properties(vk_gl_benchmark PROPERTIES
        INSTALL_RPATH "@executable_path/../lib;@executable_path"
    )
elseif(NOT WIN32)
    set_target_properties(vk_gl_benchmark PROPERTIES
        INSTALL_RPATH "$ORIGIN/../lib:$ORIGIN"
    )
endif()
