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

#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>
#include <unordered_set>
#include <vector>

OMNIUI_NAMESPACE_OPEN_SCOPE

class AbstractValueModel;
class ItemModelHelper;

/**
 * @brief The central component of the item widget. It is the application's dynamic data structure, independent of the
 * user interface, and it directly manages the nested data. It follows closely model-view pattern. It's abstract, and it
 * defines the standard interface to be able to interoperate with the components of the model-view architecture. It is
 * not supposed to be instantiated directly. Instead, the user should subclass it to create a new model.
 *
 * The overall architecture is described in the following drawing:
 *
 * \internal
 *
 *     # Data is inside the model (cache)              * # Data is outside the model (mirror)
 *     |----------------------------|                  * |-------------------|
 *     | AbstractItemModel          |                  * | AbstractItemModel |
 *     |      |------- Data -------||                  * |                   |                    |----- Data -----|
 *     |      |  |- Item1          || <-- AbstractItem * |                   | -- AbstractItem -->|  |- Item1      |
 *     |      |  | |- SubItem1     || <-- AbstractItem * |                   | -- AbstractItem -->|  | |- Sub1     |
 *     |      |  | | |- SubSubItem1|| <-- AbstractItem * |                   | -- AbstractItem -->|  | | |- SubSub1|
 *     |      |  | | |- SubSubItem2|| <-- AbstractItem * |                   | -- AbstractItem -->|  | | |- SubSub2|
 *     |      |  | |- SubItem2     || <-- AbstractItem * |                   | -- AbstractItem -->|  | |- Sub2     |
 *     |      |  |- Item2          || <-- AbstractItem * |                   | -- AbstractItem -->|  |- Item2      |
 *     |      |    |- SubItem3     || <-- AbstractItem * |                   | -- AbstractItem -->|    |- Sub3     |
 *     |      |    |- SubItem4     || <-- AbstractItem * |                   | -- AbstractItem -->|    |- Sub4     |
 *     |      |--------------------||                  * |                   |                    |----------------|
 *     |----------------------------|                  * |-------------------|
 *                   |                                 *            |
 *                   |                                 *            |
 *     |----------------------------|                  * |----------------------------|
 *     | ItemModelHelper            |                  * | ItemModelHelper            |
 *     ||--------------------------||                  * ||--------------------------||
 *     || Root                     ||                  * || Root                     ||
 *     || |- World                 ||                  * || |- World                 ||
 *     || |  |- Charater           ||                  * || |  |- Charater           ||
 *     || |  |  |- Head            ||                  * || |  |  |- Head            ||
 *     || |  |  |- Body            ||                  * || |  |  |- Body            ||
 *     || |  |- Sphere             ||                  * || |  |- Sphere             ||
 *     || |- Materials             ||                  * || |- Materials             ||
 *     ||    |- GGX                ||                  * ||    |- GGX                ||
 *     ||    |- GTR                ||                  * ||    |- GTR                ||
 *     ||--------------------------||                  * ||--------------------------||
 *     |----------------------------|                  * |----------------------------|
 *
 * \endinternal
 *
 * The item model doesn't return the data itself. Instead, it returns the value model that can contain any data type and
 * supports callbacks. Thus the client of the model can track the changes in both the item model and any value it holds.
 *
 * From any item, the item model can get both the value model and the nested items. Therefore, the model is flexible to
 * represent anything from color to complicated tree-table construction.
 *
 * TODO: We can see there is a lot of methods that are similar to the AbstractValueModel. We need to template them.
 */
class OMNIUI_CLASS_API AbstractItemModel
{
public:
    /**
     * @brief The object that is associated with the data entity of the AbstractItemModel.
     *
     * The item should be created and stored by the model implementation. And can contain any data in it. Another option
     * would be to use it as a raw pointer to the data. In any case it's the choice of the model how to manage this
     * class.
     */
    class AbstractItem
    {
    public:
        virtual ~AbstractItem() = default;
    };

