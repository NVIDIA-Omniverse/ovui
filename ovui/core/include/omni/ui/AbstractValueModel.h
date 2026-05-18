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

#include "Api.h"

#include <cstdint>
#include <functional>
#include <string>
#include <unordered_set>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class ValueModelHelper;

class OMNIUI_CLASS_API AbstractValueModel
{
public:
    OMNIUI_API
    virtual ~AbstractValueModel();

    // We assume that all the operations with the model should be performed with smart pointers because it will register
    // subscription. If the object is copied or moved, it will break the subscription.
    // No copy
    AbstractValueModel(const AbstractValueModel&) = delete;
    // No copy-assignment
    AbstractValueModel& operator=(const AbstractValueModel&) = delete;
    // No move constructor and no move-assignments are allowed because of 12.8 [class.copy]/9 and 12.8 [class.copy]/20
    // of the C++ standard

    /**
     * @brief Return the bool representation of the value.
     */
    virtual bool getValueAsBool() const = 0;

    /**
     * @brief Return the float representation of the value.
     */
    virtual double getValueAsFloat() const = 0;

    /**
     * @brief Return the int representation of the value.
     */
    virtual int64_t getValueAsInt() const = 0;

    /**
     * @brief Return the string representation of the value.
     */
    virtual std::string getValueAsString() const = 0;

    /**
     * @brief A helper that calls the correct getValueXXX method.
     */
    template <class T>
    OMNIUI_API T getValue() const;

    /**
     * @brief Called when the user starts the editing. If it's a field, this method is called when the user activates
     * the field and places the cursor inside. This method should be reimplemented.
     */
    OMNIUI_API
    virtual void beginEdit();

    /**
     * @brief Called when the user finishes the editing. If it's a field, this method is called when the user presses
     * Enter or selects another field for editing. It's useful for undo/redo. This method should be reimplemented.
     */
    OMNIUI_API
    virtual void endEdit();

    /**
     * @brief Set the value.
     */
    virtual void setValue(bool value) = 0;
    virtual void setValue(double value) = 0;
    virtual void setValue(int64_t value) = 0;
    virtual void setValue(std::string value) = 0;

    /**
     * @brief Subscribe the ValueModelHelper widget to the changes of the model.
     *
     * We need to use regular pointers because we subscribe in the constructor of the widget and unsubscribe in the
     * destructor. In constructor smart pointers are not available. We also don't allow copy and move of the widget.
     */
    OMNIUI_API
    void subscribe(ValueModelHelper* widget);

    /**
     * @brief Unsubscribe the ValueModelHelper widget from the changes of the model.
     */
    OMNIUI_API
    void unsubscribe(ValueModelHelper* widget);

    /**
     * @brief Adds the function that will be called every time the value changes.
     *
     * @return The id of the callback that is used to remove the callback.
     */
    OMNIUI_API
    uint32_t addValueChangedFn(std::function<void(const AbstractValueModel*)> fn);

    /**
     * @brief Remove the callback by its id.
     *
     * @param id The id that addValueChangedFn returns.
     */
    OMNIUI_API
    void removeValueChangedFn(uint32_t id);

    /**
     * @brief Adds the function that will be called every time the user starts the editing.
     *
     * @return The id of the callback that is used to remove the callback.
     */
    OMNIUI_API
    uint32_t addBeginEditFn(std::function<void(const AbstractValueModel*)> fn);

    /**
     * @brief Remove the callback by its id.
     *
     * @param id The id that addBeginEditFn returns.
     */
    OMNIUI_API
    void removeBeginEditFn(uint32_t id);

    /**
     * @brief Adds the function that will be called every time the user finishes the editing.
     *
     * @return The id of the callback that is used to remove the callback.
     */
    OMNIUI_API
    uint32_t addEndEditFn(std::function<void(const AbstractValueModel*)> fn);

    /**
     * @brief Remove the callback by its id.
     *
     * @param id The id that addEndEditFn returns.
     */
    OMNIUI_API
    void removeEndEditFn(uint32_t id);

    /**
     * @brief Called by the widget when the user starts editing. It calls beginEdit and the callbacks.
     */
    OMNIUI_API
    void processBeginEditCallbacks();

    /**
     * @brief Called by the widget when the user finishes editing. It calls endEdit and the callbacks.
     */
    OMNIUI_API
    void processEndEditCallbacks();

protected:
    friend class AbstractMultiField;

    /**
     * @brief Constructs AbstractValueModel
     */
    OMNIUI_API
    AbstractValueModel();

    /**
     * @brief Called when any data of the model is changed. It will notify the subscribed widgets.
     */
    OMNIUI_API
    void _valueChanged();

    // All the widgets who use this model. See description of subscribe for the information why it's regular pointers.
    // TODO: we can use m_callbacks for subscribe-unsubscribe. But in this way it's nesessary to keep widget-id map.
    // When the _valueChanged code will be more complicated, we need to do it. Now it's simple enought and m_widgets
    // stays here.
    std::unordered_set<ValueModelHelper*> m_widgets;

    // Callbacks that called when the value is changed.
    std::vector<std::function<void(const AbstractValueModel*)>> m_valueChangedCallbacks;
    // Callbacks that called when the user starts the editing.
    std::vector<std::function<void(const AbstractValueModel*)>> m_beginEditCallbacks;
    // Callbacks that called when the user finishes the editing.
    std::vector<std::function<void(const AbstractValueModel*)>> m_endEditCallbacks;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
