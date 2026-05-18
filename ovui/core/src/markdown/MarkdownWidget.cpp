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

#include "platform/Assert.h"

#include <imgui/imgui.h>
#include <imgui/imgui_internal.h>

#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/MarkdownWidget.h>
#include <omni/ui/StyleContainer.h>
#include <omni/ui/platform/IUiFileIO.h>
#include <omni/ui/platform/PlatformRegistry.h>

#include "WidgetData.h"
#include "markdown/ImageResolver.h"
#include "markdown/MarkdownRenderer.h"
#include "markdown/MarkdownStyleResolver.h"
#include "markdown/RenderConfig.h"
#include "markdown/TwemojiAtlas.h"

#include <md4c.h>

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <memory>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE


struct MarkdownWidget::MarkdownWidgetData : public Widget::WidgetData
{
    ~MarkdownWidgetData() override = default;

    MarkdownDocument doc;
    bool docDirty = true;

    // Cached layout for the last (width) we measured.
    float lastWidth = -1.0f;
    float lastHeight = 0.0f;

    // Per-widget link interaction state, kept alive across frames.
    InteractionState interaction;

    // Image resolver for inline images (file paths + base64 data URIs).
    std::unique_ptr<StbImageResolver> imageResolver;

    // Twemoji atlas — loaded lazily on first emoji encounter.
    std::unique_ptr<TwemojiAtlas> emojiAtlas;
    bool emojiAtlasTriedLoad = false;

    // Cached RenderConfig.  Rebuilt only when the cascade changes or the
    // source text/font-size changes; otherwise reused verbatim.
    RenderConfig cachedConfig;
    bool configDirty = true;
    MarkdownStyleCache styleCache;
    float lastDpiScale = -1.0f;

    // Optional async-asset provider (owned by the widget).  Swapping a
    // provider invalidates the cached render config so any provider-owned
    // texture handles are re-queried on the next frame.
    std::shared_ptr<IMarkdownAssetProvider> assetProvider;

    // Bumped on every reparse; providers can use this to drop inflight work
    // for a superseded document.
    uint64_t documentGeneration = 1;

    // Anchor Y offsets filled by the renderer during _drawContent via
    // InteractionState::anchorOffsetsThisFrame; mapped to slug here for
    // scrollToAnchor lookups.  Cleared at each walk.
    std::unordered_map<std::string, float> anchorYCache;

    // When >= 0, _drawContent calls ImGui::SetScrollY on the next frame.
    // Reset to -1 after consumption.
    float pendingScrollY = -1.0f;
};


MarkdownWidget::MarkdownWidget(const std::string& text)
    : Widget(new MarkdownWidgetData)
{
    this->setText(text);
    this->setTextChangedFn([this](const auto&) {
        auto& data = _getData<MarkdownWidgetData>();
        data.docDirty = true;
        data.lastWidth = -1.0f;
        data.configDirty = true;
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
        this->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
    });
}

MarkdownWidget::~MarkdownWidget() = default;

void MarkdownWidget::_reparse()
{
    auto& data = _getData<MarkdownWidgetData>();
    if (data.docDirty)
    {
        uint64_t previousGeneration = data.documentGeneration;
        data.documentGeneration++;
        if (data.assetProvider)
            data.assetProvider->cancelGeneration(previousGeneration);
        parseMarkdown(this->getText(), data.doc);
        data.docDirty = false;
    }
}

void MarkdownWidget::setComputedContentWidth(float width)
{
    Widget::setComputedContentWidth(width);
}

void MarkdownWidget::setComputedContentHeight(float height)
{
    auto& data = _getData<MarkdownWidgetData>();
    float reported = std::max(height, data.lastHeight);
    Widget::setComputedContentHeight(reported);
}

void MarkdownWidget::onStyleUpdated()
{
    auto& data = _getData<MarkdownWidgetData>();
    data.lastWidth = -1.0f;
    data.configDirty = true;
}

void MarkdownWidget::setMarkdownAssetProvider(std::shared_ptr<IMarkdownAssetProvider> provider)
{
    auto& data = _getData<MarkdownWidgetData>();
    data.assetProvider = std::move(provider);
    // Provider pointer lives outside the cached RenderConfig; invalidating
    // here means the next frame will pick up the new provider even though
    // the style cascade itself did not change.
    data.configDirty = true;
    this->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
}

std::shared_ptr<IMarkdownAssetProvider> MarkdownWidget::getMarkdownAssetProvider() const
{
    const auto& data = _getData<MarkdownWidgetData>();
    return data.assetProvider;
}

