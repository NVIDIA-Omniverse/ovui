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

#include "FontHelper.h"
#include "Types.h"
#include "Widget.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Minimal description of a heading in the parsed markdown outline.
 *
 * Returned in source order by MarkdownWidget::getOutline.  Values are
 * copies of the widget-owned parse state; mutating this struct does not
 * affect the widget.
 */
struct MarkdownHeadingInfo
{
    uint8_t level = 0;
    std::string text;  // Decoded heading text (UTF-8).  Falls back to slug if empty.
    std::string slug;  // Stable anchor slug suitable for scrollToAnchor.
};

/**
 * @brief A native ImGui markdown renderer widget.
 *
 * MarkdownWidget parses CommonMark + GitHub flavored markdown via md4c on
 * setText() and renders directly through ImGui draw calls each frame in
 * _drawContent.  No child ovui widgets are created -- everything is drawn
 * with ImFont + ImDrawList primitives.
 *
 * Style cascade keys consumed: color, background_color, font, font_size, ...
 * Place inside a ScrollingFrame for long documents.
 */
class OMNIUI_CLASS_API MarkdownWidget : public Widget, public FontHelper
{
    OMNIUI_OBJECT(MarkdownWidget)

public:
    OMNIUI_API
    ~MarkdownWidget() override;

    /**
     * @brief Width hint -- markdown wraps to whatever the cascade gives us.
     */
    OMNIUI_API
    void setComputedContentWidth(float width) override;

    /**
     * @brief Height hint -- we report the height of the layouted document.
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Style updated -- invalidate cached layout.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Optional native provider for async Markdown assets.
     *
     * The provider can supply ready/pending/failed textures for image-like
     * Markdown content without blocking the immediate-mode render pass.  Local
     * files and data URIs continue to work through the built-in resolver when
     * this provider is unset or returns eUnsupported.
     *
     * Ownership: the widget takes a shared ownership handle.  Pass nullptr to
     * detach.  Setting a new provider does not flush the widget's texture
     * cache -- the C++ renderer decides how to handle transitions.
     */
    OMNIUI_API
    void setMarkdownAssetProvider(std::shared_ptr<IMarkdownAssetProvider> provider);

    /**
     * @brief Accessor for the currently installed provider, or nullptr when
     * none has been set.  Primarily for tests and the pybind11 binding layer.
     */
    OMNIUI_API
    std::shared_ptr<IMarkdownAssetProvider> getMarkdownAssetProvider() const;

    /**
     * @brief Enumerate the headings in the parsed document in source order.
     *
     * Reparses the source if it has been dirtied since the last call.  Each
     * entry carries the heading level (1..6), the heading text, and a
     * stable slug suitable for scrollToAnchor / anchor-link navigation.
     */
    OMNIUI_API
    std::vector<MarkdownHeadingInfo> getOutline() const;

    /**
     * @brief Scroll the enclosing scroll region so the heading with the
     * given slug is near the top of the viewport.
     *
     * @return true when the slug was found in the document outline.  The
     *         actual scroll is applied on the next frame's _drawContent so
     *         callers that run outside of ImGui's render pass still see a
     *         deterministic result.  Returns false if the slug is unknown
     *         or if the widget has not drawn at least once yet (offset
     *         cache is populated during the walk).
     */
    OMNIUI_API
    bool scrollToAnchor(const std::string& slug);

    /**
     * @brief Copy the Nth fenced/indented code block's contents to the
     *        system clipboard.
     *
     * Pure helper for tests and automation -- mirrors the copy button on
     * each code block.  Index is source-order.  Returns false when the
     * index is out of range or the document has not parsed.
     */
    OMNIUI_API
    bool copyCodeBlock(int index);

    /**
     * @brief The raw markdown source for this widget.
     */
    OMNIUI_PROPERTY(std::string, text, READ, getText, WRITE, setText, NOTIFY, setTextChangedFn);

    /**
     * @brief Fired when the user clicks a link.  The argument is the link URL
     * (the contents of the markdown's `[text](url)` URL field).
     */
    OMNIUI_CALLBACK(LinkClicked, void, std::string);

    /**
     * @brief Optional callback for custom image URL resolution.
     *
     * When set, the widget calls this function with the image `src` string
     * from the markdown.  The callback should return a resolved file path
     * (or empty string to fall back to the default resolver).
     */
    OMNIUI_CALLBACK(ImageUrlProvider, std::string, const std::string&);

protected:
    /**
     * @brief Construct a markdown widget with the given source text.
     */
    OMNIUI_API
    MarkdownWidget(const std::string& text);

    /**
     * @brief Render the parsed markdown for the current frame.
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct MarkdownWidgetData;

    /**
     * @brief Re-parse the source text via md4c into the cached token stream.
     */
    void _reparse();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
