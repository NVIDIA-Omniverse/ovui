/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#include "WebPlatform.h"

#include <Python.h>
#include <emscripten/emscripten.h>

#include <sstream>
#include <string>

namespace {

bool s_pythonInitialized = false;
std::string s_lastString;
std::string s_lastError;

std::string jsonEscape(const std::string& value)
{
    std::ostringstream out;
    for (char ch : value)
    {
        switch (ch)
        {
        case '\\': out << "\\\\"; break;
        case '"': out << "\\\""; break;
        case '\b': out << "\\b"; break;
        case '\f': out << "\\f"; break;
        case '\n': out << "\\n"; break;
        case '\r': out << "\\r"; break;
        case '\t': out << "\\t"; break;
        default:
            if (static_cast<unsigned char>(ch) < 0x20)
            {
                out << "\\u";
                const char* hex = "0123456789abcdef";
                out << "00" << hex[(ch >> 4) & 0x0f] << hex[ch & 0x0f];
            }
            else
            {
                out << ch;
            }
            break;
        }
    }
    return out.str();
}

std::string errorJson(const std::string& message)
{
    return "{\"status\":\"error\",\"stdout\":\"\",\"stderr\":\"\",\"traceback\":\"" + jsonEscape(message) + "\"}";
}

std::string pyObjectToUtf8(PyObject* object)
{
    if (!object)
        return {};

    PyObject* text = PyObject_Str(object);
    if (!text)
        return {};

    const char* utf8 = PyUnicode_AsUTF8(text);
    std::string result = utf8 ? utf8 : "";
    Py_DECREF(text);
    return result;
}

std::string fetchPythonError()
{
    if (!PyErr_Occurred())
        return {};

    PyObject* type = nullptr;
    PyObject* value = nullptr;
    PyObject* traceback = nullptr;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);

    std::string result;
    PyObject* tracebackModule = PyImport_ImportModule("traceback");
    if (tracebackModule)
    {
        PyObject* formatter = PyObject_GetAttrString(tracebackModule, "format_exception");
        if (formatter)
        {
            PyObject* lines = PyObject_CallFunctionObjArgs(
                formatter,
                type ? type : Py_None,
                value ? value : Py_None,
                traceback ? traceback : Py_None,
                nullptr);
            if (lines)
            {
                PyObject* separator = PyUnicode_FromString("");
                PyObject* joined = separator ? PyUnicode_Join(separator, lines) : nullptr;
                if (joined)
                {
                    result = pyObjectToUtf8(joined);
                    Py_DECREF(joined);
                }
                Py_XDECREF(separator);
                Py_DECREF(lines);
            }
            Py_DECREF(formatter);
        }
        Py_DECREF(tracebackModule);
    }

    if (result.empty())
        result = pyObjectToUtf8(value ? value : type);

    Py_XDECREF(type);
    Py_XDECREF(value);
    Py_XDECREF(traceback);
    return result.empty() ? "unknown Python error" : result;
}

bool appendSearchPath(PyConfig& config, const wchar_t* path)
{
    PyStatus status = PyWideStringList_Append(&config.module_search_paths, path);
    if (PyStatus_Exception(status))
    {
        s_lastError = status.err_msg ? status.err_msg : "failed to append Python search path";
        return false;
    }
    return true;
}

bool initializePython()
{
    if (s_pythonInitialized)
        return true;

    PyConfig config;
    PyConfig_InitIsolatedConfig(&config);
    config.isolated = 1;
    config.use_environment = 0;
    config.user_site_directory = 0;
    config.site_import = 0;
    config.write_bytecode = 0;
    config.parse_argv = 0;
    config.install_signal_handlers = 0;
    config.module_search_paths_set = 1;

    PyStatus status = PyConfig_SetString(&config, &config.program_name, L"ovui");
    if (PyStatus_Exception(status))
    {
        s_lastError = status.err_msg ? status.err_msg : "failed to set Python program name";
        PyConfig_Clear(&config);
        return false;
    }

    bool pathsOk = appendSearchPath(config, L"/home/ovui/python") &&
                   appendSearchPath(config, L"/usr/local/lib/python312.zip") &&
                   appendSearchPath(config, L"/usr/local/lib/python3.12") &&
                   appendSearchPath(config, L"/usr/local/lib/python3.12/lib-dynload");
    if (!pathsOk)
    {
        PyConfig_Clear(&config);
        return false;
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status))
    {
        s_lastError = status.err_msg ? status.err_msg : "Py_InitializeFromConfig failed";
        return false;
    }

    s_pythonInitialized = true;
    return true;
}