    OMNIUI_API
    virtual ~AbstractItemModel();

    // We assume that all the operations with the model should be performed with smart pointers because it will register
    // subscription. If the object is copied or moved, it will break the subscription.
    // No copy
    AbstractItemModel(const AbstractItemModel&) = delete;
    // No copy-assignment
    AbstractItemModel& operator=(const AbstractItemModel&) = delete;
    // No move constructor and no move-assignments are allowed because of 12.8 [class.copy]/9 and 12.8 [class.copy]/20
    // of the C++ standard

    /**
     * @brief Returns the vector of items that are nested to the given parent item.
     *
     * @param id The item to request children from. If it's null, the children of root will be returned.
     */
    OMNIUI_API
    virtual std::vector<std::shared_ptr<const AbstractItem>> getItemChildren(
        const std::shared_ptr<const AbstractItem>& parentItem = nullptr) = 0;

    /**
     * @brief Returns true if the item can have children. In this way the delegate usually draws +/- icon.
     *
     * @param id The item to request children from. If it's null, the children of root will be returned.
     */
    OMNIUI_API
    virtual bool canItemHaveChildren(const std::shared_ptr<const AbstractItem>& parentItem = nullptr);

    /**
     * @brief Creates a new item from the value model and appends it to the list of the children of the given item.
     */
    OMNIUI_API
    virtual std::shared_ptr<const AbstractItem> appendChildItem(const std::shared_ptr<const AbstractItem>& parentItem,
                                                                std::shared_ptr<AbstractValueModel> model);

    /**
     * @brief Removes the item from the model.
     *
     * There is no parent here because we assume that the reimplemented model deals with its data and can figure out how
     * to remove this item.
     */
    OMNIUI_API
    virtual void removeItem(const std::shared_ptr<const AbstractItem>& item);

    /**
     * @brief Returns the number of columns this model item contains.
     */
    OMNIUI_API
    virtual size_t getItemValueModelCount(const std::shared_ptr<const AbstractItem>& item = nullptr) = 0;

    /**
     * @brief Get the value model associated with this item.
     *
     * @param item The item to request the value model from. If it's null, the root value model will be returned.
     * @param index The column number to get the value model.
     */
    OMNIUI_API
    virtual std::shared_ptr<AbstractValueModel> getItemValueModel(const std::shared_ptr<const AbstractItem>& item = nullptr,
                                                                  size_t index = 0) = 0;

    /**
     * @brief Called when the user starts the editing. If it's a field, this method is called when the user activates
     * the field and places the cursor inside.
     */
    OMNIUI_API
    virtual void beginEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Called when the user finishes the editing. If it's a field, this method is called when the user presses
     * Enter or selects another field for editing. It's useful for undo/redo.
     */
    OMNIUI_API
    virtual void endEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Called to determine if the model can perform drag and drop to the given item. If this method returns
     * false, the widget shouldn't highlight the visual element that represents this item.
     */
    OMNIUI_API
    virtual bool dropAccepted(const std::shared_ptr<const AbstractItem>& itemTarget,
                              const std::shared_ptr<const AbstractItem>& itemSource,
                              int32_t dropLocation = -1);

    /**
     * @brief Called to determine if the model can perform drag and drop of the given string to the given item. If this
     * method returns false, the widget shouldn't highlight the visual element that represents this item.
     */
    OMNIUI_API
    virtual bool dropAccepted(const std::shared_ptr<const AbstractItem>& itemTarget,
                              const char* source,
                              int32_t dropLocation = -1);

