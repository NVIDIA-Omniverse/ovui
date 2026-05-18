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

#include "Widget.h"

#include <memory>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief The container is an abstract widget that can hold one or several child widgets.
 *
 * The user is allowed to add or replace child widgets. If the widget has multiple children internally (like Button) and
 * the user doesn't have access to them, it's not necessary to use this class.
 */
class OMNIUI_CLASS_API Container : public Widget
{
public:
    OMNIUI_API
    ~Container() override;

    /**
     * @brief Adds widget to this container in a manner specific to the container. If it's allowed to have one
     * sub-widget only, it will be overwriten.
     */
    virtual void addChild(std::shared_ptr<Widget> widget);

    /**
     * @brief Removes the container items from the container.
     */
    virtual void clear(){}

protected:
    friend class Inspector;
    struct ContainerData;

    OMNIUI_API
    Container(ContainerData* data = nullptr);

    /**
     * @brief Return the list of children for the Container, only used by Inspector and for debug/inspection
     * perspective.
     */
    OMNIUI_API
    virtual std::vector<std::shared_ptr<Widget>> _getChildren() const { return {}; }
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
