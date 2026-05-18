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

#include "AbstractContainer.h"
#include "AbstractGesture.h"
#include "AbstractManipulatorModel.h"
#include "ManipulatorModelHelper.h"

#include <memory>
#include <vector>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class ManipulatorGesture;

/**
 * @brief The base object for the custom manipulators
 */
class OMNIUI_SCENE_CLASS_API Manipulator : public AbstractContainer, public ManipulatorModelHelper
{
    OMNIUI_SCENE_OBJECT(Manipulator);

public:
    OMNIUI_SCENE_API
    virtual ~Manipulator();

    /**
     * @brief Called when Manipulator is dirty to build the content.
     */
    OMNIUI_SCENE_API
    virtual void onBuild();

    /**
     * @brief Make Manipulator dirty so onBuild will be executed in
     * _preDrawContent
     */
    OMNIUI_SCENE_API
    void invalidate();

    /**
     * @brief Called by the model when the model value is changed. The class should react to the changes.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is changed.
     */
    OMNIUI_SCENE_API
    void onModelUpdated(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>& item) override;

    /**
     * @brief All the gestures assigned to this manipulator
     */
    OMNIUI_SCENE_API
    const std::vector<std::shared_ptr<ManipulatorGesture>>& getGestures() const;

    /**
     * @brief Replace the gestures of the manipulator
     */
    OMNIUI_SCENE_API
    void setGestures(std::vector<std::shared_ptr<ManipulatorGesture>> gestures);

    /**
     * @brief Add a single gesture to the manipulator
     */
    OMNIUI_SCENE_API
    void addGesture(std::shared_ptr<ManipulatorGesture> gesture);

    /**
     * @brief Called when Manipulator is dirty to build the content. It's
     * another way to build the manipulator's content on the case the user
     * doesn't want to reimplement the class.
     */
    OMNIUI_CALLBACK(OnBuild, void, Manipulator const*);

protected:
    /**
     * @brief Constructor
     */
    OMNIUI_SCENE_API
    Manipulator();

    OMNIUI_SCENE_API
    void _preDrawContent(
        const MouseInput& input, const Matrix44& projection, const Matrix44& view, float width, float height) override;

    OMNIUI_SCENE_API
    void _drawContent(const Matrix44& projection, const Matrix44& view) override;

    OMNIUI_SCENE_API
    void _postDrawContent(const Matrix44& projection, const Matrix44& view) override;

    /**
     * @brief Process the ManipulatorGestures that can be casted to the given type
     */
    template <class Gesture>
    void _processGesture(GestureState state, const std::shared_ptr<AbstractGesture::GesturePayload>& gesturePayload)
    {
        if (!gesturePayload)
        {
            return;
        }

        for (auto& gesture : getGestures())
        {
            auto castedGesture = std::dynamic_pointer_cast<Gesture>(gesture);
            if (castedGesture)
            {
                castedGesture->_processWithGesturePayload(this, state, gesturePayload);
            }
        }
    }


private:
    struct ManipulatorData;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
