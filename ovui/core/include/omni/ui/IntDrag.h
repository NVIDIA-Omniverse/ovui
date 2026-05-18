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

#include "IntSlider.h"

#include <cstdint>
#include <memory>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The drag widget that looks like a field but it's possible to change the value with dragging.
 */
class OMNIUI_CLASS_API IntDrag : public IntSlider
{
    OMNIUI_OBJECT(IntDrag)

public:
    /**
     * @brief This property controls the steping speed on the drag, its float to enable slower speed,
     * but of course the value on the Control are still integer
     */
    OMNIUI_PROPERTY(float, step, DEFAULT, 0.1f, READ, getStep, WRITE, setStep);

protected:
    /**
     * @brief Constructs IntDrag
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    IntDrag(std::shared_ptr<AbstractValueModel> model = {});

private:
    /**
     * @brief Reimplemented. It has to run a very low level function to call the widget.
     */
    virtual bool _drawUnderlyingItem(int64_t* value, int64_t min, int64_t max) override;
};

class OMNIUI_CLASS_API UIntDrag : public UIntSlider
{
    OMNIUI_OBJECT(UIntDrag)

public:
    /**
     * @brief This property controls the steping speed on the drag, its float to enable slower speed,
     * but of course the value on the Control are still integer
     */
    OMNIUI_PROPERTY(float, step, DEFAULT, 0.1f, READ, getStep, WRITE, setStep);

protected:
    /**
     * @brief Constructs UIntDrag
     *
     * @param model The widget's model. If the model is not assigned, the default model is created.
     */
    OMNIUI_API
    UIntDrag(std::shared_ptr<AbstractValueModel> model = {});

private:
    /**
     * @brief Reimplemented. It has to run a very low level function to call the widget.
     */
    virtual bool _drawUnderlyingItem(uint64_t* value, uint64_t min, uint64_t max) override;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
