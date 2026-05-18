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

#define _USE_MATH_DEFINES
#include <omni/ui/Container.h>
#include <omni/ui/FontAtlasTexture.h>
#include <omni/ui/Frame.h>
#include <omni/ui/Inspector.h>
#include <omni/ui/TreeView.h>

OMNIUI_NAMESPACE_OPEN_SCOPE

class InspectorMetrics
{
public:
    enum class Metrics
    {
        eComputedWidth = 0,
        eComputedHeight,
        eCount,
    };

    static InspectorMetrics& instance()
    {
        static InspectorMetrics instance;
        return instance;
    }

    void reset(Metrics m)
    {
        m_metrics[static_cast<size_t>(m)] = 0;
    }

    void bump(Metrics m)
    {
        if (this->isEnabled(m))
        {
            m_metrics[static_cast<size_t>(m)]++;
        }
    }

    size_t get(Metrics m)
    {
        return m_metrics[static_cast<size_t>(m)];
    }

    bool isEnabled(Metrics m) const
    {
        return m_metricEnabled[static_cast<size_t>(m)];
    }

    void setEnabled(Metrics m, bool enabled)
    {
        m_metricEnabled[static_cast<size_t>(m)] = enabled;
    }

public:
    InspectorMetrics(InspectorMetrics const&) = delete;
    void operator=(InspectorMetrics const&) = delete;

private:
    InspectorMetrics()
    {
    }

    bool m_metricEnabled[static_cast<size_t>(Metrics::eCount)];
    size_t m_metrics[static_cast<size_t>(Metrics::eCount)];
};

std::vector<std::shared_ptr<Widget>> Inspector::getChildren(const std::shared_ptr<Widget>& widget)
{
    if (!widget)
    {
        // we should probably complain?
        return {};
    }

    if (auto container = std::dynamic_pointer_cast<Container>(widget))
    {
        if (auto frame = std::dynamic_pointer_cast<Frame>(widget))
        {
            // Call build_fn
            frame->_populate();
        }

        return container->_getChildren();
    }
    else if (auto treeview = std::dynamic_pointer_cast<TreeView>(widget))
    {
        return treeview->_getChildren();
    }

    return {};
}

const std::shared_ptr<StyleContainer>& Inspector::getResolvedStyle(const std::shared_ptr<Widget>& widget)
{
    return widget->_getResolvedStyle();
}

void Inspector::beginComputedWidthMetric()
{
    InspectorMetrics::instance().reset(InspectorMetrics::Metrics::eComputedWidth);
    InspectorMetrics::instance().setEnabled(InspectorMetrics::Metrics::eComputedWidth, true);
}

void Inspector::bumpComputedWidthMetric()
{
    InspectorMetrics::instance().bump(InspectorMetrics::Metrics::eComputedWidth);
}

size_t Inspector::endComputedWidthMetric()
{
    InspectorMetrics::instance().setEnabled(InspectorMetrics::Metrics::eComputedWidth, false);
    return InspectorMetrics::instance().get(InspectorMetrics::Metrics::eComputedWidth);
}

void Inspector::beginComputedHeightMetric()
{
    InspectorMetrics::instance().reset(InspectorMetrics::Metrics::eComputedHeight);
    InspectorMetrics::instance().setEnabled(InspectorMetrics::Metrics::eComputedHeight, true);
}

void Inspector::bumpComputedHeightMetric()
{
    InspectorMetrics::instance().bump(InspectorMetrics::Metrics::eComputedHeight);
}

size_t Inspector::endComputedHeightMetric()
{
    InspectorMetrics::instance().setEnabled(InspectorMetrics::Metrics::eComputedHeight, false);
    return InspectorMetrics::instance().get(InspectorMetrics::Metrics::eComputedHeight);
}

std::vector<std::pair<std::string, uint32_t>> Inspector::getStoredFontAtlases()
{
    return FontAtlasTextureRegistry::instance()._getStoredFonts();
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
