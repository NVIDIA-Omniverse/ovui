if(NOT EMSCRIPTEN)
    message(FATAL_ERROR "web/runtime must be configured with the Emscripten toolchain")
endif()

if(NOT TARGET ovui)
    message(FATAL_ERROR "Configure from ovui/ so the ovui core target is available")
endif()

if(NOT OVUI_CPYTHON_SOURCE_DIR)
    message(FATAL_ERROR "OVUI_CPYTHON_SOURCE_DIR must point at the official CPython source checkout")
endif()

if(NOT OVUI_CPYTHON_WASM_BUILD_DIR)
    message(FATAL_ERROR "OVUI_CPYTHON_WASM_BUILD_DIR must point at the CPython wasm32-emscripten build directory")
endif()

if(NOT OVUI_WEB_PACKAGE_DIR)
    message(FATAL_ERROR "OVUI_WEB_PACKAGE_DIR must point at the preloaded filesystem staging directory")
endif()
if(NOT OVUI_PYBIND11_INCLUDE_DIR)
    message(FATAL_ERROR "OVUI_PYBIND11_INCLUDE_DIR must point at pybind11 headers")
endif()
if(NOT OVUI_WEB_OUTPUT_DIR)
    set(OVUI_WEB_OUTPUT_DIR "${CMAKE_BINARY_DIR}/dist")
endif()

set(IMGUI_DIR "${CMAKE_SOURCE_DIR}/third_party/imgui")
set(OVUI_CPYTHON_LIBRARY "${OVUI_CPYTHON_WASM_BUILD_DIR}/libpython3.12.a")
set(OVUI_CPYTHON_EXTRA_LIBRARIES
    "${OVUI_CPYTHON_WASM_BUILD_DIR}/Modules/_decimal/libmpdec/libmpdec.a"
    "${OVUI_CPYTHON_WASM_BUILD_DIR}/Modules/_hacl/libHacl_Hash_SHA2.a"
    "${OVUI_CPYTHON_WASM_BUILD_DIR}/Modules/expat/libexpat.a"
)

if(NOT EXISTS "${OVUI_CPYTHON_LIBRARY}")
    message(FATAL_ERROR "CPython wasm library not found: ${OVUI_CPYTHON_LIBRARY}")
endif()
foreach(_ovui_cpython_extra IN LISTS OVUI_CPYTHON_EXTRA_LIBRARIES)
    if(NOT EXISTS "${_ovui_cpython_extra}")
        message(FATAL_ERROR "CPython wasm support library not found: ${_ovui_cpython_extra}")
    endif()
endforeach()

add_executable(ovui_web
    WebRuntime.cpp
    WebPlatform.cpp
    WebPlatformBindings.cpp
    "${CMAKE_SOURCE_DIR}/bindings/Module.cpp"
    "${CMAKE_SOURCE_DIR}/bindings/BindCornerFlag.cpp"
    "${CMAKE_SOURCE_DIR}/standalone/src/StandaloneSettings.cpp"
    "${CMAKE_SOURCE_DIR}/standalone/src/StandaloneGlyphManager.cpp"
    "${IMGUI_DIR}/backends/imgui_impl_opengl3.cpp"
)

target_include_directories(ovui_web PRIVATE
    "${CMAKE_SOURCE_DIR}/bindings"
    "${CMAKE_SOURCE_DIR}/core/include"
    "${CMAKE_SOURCE_DIR}/core/src"
    "${CMAKE_SOURCE_DIR}/standalone/src"
    "${IMGUI_DIR}"
    "${IMGUI_DIR}/backends"
    "${OVUI_CPYTHON_SOURCE_DIR}/Include"
    "${OVUI_CPYTHON_SOURCE_DIR}/Include/internal"
    "${OVUI_CPYTHON_WASM_BUILD_DIR}"
    "${OVUI_PYBIND11_INCLUDE_DIR}"
)

target_compile_definitions(ovui_web PRIVATE
    IMGUI_NVIDIA
    IMGUI_IMPL_OPENGL_ES2
    OMNIUI_PYBIND_EMBEDDED
    OMNIUI_PYBIND_STRICT_KWARGS
)

target_compile_options(ovui_web PRIVATE
    -fexceptions
    -fpermissive
    -Wno-error
)

target_link_libraries(ovui_web PRIVATE
    "-Wl,--whole-archive"
    ovui
    "${OVUI_CPYTHON_LIBRARY}"
    "-Wl,--no-whole-archive"
    ${OVUI_CPYTHON_EXTRA_LIBRARIES}
)

target_link_options(ovui_web PRIVATE
    "SHELL:--no-entry"
    "SHELL:-fexceptions"
    "SHELL:-sALLOW_MEMORY_GROWTH=1"
    "SHELL:-sINITIAL_MEMORY=67108864"
    "SHELL:-sFORCE_FILESYSTEM=1"
    "SHELL:-sWASM_BIGINT=1"
    "SHELL:-sUSE_ZLIB=1"
    "SHELL:-sUSE_BZIP2=1"
    "SHELL:-sUSE_SQLITE3=1"
    "SHELL:-sENVIRONMENT=web"
    "SHELL:-sEXPORTED_FUNCTIONS=['_ovui_web_init','_ovui_web_run_python','_ovui_web_tick','_ovui_web_resize','_ovui_web_shutdown','_ovui_web_backend_info','_ovui_web_font_info','_ovui_web_dpi_info']"
    "SHELL:-sEXPORTED_RUNTIME_METHODS=['ccall']"
    "SHELL:--pre-js ${CMAKE_CURRENT_SOURCE_DIR}/ModulePre.js"
    "SHELL:--post-js ${CMAKE_SOURCE_DIR}/web/static/app.js"
    "SHELL:--preload-file ${OVUI_WEB_PACKAGE_DIR}/usr@/usr"
    "SHELL:--preload-file ${OVUI_WEB_PACKAGE_DIR}/home@/home"
    "SHELL:--preload-file ${OVUI_WEB_PACKAGE_DIR}/assets@/assets"
)

set_target_properties(ovui_web PROPERTIES
    OUTPUT_NAME ovui
    RUNTIME_OUTPUT_DIRECTORY "${OVUI_WEB_OUTPUT_DIR}"
)