std::vector<MarkdownHeadingInfo> MarkdownWidget::getOutline() const
{
    // Cast away const because _reparse mutates the cached parse state.
    // The widget is documented as logically const here -- the underlying
    // cache is an implementation detail.
    auto* self = const_cast<MarkdownWidget*>(this);
    self->_reparse();

    const auto& data = _getData<MarkdownWidgetData>();
    std::vector<MarkdownHeadingInfo> out;
    out.reserve(data.doc.headings.size());

    const std::string& buf = data.doc.textBuffer;
    const size_t bufSize = buf.size();
    for (const MdHeading& h : data.doc.headings)
    {
        MarkdownHeadingInfo info;
        info.level = h.level;
        if (h.slugLen > 0 && static_cast<size_t>(h.slugOffset) + h.slugLen <= bufSize)
            info.slug.assign(buf.data() + h.slugOffset, h.slugLen);
        if (h.textLen > 0 && static_cast<size_t>(h.textOffset) + h.textLen <= bufSize)
            info.text.assign(buf.data() + h.textOffset, h.textLen);
        if (info.text.empty())
            info.text = info.slug;
        out.push_back(std::move(info));
    }
    return out;
}

bool MarkdownWidget::scrollToAnchor(const std::string& slug)
{
    auto& data = _getData<MarkdownWidgetData>();
    // Normalize leading '#'.
    std::string key = slug;
    if (!key.empty() && key.front() == '#')
        key.erase(0, 1);
    auto it = data.anchorYCache.find(key);
    if (it == data.anchorYCache.end())
        return false;
    data.pendingScrollY = it->second;
    this->forceRasterDirty(Widget::BakeDirtyReason::eContentChanged);
    return true;
}

bool MarkdownWidget::copyCodeBlock(int index)
{
    if (index < 0)
        return false;
    this->_reparse();

    auto& data = _getData<MarkdownWidgetData>();
    const auto& tokens = data.doc.tokens;
    const char* base = data.doc.textBuffer.data();

    int codeBlockCount = 0;
    bool inTarget = false;
    std::string buffer;
    for (const MdToken& tok : tokens)
    {
        if (tok.hidden)
            continue;
        if (tok.kind == MdToken::EnterBlock && tok.blockType == MD_BLOCK_CODE)
        {
            if (codeBlockCount == index)
            {
                inTarget = true;
                buffer.clear();
            }
            codeBlockCount++;
            continue;
        }
        if (tok.kind == MdToken::LeaveBlock && tok.blockType == MD_BLOCK_CODE)
        {
            if (inTarget)
            {
                // Strip trailing newlines to match the copy button's
                // visual trim behavior.
                while (!buffer.empty() && (buffer.back() == '\n' || buffer.back() == '\r'))
                    buffer.pop_back();
                ImGui::SetClipboardText(buffer.c_str());
                return true;
            }
            continue;
        }
        if (!inTarget)
            continue;
        if (tok.kind == MdToken::Text)
        {
            buffer.append(base + tok.textOffset, tok.textLen);
        }
        else if (tok.kind == MdToken::SoftBreak || tok.kind == MdToken::HardBreak)
        {
            buffer.push_back('\n');
        }
    }
    return false;
}

