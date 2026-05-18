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

#include "FontHelper.h"
#include "ValueModelHelper.h"

#include <memory>
#include <string>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief A progressbar is a classic widget for showing the progress of an operation.
 */
class OMNIUI_CLASS_API ProgressBar : public Widget, public ValueModelHelper, public FontHelper
{
    OMNIUI_OBJECT(ProgressBar)

public:
    OMNIUI_API
    ~ProgressBar() override;

    /**
     * @brief Reimplemented the method to indicate the height hint that represents the preferred size of the widget.
     *
     * @see Widget::setComputedContentHeight
     */
    OMNIUI_API
    void setComputedContentHeight(float height) override;

    /**
     * @brief Reimplemented. Something happened with the style or with the parent style. We need to gerenerate the
     * cache.
     */
    OMNIUI_API
    void onStyleUpdated() override;

    /**
     * @brief Reimplemented the method from ValueModelHelper that is called when the model is changed.
     */
    OMNIUI_API
    void onModelUpdated() override;

protected:
    /**
     * @brief Construct ProgressBar
     *
     * @param model The model that determines if the button is checked.
     */
    OMNIUI_API
    ProgressBar(std::shared_ptr<AbstractValueModel> model = {});

    /**
     * @brief Reimplemented the rendering code of the widget.
     *
     * @see Widget::_drawContent
     */
    OMNIUI_API
    void _drawContent(float elapsedTime) override;

private:
    struct ProgressBarData;

    void _drawUnderlyingItem();
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
