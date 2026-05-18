/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
#include "Math.h"

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * - A model that holds projection and view matrices
 */
class OMNIUI_SCENE_CLASS_API CameraModel : public AbstractManipulatorModel
{
public:
    /**
     * @brief Initialize the camera with the given projection/view matrices
     */
    OMNIUI_SCENE_API
    CameraModel(const Matrix44& projection, const Matrix44& view);

    // TODO: perspective/ortho with origin, direction, fov

    OMNIUI_SCENE_API
    ~CameraModel() override;

    /**
     * @brief Returns the items that represents the identifier.
     */
    OMNIUI_SCENE_API
    std::shared_ptr<const AbstractManipulatorItem> getItem(const std::string& identifier) override;

    /**
     * @brief Returns the float values of the item.
     */
    OMNIUI_SCENE_API
    std::vector<Float> getAsFloats(const std::shared_ptr<const AbstractManipulatorItem>& item) override;

    /**
     * @brief Returns the int values of the item.
     */
    OMNIUI_SCENE_API
    std::vector<int64_t> getAsInts(const std::shared_ptr<const AbstractManipulatorItem>& item) override;

    /**
     * @brief Sets the float values of the item.
     */
    OMNIUI_SCENE_API
    void setFloats(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<Float> value) override;

    /**
     * @brief Sets the int values of the item.
     */
    OMNIUI_SCENE_API
    void setInts(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<int64_t> value) override;

    /**
     * @brief The camera projection matrix.
     */
    OMNIUI_SCENE_API
    virtual Matrix44 getProjection() const;

    /**
     * @brief The camera view matrix.
     */
    OMNIUI_SCENE_API
    virtual Matrix44 getView() const;

    /**
     * @brief Set the camera projection matrix.
     */
    OMNIUI_SCENE_API
    virtual void setProjection(const Matrix44& projection);

    /**
     * @brief Set the camera view matrix.
     */
    OMNIUI_SCENE_API
    virtual void setView(const Matrix44& view);


private:
    struct CameraModelData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
