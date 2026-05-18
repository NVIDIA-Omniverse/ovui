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

#include "AbstractManipulatorModel.h"

#include <memory>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The ManipulatorModelHelper class provides the basic model functionality.
 *
 * TODO: It's very similar to ValueModelHelper. We need to template it. It's not templated now because we need a good
 * solution for pybind11. Pybind11 doesn't like templated classes.
 */
class OMNIUI_SCENE_CLASS_API ManipulatorModelHelper
{
public:
    OMNIUI_SCENE_API
    virtual ~ManipulatorModelHelper();

    /**
     * @brief Called by the model when the model value is changed. The class should react to the changes.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is changed.
     */
    OMNIUI_SCENE_API
    virtual void onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item) = 0;

    /**
     * @brief Set the current model.
     */
    OMNIUI_SCENE_API
    virtual void setModel(const std::shared_ptr<AbstractManipulatorModel>& model);

    /**
     * @brief Returns the current model.
     */
    OMNIUI_SCENE_API
    virtual const std::shared_ptr<AbstractManipulatorModel>& getModel() const;

protected:
    OMNIUI_SCENE_API
    ManipulatorModelHelper(const std::shared_ptr<AbstractManipulatorModel>& model);

private:
    std::shared_ptr<AbstractManipulatorModel> m_model = {};
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
