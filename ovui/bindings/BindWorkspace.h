/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: LicenseRef-NvidiaProprietary
 *
 * NVIDIA CORPORATION, its affiliates and licensors retain all intellectual
 * property and proprietary rights in and to this material, related
 * documentation and any modifications thereto. Any use, reproduction,
 * disclosure or distribution of this material and related documentation
 * without an express license agreement from NVIDIA CORPORATION or
 * its affiliates is strictly prohibited.
 */

#pragma once

#include <omni/ui/WindowHandle.h>
#include <omni/ui/Workspace.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/BindWorkspace.h>

using namespace pybind11;

namespace omni
{
namespace ui
{
namespace windowmanager
{

}
}
}

OMNIUI_NAMESPACE_USING_DIRECTIVE

static object _getDockNodeChildrenId(uint32_t dockId)
{
    uint32_t first;
    uint32_t second;
    if (Workspace::getDockNodeChildrenId(dockId, first, second))
    {
        return make_tuple(first, second);
    }

    return none();
}

void wrapWorkspace(module& m)
{
    constexpr const char* workspaceDoc = OMNIUI_PYBIND_CLASS_DOC(Workspace);

    class_<Workspace, std::shared_ptr<Workspace>>(m, "Workspace", workspaceDoc)
        .def_static("get_windows", &Workspace::getWindows, OMNIUI_PYBIND_DOC_Workspace_getWindows)
        .def_static("get_window", &Workspace::getWindow, arg("title"), OMNIUI_PYBIND_DOC_Workspace_getWindow)
        .def_static("get_window_from_callback", &Workspace::getWindowFromCallback, arg("callback"),
                    OMNIUI_PYBIND_DOC_Workspace_getWindowFromCallback)
        .def_static("get_dpi_scale", &Workspace::getDpiScale, OMNIUI_PYBIND_DOC_Workspace_getDpiScale)
        .def_static(
            "get_main_window_width", &Workspace::getMainWindowWidth, OMNIUI_PYBIND_DOC_Workspace_getMainWindowWidth)
        .def_static(
            "get_main_window_height", &Workspace::getMainWindowHeight, OMNIUI_PYBIND_DOC_Workspace_getMainWindowHeight)
        .def_static("get_docked_neighbours", &Workspace::getDockedNeighbours, arg("member"),
                    OMNIUI_PYBIND_DOC_Workspace_getDockedNeighbours)
        .def_static("get_selected_window_index", &Workspace::getSelectedWindowIndex, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getSelectedWindowIndex)
        .def_static("get_parent_dock_id", &Workspace::getParentDockId, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getParentDockId)
        .def_static("get_dock_children_id", &_getDockNodeChildrenId, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getDockNodeChildrenId)
        .def_static("get_dock_position", &Workspace::getDockPosition, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getDockPosition)
        .def_static(
            "get_dock_id_width", &Workspace::getDockIdWidth, arg("dock_id"), OMNIUI_PYBIND_DOC_Workspace_getDockIdWidth)
        .def_static("get_dock_id_height", &Workspace::getDockIdHeight, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getDockIdHeight)
        .def_static("set_dock_id_width", &Workspace::setDockIdWidth, arg("dock_id"), arg("width"),
                    OMNIUI_PYBIND_DOC_Workspace_setDockIdWidth)
        .def_static("set_dock_id_height", &Workspace::setDockIdHeight, arg("dock_id"), arg("height"),
                    OMNIUI_PYBIND_DOC_Workspace_setDockIdHeight)
        .def_static("get_docked_windows", &Workspace::getDockedWindows, arg("dock_id"),
                    OMNIUI_PYBIND_DOC_Workspace_getDockedWindows)
        .def_static("clear", &Workspace::clear, OMNIUI_PYBIND_DOC_Workspace_clear)
        .def_static("show_window", &Workspace::showWindow, arg("title"), arg("show") = true,
                    OMNIUI_PYBIND_DOC_Workspace_showWindow)
        .def_static("set_show_window_fn",
                    [](const std::string& title, const std::function<void(bool)>& fn)
                    {
                        // make sure to pass along an empty function if `None` was passed in as
                        // the function.  Otherwise wrapping the empty function will never be
                        // seen as empty inside setShowWindowFn().
                        Workspace::setShowWindowFn(title, fn ? wrapPythonCallback(fn) : std::function<void(bool)>{});
                    }, arg("title"), arg("fn"), OMNIUI_PYBIND_DOC_Workspace_setShowWindowFn)
        .def_static("get_show_window_titles", &Workspace::getShowWindowTitles, OMNIUI_PYBIND_DOC_Workspace_getShowWindowTitles)
        .def_static("set_window_created_callback",
                    [](std::function<void(const std::shared_ptr<WindowHandle>& window)> fn)
                    { Workspace::setWindowCreatedCallback(wrapPythonCallback(fn)); },
                    arg("fn"), OMNIUI_PYBIND_DOC_Workspace_setWindowCreatedCallback)
        .def_static("set_window_visibility_changed_callback",
                    [](std::function<void(const std::string& title, bool visible)> fn)
                    { return Workspace::setWindowVisibilityChangedCallback(wrapPythonCallback(fn)); },
                    arg("fn"), OMNIUI_PYBIND_DOC_Workspace_setWindowVisibilityChangedCallback)
        .def_static("remove_window_visibility_changed_callback", &Workspace::removeWindowVisibilityChangedCallback, arg("fn"),
                    OMNIUI_PYBIND_DOC_Workspace_removeWindowVisibilityChangedCallback)
        /* */;
}
