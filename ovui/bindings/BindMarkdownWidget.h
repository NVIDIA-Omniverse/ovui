/*
 * SPDX-FileCopyrightText: Copyright (c) 2024-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

#include <omni/ui/MarkdownWidget.h>
#include <omni/ui/bind/BindMarkdownWidget.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/Pybind.h>

#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapMarkdownWidget(module& m)
{
    constexpr const char* mdDoc = OMNIUI_PYBIND_CLASS_DOC(MarkdownWidget);
    static constexpr char mdConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(MarkdownWidget, MarkdownWidget);

    class_<MarkdownWidget, Widget, std::shared_ptr<MarkdownWidget>>(m, "MarkdownWidget", mdDoc)
        .def(init([](std::string text, kwargs kwargs) { OMNIUI_PYBIND_INIT(MarkdownWidget, text) }), mdConstructorDoc)
        .def_property("text", &MarkdownWidget::getText, &MarkdownWidget::setText, OMNIUI_PYBIND_DOC_MarkdownWidget_text)
        .OMNIUI_PYBIND_DEF_CALLBACK(link_clicked, MarkdownWidget, LinkClicked)
        .OMNIUI_PYBIND_DEF_CALLBACK(image_url_provider, MarkdownWidget, ImageUrlProvider)
        .def(
            "get_outline",
            [](const MarkdownWidget& self) {
                // Exposed as a list of plain dicts so Python callers don't
                // need to import a struct wrapper.  Keys match the C++
                // MarkdownHeadingInfo field names.
                list out;
                for (const auto& h : self.getOutline())
                {
                    dict d;
                    d["level"] = static_cast<int>(h.level);
                    d["text"] = h.text;
                    d["slug"] = h.slug;
                    out.append(std::move(d));
                }
                return out;
            },
            "Return the document heading outline as a list of dicts "
            "``{\"level\": int, \"text\": str, \"slug\": str}`` in source order.")
        .def(
            "scroll_to_anchor",
            &MarkdownWidget::scrollToAnchor,
            arg("slug"),
            "Scroll the enclosing scroll region so the heading with the given "
            "slug is near the top of the viewport.  Returns True when the slug "
            "is known; returns False if the widget has not rendered at least "
            "one frame or the slug is not in the outline.")
        .def(
            "copy_code_block",
            &MarkdownWidget::copyCodeBlock,
            arg("index"),
            "Copy the Nth fenced/indented code block's contents to the "
            "clipboard.  Mirrors the visual copy button.  Returns True on "
            "success; False when index is out of range.")
        /* */;
}