    /**
     * @brief Called when the user droped one item to another.
     *
     * @note Small explanation why the same default value is declared in multiple places. We use the default value to be
     * compatible with the previous API and especially with Stage 2.0. Thr signature in the old Python API is: `def
     * drop(self, target_item, source)`. So when the user drops something over the item, we call 2-args `drop(self,
     * target_item, source)`, see `PyAbstractItemModel::drop`, and to call 2-args drop PyBind11 needs default value in
     * both here and Python implementation of `AbstractItemModel.drop`. W also set the default value in
     * `pybind11::class_<AbstractItemModel>.def("drop")` and PyBind11 uses it when the user calls the C++ binding of
     * AbstractItemModel from the python code.
     *
     * @see PyAbstractItemModel::drop
     */
    OMNIUI_API
    virtual void drop(const std::shared_ptr<const AbstractItem>& itemTarget,
                      const std::shared_ptr<const AbstractItem>& itemSource,
                      int32_t dropLocation = -1);

    /**
     * @brief Called when the user droped a string to the item.
     */
    OMNIUI_API
    virtual void drop(const std::shared_ptr<const AbstractItem>& itemTarget,
                      const char* source,
                      int32_t dropLocation = -1);

    /**
     * @brief Returns Multipurpose Internet Mail Extensions (MIME) for drag and drop.
     */
    OMNIUI_API
    virtual std::string getDragMimeData(const std::shared_ptr<const AbstractItem>& item);

    /**
     * @brief Subscribe the ItemModelHelper widget to the changes of the model.
     *
     * We need to use regular pointers because we subscribe in the constructor of the widget and unsubscribe in the
     * destructor. In constructor smart pointers are not available. We also don't allow copy and move of the widget.
     *
     * TODO: It's similar to AbstractValueModel::subscribe, we can template it.
     */
    OMNIUI_API
    void subscribe(ItemModelHelper* widget);

    /**
     * @brief Unsubscribe the ItemModelHelper widget from the changes of the model.
     *
     * TODO: It's similar to AbstractValueModel::unsubscribe, we can template it.
     */
    OMNIUI_API
    void unsubscribe(ItemModelHelper* widget);

    /**
     * @brief Adds the function that will be called every time the value changes.
     *
     * @return The id of the callback that is used to remove the callback.
     *
     * TODO: It's similar to AbstractValueModel::addItemChangedFn, we can template it.
     */
    OMNIUI_API
    uint32_t addItemChangedFn(std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn);

    /**
     * @brief Remove the callback by its id.
     *
     * @param id The id that addValueChangedFn returns.
     *
     * TODO: It's similar to AbstractValueModel::removeItemChangedFn, we can template it.
     */
    OMNIUI_API
    void removeItemChangedFn(uint32_t id);

    /**
     * @brief Adds the function that will be called every time the user starts the editing.
     *
     * @return The id of the callback that is used to remove the callback.
     */
    OMNIUI_API
    uint32_t addBeginEditFn(std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn);

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
    uint32_t addEndEditFn(std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn);

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
    void processBeginEditCallbacks(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

    /**
     * @brief Called by the widget when the user finishes editing. It calls endEdit and the callbacks.
     */
    OMNIUI_API
    void processEndEditCallbacks(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item);

protected:
    /**
     * @brief Constructs AbstractItemModel
     */
    OMNIUI_API
    AbstractItemModel();

    /**
     * @brief Called when any data of the model is changed. It will notify the subscribed widgets.
     *
     * @param item The item in the model that is changed. If it's NULL, the root is chaged.
     */
    OMNIUI_API
    void _itemChanged(const std::shared_ptr<const AbstractItem>& item);

    // All the widgets who use this model. See description of subscribe for the information why it's regular pointers.
    // TODO: we can use m_callbacks for subscribe-unsubscribe. But in this way it's nesessary to keep widget-id map.
    // When the _valueChanged code will be more complicated, we need to do it. Now it's simple enought and m_widgets
    // stays here.
    std::unordered_set<ItemModelHelper*> m_widgets;

    // All the callbacks.
    std::vector<std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>> m_itemChangedCallbacks;
    // Callbacks that called when the user starts the editing.
    std::vector<std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>> m_beginEditCallbacks;
    // Callbacks that called when the user finishes the editing.
    std::vector<std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>> m_endEditCallbacks;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