void MarkdownWidget::_drawContent(float elapsedTime)
{
    auto& data = _getData<MarkdownWidgetData>();
    _reparse();

    float dpiScale = this->getDpiScale();
    if (std::abs(data.lastDpiScale - dpiScale) > 0.001f)
    {
        data.lastDpiScale = dpiScale;
        data.lastWidth = -1.0f;
        data.configDirty = true;
        this->forceWidthDirty(SizeDirtyReason::eSizeChanged);
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
    }

    if (data.configDirty)
    {
        StyleAccessors accessors;
        accessors.resolveColor = [this](StyleColorProperty p, uint32_t* out) {
            return this->_resolveStyleProperty(p, out);
        };
        accessors.resolveFloat = [this](StyleFloatProperty p, float* out) {
            return this->_resolveStyleProperty(p, out);
        };
        accessors.resolveString = [this](StyleStringProperty p, const char** out) {
            return this->_resolveStyleProperty(p, out);
        };
        accessors.resolveGroupColor = [this](const char* group, StyleColorProperty p, uint32_t* out) -> bool {
            const auto& rs = this->_getResolvedStyle();
            if (!rs) return false;
            size_t idx = rs->getStyleStateGroupIndex(group, "");
            return rs->resolveStyleProperty(idx, this->_getStyleState(), p, out);
        };
        accessors.resolveGroupFloat = [this](const char* group, StyleFloatProperty p, float* out) -> bool {
            const auto& rs = this->_getResolvedStyle();
            if (!rs) return false;
            size_t idx = rs->getStyleStateGroupIndex(group, "");
            return rs->resolveStyleProperty(idx, this->_getStyleState(), p, out);
        };
        accessors.resolveGroupString = [this](const char* group, StyleStringProperty p, const char** out) -> bool {
            const auto& rs = this->_getResolvedStyle();
            if (!rs) return false;
            size_t idx = rs->getStyleStateGroupIndex(group, "");
            return rs->resolveStyleProperty(idx, this->_getStyleState(), p, out);
        };
        accessors.pushFont = [this]() {
            this->_pushFont(*this, this->_isParentCanvasFrame());
        };

        buildRenderConfig(accessors, data.styleCache, data.cachedConfig);
        data.configDirty = false;
    }
    else
    {
        // Cached path: we still need to push the font so rendering uses
        // the widget's cascade-resolved face, matching the build path.
        this->_pushFont(*this, this->_isParentCanvasFrame());
    }

    RenderConfig& config = data.cachedConfig;
    // These live outside the cached config because the provider can change
    // without a style invalidation and the generation bumps on every reparse.
    config.assetProvider = data.assetProvider.get();
    config.documentGeneration = data.documentGeneration;
    if (data.assetProvider)
        data.assetProvider->tick();

    float width = this->getComputedContentWidth();
    float availableWidth = ImGui::GetContentRegionAvail().x;
    if (availableWidth > 0.0f)
    {
        width = width > 0.0f ? std::min(width, availableWidth) : availableWidth;
    }
    if (width <= 0.0f)
    {
        width = 1.0f;
    }

    // Carry hover/focus indices across frames; install the click callback
    // that forwards into the ovui callback machinery (which routes to
    // Python via wrapCallbackSetter when bound from the Python side).  The
    // anchor-navigate callback scrolls the viewport to the target slug AND
    // still fires onLinkClicked so user listeners observe the navigation.
    data.interaction.prevHoveredLinkIdx = data.interaction.hoveredLinkIdx;
    data.interaction.prevFocusedLinkIdx = data.interaction.focusedLinkIdx;
    data.interaction.onLinkClicked = [this](const std::string& url) {
        this->callLinkClickedFn(url);
    };
    data.interaction.onAnchorNavigate = [this](const std::string& url) {
        this->scrollToAnchor(url);
        // Also notify any user-registered link callback so external
        // listeners (e.g. analytics) still observe the activation.
        this->callLinkClickedFn(url);
    };

    // Consume a pending scroll request from a prior frame's
    // scrollToAnchor.  We apply this before rendering so the layout pass
    // sees the target viewport -- avoids a one-frame flash at the old
    // scroll position.
    if (data.pendingScrollY >= 0.0f)
    {
        ImGui::SetScrollY(data.pendingScrollY);
        data.pendingScrollY = -1.0f;
    }

    if (!data.imageResolver)
        data.imageResolver = std::make_unique<StbImageResolver>();
    data.imageResolver->setUrlProvider([this](const std::string& src) {
        return this->hasImageUrlProviderFn() ? this->callImageUrlProviderFn(src) : std::string();
    });

    if (!data.emojiAtlasTriedLoad)
    {
        data.emojiAtlasTriedLoad = true;
        auto tryLoad = [&](const std::filesystem::path& base) -> bool {
            auto atlas = base / "twemoji-atlas.png";
            auto manifest = base / "twemoji-atlas.json";
            if (std::filesystem::exists(atlas) && std::filesystem::exists(manifest))
            {
                data.emojiAtlas = std::make_unique<TwemojiAtlas>();
                if (!data.emojiAtlas->init(atlas.string().c_str(), manifest.string().c_str()))
                    data.emojiAtlas.reset();
                return data.emojiAtlas != nullptr;
            }
            return false;
        };
        if (!tryLoad("resources"))
        {
            namespace fs = std::filesystem;
            fs::path cwd = fs::current_path();
            for (int i = 0; i < 4 && !cwd.empty(); ++i)
            {
                if (tryLoad(cwd / "resources"))
                    break;
                cwd = cwd.parent_path();
            }
        }
    }

    float h = renderMarkdown(data.doc, config, width, &data.interaction, data.imageResolver.get(),
                             data.emojiAtlas ? data.emojiAtlas.get() : nullptr);

    // Mirror the per-frame anchor offsets into the persistent cache so
    // scrollToAnchor lookups succeed even between frames.  Later entries
    // overwrite earlier ones (same slug), matching scroll intent.
    for (const auto& kv : data.interaction.anchorOffsetsThisFrame)
        data.anchorYCache[kv.first] = kv.second;

    this->_popFont();

    if (h != data.lastHeight || width != data.lastWidth)
    {
        data.lastHeight = h;
        data.lastWidth = width;
        this->forceHeightDirty(SizeDirtyReason::eSizeChanged);
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
