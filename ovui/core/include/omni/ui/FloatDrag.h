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
