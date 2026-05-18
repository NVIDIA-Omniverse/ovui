# ==============================================================================
# third_party/CMakeLists.txt - Third-party dependency targets
# ==============================================================================

include(FetchContent)

# --- ImGui (OBJECT library) ---
add_library(imgui OBJECT
    imgui/imgui.cpp
    imgui/imgui_draw.cpp
    imgui/imgui_tables.cpp
    imgui/imgui_widgets.cpp
    imgui/imgui_demo.cpp
    imgui/misc/freetype/imgui_freetype.cpp
)
target_include_directories(imgui PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}          # so #include <imgui/imgui.h> works
)
target_include_directories(imgui PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/imgui    # for imgui internal includes
)
target_compile_definitions(imgui PUBLIC IMGUI_NVIDIA)
target_link_libraries(imgui PUBLIC Freetype::Freetype)

# --- glad (generated OpenGL loader) ---
# Verified refs/tags/v0.1.36 with:
# git ls-remote https://github.com/Dav1dde/glad.git refs/tags/v0.1.36
FetchContent_Declare(
    glad
    GIT_REPOSITORY https://github.com/Dav1dde/glad.git
    GIT_TAG        1ecd45775d96f35170458e6b148eb0708967e402
    GIT_SHALLOW    FALSE
)
set(GLAD_REPRODUCIBLE ON CACHE BOOL "" FORCE)
set(GLAD_PROFILE "core" CACHE STRING "" FORCE)
set(GLAD_API "gl=3.3" CACHE STRING "" FORCE)
set(GLAD_GENERATOR "c" CACHE STRING "" FORCE)
set(GLAD_EXTENSIONS
    "${CMAKE_CURRENT_SOURCE_DIR}/glad_extensions.txt"
    CACHE FILEPATH "" FORCE
)
set(GLAD_ALL_EXTENSIONS OFF CACHE BOOL "" FORCE)
set(GLAD_NO_LOADER OFF CACHE BOOL "" FORCE)
set(GLAD_INSTALL OFF CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(glad)

# glad v0.1.36 opens packaged XML resources in text mode before handing them to
# ElementTree.  On Python builds that do not have lxml installed, the UTF-8 BOM
# in gl.xml is surfaced as text and ElementTree rejects the file.
set(_ovui_glad_gl_xml "${glad_SOURCE_DIR}/glad/files/gl.xml")
if(EXISTS "${_ovui_glad_gl_xml}")
    if(PYTHON_EXECUTABLE)
        set(_ovui_glad_patch_python "${PYTHON_EXECUTABLE}")
    else()
        find_package(Python3 COMPONENTS Interpreter QUIET)
        set(_ovui_glad_patch_python "${Python3_EXECUTABLE}")
    endif()

    if(_ovui_glad_patch_python)
        execute_process(
            COMMAND
                "${_ovui_glad_patch_python}" -c
                "from pathlib import Path; p = Path(r'''${_ovui_glad_gl_xml}'''); data = p.read_bytes(); p.write_bytes(data[3:] if data.startswith(b'\\xef\\xbb\\xbf') else data)"
            RESULT_VARIABLE _ovui_glad_patch_result
        )
        if(NOT _ovui_glad_patch_result EQUAL 0)
            message(FATAL_ERROR "Failed to normalize ${_ovui_glad_gl_xml}")
        endif()
    endif()
endif()

# --- Header-only interface targets ---

# GLM
# Verified refs/tags/0.9.9.8 with:
# git ls-remote https://github.com/g-truc/glm.git refs/tags/0.9.9.8
FetchContent_Declare(
    glm
    GIT_REPOSITORY https://github.com/g-truc/glm.git
    GIT_TAG        bf71a834948186f4097caa076cd2663c69a10e1e
    GIT_SHALLOW    FALSE
)
FetchContent_MakeAvailable(glm)
if(NOT TARGET glm AND TARGET glm::glm)
    add_library(glm ALIAS glm::glm)
endif()

# Boost.Preprocessor
# Verified refs/tags/boost-1.85.0 with:
# git ls-remote https://github.com/boostorg/preprocessor.git refs/tags/boost-1.85.0
FetchContent_Declare(
    boost_preprocessor
    GIT_REPOSITORY https://github.com/boostorg/preprocessor.git
    GIT_TAG        c4ea7e40d365ba28faecef8917d5c3f1e0121bf9
    GIT_SHALLOW    FALSE
)
FetchContent_MakeAvailable(boost_preprocessor)

# stb
FetchContent_Declare(
    stb
    GIT_REPOSITORY https://github.com/nothings/stb.git
    GIT_TAG        31c1ad37456438565541f4919958214b6e762fb4
    GIT_SHALLOW    FALSE
)
FetchContent_Populate(stb)
add_library(stb INTERFACE)
target_include_directories(stb INTERFACE
    ${stb_SOURCE_DIR}
)

# --- md4c (CommonMark/GFM parser) ---
# Verified refs/tags/release-0.5.2 with:
# git ls-remote https://github.com/mity/md4c.git refs/tags/release-0.5.2
#
# Upstream CMake always adds md4c-html; populate the source tree and build only
# the parser plus entity table used by ovui's markdown renderer.
FetchContent_Declare(
    md4c
    GIT_REPOSITORY https://github.com/mity/md4c.git
    GIT_TAG        729e6b8b320caa96328968ab27d7db2235e4fb47
    GIT_SHALLOW    FALSE
    SOURCE_SUBDIR  cmake/skip-upstream-add-subdirectory
)
FetchContent_MakeAvailable(md4c)

add_library(md4c STATIC
    ${md4c_SOURCE_DIR}/src/md4c.c
    ${md4c_SOURCE_DIR}/src/entity.c
)
target_include_directories(md4c PUBLIC
    ${md4c_SOURCE_DIR}/src
)
target_compile_definitions(md4c PRIVATE
    MD_VERSION_MAJOR=0
    MD_VERSION_MINOR=5
    MD_VERSION_RELEASE=2
    MD4C_USE_UTF8
)
set_target_properties(md4c PROPERTIES POSITION_INDEPENDENT_CODE ON)
