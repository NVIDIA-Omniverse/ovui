find_package(pybind11 REQUIRED)

pybind11_add_module(_ui Module.cpp BindCornerFlag.cpp StandalonePlatformBindings.cpp)

target_link_libraries(_ui PRIVATE ovui omniui_standalone)

target_include_directories(_ui PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/core/include
    ${CMAKE_SOURCE_DIR}/core/src
    ${CMAKE_SOURCE_DIR}/standalone/src
)

target_compile_definitions(_ui PRIVATE IMGUI_NVIDIA)

if(APPLE)
    set_target_properties(_ui PROPERTIES
        INSTALL_RPATH "@loader_path"
    )
elseif(NOT WIN32)
    set_target_properties(_ui PROPERTIES
        INSTALL_RPATH "$ORIGIN"
    )
endif()
if(WIN32)
    set_target_properties(_ui PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# Copy module to the Python package directory after every build so that
# ``python tests/run_tests.py`` always picks up the freshly-built binary.
set(_PY_PKG_DIR "${CMAKE_SOURCE_DIR}/python/omni/ui")
add_custom_command(TARGET _ui POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:_ui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovui> "${_PY_PKG_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:omniui_standalone> "${_PY_PKG_DIR}/"
    COMMENT "Copying _ui, ovui, omniui_standalone to ${_PY_PKG_DIR}"
)

# Install the extension module next to the Python package
install(TARGETS _ui DESTINATION ${CMAKE_SOURCE_DIR}/python/omni/ui)

# ─── _scene pybind11 module ──────────────────────────────────────────────────
file(GLOB SCENE_BIND_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/scene/Bind*.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/scene/Module.cpp
)

pybind11_add_module(_scene ${SCENE_BIND_SOURCES})

target_link_libraries(_scene PRIVATE ovuiscene ovui omniui_standalone)

target_include_directories(_scene PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${CMAKE_SOURCE_DIR}/core/include
    ${CMAKE_SOURCE_DIR}/core/src
    ${CMAKE_SOURCE_DIR}/standalone/src
)

target_compile_definitions(_scene PRIVATE IMGUI_NVIDIA)

if(APPLE)
    set_target_properties(_scene PROPERTIES
        INSTALL_RPATH "@loader_path"
    )
elseif(NOT WIN32)
    set_target_properties(_scene PROPERTIES
        INSTALL_RPATH "$ORIGIN"
    )
endif()
if(WIN32)
    set_target_properties(_scene PROPERTIES
        RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_CURRENT_BINARY_DIR}"
    )
endif()

# Copy _scene module and ovuiscene to the Python package dir after every build.
set(_SCENE_PY_DIR "${CMAKE_SOURCE_DIR}/python/omni/ui_scene")
add_custom_command(TARGET _scene POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${_SCENE_PY_DIR}"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:_scene>    "${_SCENE_PY_DIR}/"
    COMMAND ${CMAKE_COMMAND} -E copy_if_different $<TARGET_FILE:ovuiscene> "${_SCENE_PY_DIR}/"
    COMMENT "Copying _scene and ovuiscene to ${_SCENE_PY_DIR}"
)

install(TARGETS _scene DESTINATION ${CMAKE_SOURCE_DIR}/python/omni/ui_scene)
