/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "FloatSlider.h"


OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The drag widget that looks like a field but it's possible to change the value with dragging.
 */
class OMNIUI_CLASS_API FloatDrag : public FloatSlider
{
    OMNIUI_OBJECT(FloatDrag)

protected:
    /**
     * @brief Construct FloatDrag
     */
    OMNIUI_API
    FloatDrag(std::shared_ptr<AbstractValueModel> model = {});

private:
    /**
     * @brief Reimplemented. It has to run a very low level function to call the widget.
     */
    virtual bool _drawUnderlyingItem(double* value, double min, double max) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
