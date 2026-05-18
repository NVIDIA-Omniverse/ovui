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
    $<TARGET_OBJECTS:imgui>
)

target_include_directories(ovui
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
        ${CMAKE_SOURCE_DIR}/third_party/imgui   # for imgui_freetype.h -> "imgui.h"
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
        # Kit's ImGui 1.92.7 moved the shadow cut-out flag into ImDrawFlags at bit 9.
        # Standalone's vendored ImGui keeps the legacy separate ImDrawShadowFlags enum at bit 0.
        # Alias the new name so the byte-identical shared Shape.cpp compiles and behaves
        # correctly against standalone's AddShadowRect(... ImDrawShadowFlags ...).
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
    set_target_properties(ovui PROPERTIES
        VERSION ${PROJECT_VERSION}
        SOVERSION 3
    )
endif()
if(APPLE)
    set_target_properties(ovui PROPERTIES
        INSTALL_RPATH "@loader_path"
    )
elseif(NOT WIN32 AND NOT EMSCRIPTEN)
    set_target_properties(ovui PROPERTIES
        INSTALL_RPATH "$ORIGIN"
    )
endif()
if(WIN32)
    # Export all symbols so that omniui_standalone.dll can resolve ImGui symbols
    # (ImGui is compiled as OBJECT files into this DLL).
    set_target_properties(ovui PROPERTIES
        WINDOWS_EXPORT_ALL_SYMBOLS ON
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
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
            ovui
        PRIVATE
            glm
            boost_preprocessor
    )

    if(MSVC)
        target_compile_options(ovuiscene PRIVATE /W3 /wd4244 /wd4267 /wd4305 /wd4996)
    else()
        target_compile_options(ovuiscene PRIVATE -fpermissive -Wno-error)
    endif()

    set_target_properties(ovuiscene PROPERTIES
        OUTPUT_NAME ovuiscene
        CXX_VISIBILITY_PRESET hidden
        VISIBILITY_INLINES_HIDDEN ON
    )
    if(NOT WIN32)
        set_target_properties(ovuiscene PROPERTIES
            VERSION ${PROJECT_VERSION}
            SOVERSION 3
            BUILD_RPATH "$ORIGIN"
            INSTALL_RPATH "$ORIGIN"
        )
    endif()
    if(WIN32)
        set_target_properties(ovuiscene PROPERTIES
            WINDOWS_EXPORT_ALL_SYMBOLS ON
            RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
            ARCHIVE_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
        )
    endif()
endif()