bool importOmniUi()
{
    PyObject* module = PyImport_ImportModule("omni.ui");
    if (!module)
    {
        s_lastError = fetchPythonError();
        return false;
    }
    Py_DECREF(module);
    return true;
}

const char* stableString(const std::string& value)
{
    s_lastString = value;
    return s_lastString.c_str();
}

const char* backendString(const std::string& value)
{
    return stableString(s_pythonInitialized ? value : "CPython runtime not initialized");
}

} // namespace

extern "C" {

EMSCRIPTEN_KEEPALIVE
int ovui_web_init(const char* canvasSelector, int width, int height, double devicePixelRatio)
{
    if (!initializePython())
        return 0;

    const char* selector = canvasSelector && canvasSelector[0] ? canvasSelector : "#canvas";
    if (!omni::ui::web::init(selector, width, height, static_cast<float>(devicePixelRatio)))
    {
        s_lastError = "failed to initialize ovui WebGL backend";
        return 0;
    }

    return importOmniUi() ? 1 : 0;
}

EMSCRIPTEN_KEEPALIVE
const char* ovui_web_run_python(const char* script)
{
    if (!s_pythonInitialized)
        return stableString(errorJson(s_lastError.empty() ? "CPython runtime not initialized" : s_lastError));

    static const char* runner = R"PY(
def _ovui_run_user_code(_ovui_user_code):
    import contextlib
    import io
    import json
    import traceback
    import omni.ui as ui

    ui._web_reset()
    _stdout = io.StringIO()
    _stderr = io.StringIO()
    _status = "ok"
    _traceback = ""

    try:
        with contextlib.redirect_stdout(_stdout), contextlib.redirect_stderr(_stderr):
            exec(_ovui_user_code, {"__name__": "__main__"})
    except Exception:
        _status = "error"
        _traceback = traceback.format_exc()
        ui._web_reset()

    return json.dumps({
        "status": _status,
        "stdout": _stdout.getvalue(),
        "stderr": _stderr.getvalue(),
        "traceback": _traceback,
    })
)PY";

    PyObject* mainModule = PyImport_AddModule("__main__");
    PyObject* globals = mainModule ? PyModule_GetDict(mainModule) : nullptr;
    if (!globals)
        return stableString(errorJson("failed to access __main__ globals"));

    PyObject* loaded = PyRun_String(runner, Py_file_input, globals, globals);
    if (!loaded)
        return stableString(errorJson(fetchPythonError()));
    Py_DECREF(loaded);

    PyObject* function = PyDict_GetItemString(globals, "_ovui_run_user_code");
    if (!function)
        return stableString(errorJson("internal runner function was not created"));

    PyObject* code = PyUnicode_FromString(script ? script : "");
    if (!code)
        return stableString(errorJson(fetchPythonError()));

    PyObject* result = PyObject_CallFunctionObjArgs(function, code, nullptr);
    Py_DECREF(code);
    if (!result)
        return stableString(errorJson(fetchPythonError()));

    std::string json = pyObjectToUtf8(result);
    Py_DECREF(result);
    return stableString(json.empty() ? errorJson("Python runner returned an empty result") : json);
}

EMSCRIPTEN_KEEPALIVE
int ovui_web_tick()
{
    return omni::ui::web::tick() ? 1 : 0;
}

EMSCRIPTEN_KEEPALIVE
int ovui_web_resize(int width, int height, double devicePixelRatio)
{
    return omni::ui::web::setCanvasSize(width, height, static_cast<float>(devicePixelRatio)) ? 1 : 0;
}

EMSCRIPTEN_KEEPALIVE
void ovui_web_shutdown()
{
    omni::ui::web::shutdown();
    if (s_pythonInitialized)
    {
        Py_FinalizeEx();
        s_pythonInitialized = false;
    }
}

EMSCRIPTEN_KEEPALIVE
const char* ovui_web_backend_info()
{
    return backendString(omni::ui::web::backendInfo());
}

EMSCRIPTEN_KEEPALIVE
const char* ovui_web_font_info()
{
    return backendString(omni::ui::web::fontInfo());
}

EMSCRIPTEN_KEEPALIVE
const char* ovui_web_dpi_info()
{
    return backendString(omni::ui::web::dpiInfo());
}

} // extern "C"
