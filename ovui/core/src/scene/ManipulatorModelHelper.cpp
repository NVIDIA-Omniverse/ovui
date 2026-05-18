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

#include <omni/ui/scene/AbstractManipulatorModel.h>
#include <omni/ui/scene/ManipulatorModelHelper.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

ManipulatorModelHelper::ManipulatorModelHelper(const std::shared_ptr<AbstractManipulatorModel>& model)
    : m_model{ model }
{
    if (m_model)
    {
        m_model->subscribe(this);
    }
}

ManipulatorModelHelper::~ManipulatorModelHelper()
{
    if (m_model)
    {
        m_model->unsubscribe(this);
    }
}

void ManipulatorModelHelper::setModel(const std::shared_ptr<AbstractManipulatorModel>& model)
{
    if (m_model != model)
    {
        // Unsubscribe from the previous model.
        if (m_model)
        {
            m_model->unsubscribe(this);
        }

        m_model = model;

        // Subscribe to the new model.
        if (m_model)
        {
            m_model->subscribe(this);
        }

        // Update the current representation.
        this->onModelUpdated(nullptr);
    }
}

const std::shared_ptr<AbstractManipulatorModel>& ManipulatorModelHelper::getModel() const
{
    return m_model;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
