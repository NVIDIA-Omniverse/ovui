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

#include <omni/ui/Subscription.h>

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/bind/BindAbstractItemModel.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <string>
#include <utility>
#include <vector>

using namespace pybind11;

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Class-helper that redirects all the abstract methods to python so that it's possible to reimplement this class
 * in python.
 */
class PyAbstractItemModel : public AbstractItemModel
{
public:
    using AbstractItemModel::_itemChanged;

    ~PyAbstractItemModel() override = default;

    // Redirect all the abstract methods to python.
    std::vector<std::shared_ptr<const AbstractItem>> getItemChildren(
        const std::shared_ptr<const AbstractItem>& parentItem) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(
            std::vector<std::shared_ptr<const AbstractItem>>, AbstractItemModel, get_item_children, parentItem);

        return {};
    }

    bool canItemHaveChildren(const std::shared_ptr<const AbstractItem>& parentItem) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(
            bool, AbstractItemModel, AbstractItemModel::canItemHaveChildren, can_item_have_children, parentItem);

        return false;
    }

    std::shared_ptr<const AbstractItem> appendChildItem(const std::shared_ptr<const AbstractItem>& parentItem,
                                                        std::shared_ptr<AbstractValueModel> model) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(std::shared_ptr<const AbstractItem>, AbstractItemModel,
                                  AbstractItemModel::appendChildItem, append_child_item, parentItem, model);

        return nullptr;
    }

    void removeItem(const std::shared_ptr<const AbstractItem>& item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemModel, AbstractItemModel::removeItem, remove_item, item);
    }

    size_t getItemValueModelCount(const std::shared_ptr<const AbstractItem>& item = nullptr) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(uint8_t, AbstractItemModel, get_item_value_model_count, item);

        return 0;
    }

    std::shared_ptr<AbstractValueModel> getItemValueModel(const std::shared_ptr<const AbstractItem>& item = nullptr,
                                                          size_t index = 0) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(
            std::shared_ptr<AbstractValueModel>, AbstractItemModel, get_item_value_model, item, index);

        return {};
    }

    void beginEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemModel, beginEdit, begin_edit, item);
    }

    void endEdit(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemModel, endEdit, end_edit, item);
    }

    bool dropAccepted(const std::shared_ptr<const AbstractItem>& itemTarget,
                      const std::shared_ptr<const AbstractItem>& itemSource,
                      int32_t dropLocation = -1) override
    {
        if (dropLocation < 0)
        {
            OMNIUI_PYBIND_OVERLOAD_VA(
                bool, AbstractItemModel, AbstractItemModel::dropAccepted, drop_accepted, itemTarget, itemSource);
        }
        else
        {
            OMNIUI_PYBIND_OVERLOAD_VA(bool, AbstractItemModel, AbstractItemModel::dropAccepted, drop_accepted,
                                      itemTarget, itemSource, dropLocation);
        }
    }

    bool dropAccepted(const std::shared_ptr<const AbstractItem>& itemTarget,
                      const char* source,
                      int32_t dropLocation = -1) override
    {
        if (dropLocation < 0)
        {
            OMNIUI_PYBIND_OVERLOAD_VA(
                bool, AbstractItemModel, AbstractItemModel::dropAccepted, drop_accepted, itemTarget, source);
        }
        else
        {
            OMNIUI_PYBIND_OVERLOAD_VA(bool, AbstractItemModel, AbstractItemModel::dropAccepted, drop_accepted,
                                      itemTarget, source, dropLocation);
        }
    }

    void drop(const std::shared_ptr<const AbstractItem>& itemTarget,
              const std::shared_ptr<const AbstractItem>& itemSource,
              int32_t dropLocation = -1) override
    {
        if (dropLocation < 0)
        {
            OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemModel, AbstractItemModel::drop, drop, itemTarget, itemSource);
        }
        else
        {
            OMNIUI_PYBIND_OVERLOAD_VA(
                void, AbstractItemModel, AbstractItemModel::drop, drop, itemTarget, itemSource, dropLocation);
        }
    }

    void drop(const std::shared_ptr<const AbstractItem>& itemTarget, const char* source, int32_t dropLocation = -1) override
    {
        if (dropLocation < 0)
        {
            OMNIUI_PYBIND_OVERLOAD_VA(void, AbstractItemModel, AbstractItemModel::drop, drop, itemTarget, source);
        }
        else
        {
            OMNIUI_PYBIND_OVERLOAD_VA(
                void, AbstractItemModel, AbstractItemModel::drop, drop, itemTarget, source, dropLocation);
        }
    }

    std::string getDragMimeData(const std::shared_ptr<const AbstractItem>& item) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(
            std::string, AbstractItemModel, AbstractItemModel::getDragMimeData, get_drag_mime_data, item);

        return {};
    }
};

std::shared_ptr<omni::ui::Subscription> createSubscription(
    std::shared_ptr<AbstractItemModel>& self,
    std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn,
    uint32_t (AbstractItemModel::*ptrAdd)(
        std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>),
    void (AbstractItemModel::*ptrRemove)(uint32_t id))
{
    auto callbackId = (*self.get().*ptrAdd)(wrapPythonCallback(std::move(fn)));
    std::weak_ptr<AbstractItemModel> weakPtr = self;

    return std::make_shared<omni::ui::Subscription>(
        [=]()
        {
            auto ptr = weakPtr.lock();
            if (ptr)
            {
                (*ptr.get().*ptrRemove)(callbackId);
            }
        });
}

OMNIUI_NAMESPACE_CLOSE_SCOPE

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAbstractItemModel(module& m)
{
    constexpr const char* abstractItemModelDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractItemModel);
    static constexpr char abstractItemModelConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(AbstractItemModel, AbstractItemModel);
    static constexpr char itemDescription[] = R"(
        The object that is associated with the data entity of the AbstractItemModel.
    )";

    class_<AbstractItemModel::AbstractItem, std::shared_ptr<AbstractItemModel::AbstractItem>>(
        m, "AbstractItem", itemDescription)
        .def(init<>());

    class_<AbstractItemModel, PyAbstractItemModel, std::shared_ptr<AbstractItemModel>>(
        m, "AbstractItemModel", abstractItemModelDoc)
        .def(init<>(), abstractItemModelConstructorDoc)
        .def("get_item_children", &AbstractItemModel::getItemChildren, arg("parentItem") = nullptr,
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractItemModel_getItemChildren)
        .def("can_item_have_children", &AbstractItemModel::canItemHaveChildren, arg("parentItem") = nullptr,
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractItemModel_canItemHaveChildren)
        .def("append_child_item", &AbstractItemModel::appendChildItem, arg("parentItem"), arg("model"),
             return_value_policy::reference, OMNIUI_PYBIND_DOC_AbstractItemModel_appendChildItem)
        .def("remove_item", &AbstractItemModel::removeItem, arg("item"), OMNIUI_PYBIND_DOC_AbstractItemModel_removeItem)
        .def("get_item_value_model_count", &AbstractItemModel::getItemValueModelCount, arg("item") = nullptr,
             OMNIUI_PYBIND_DOC_AbstractItemModel_getItemValueModelCount)
        .def("get_item_value_model", &AbstractItemModel::getItemValueModel, arg("item") = nullptr, arg("column_id") = 0,
             OMNIUI_PYBIND_DOC_AbstractItemModel_getItemValueModel)
        .def("begin_edit", &AbstractItemModel::beginEdit, arg("item"), OMNIUI_PYBIND_DOC_AbstractItemModel_beginEdit)
        .def("end_edit", &AbstractItemModel::endEdit, arg("item"), OMNIUI_PYBIND_DOC_AbstractItemModel_endEdit)
        .def("drop_accepted",
             (bool (AbstractItemModel::*)(const std::shared_ptr<const AbstractItemModel::AbstractItem>&,
                                          const std::shared_ptr<const AbstractItemModel::AbstractItem>&, int32_t)) &
                 AbstractItemModel::dropAccepted,
             arg("item_tagget"), arg("item_source"), arg("drop_location") = -1,
             OMNIUI_PYBIND_DOC_AbstractItemModel_dropAccepted)
        .def("drop_accepted",
             (bool (AbstractItemModel::*)(
                 const std::shared_ptr<const AbstractItemModel::AbstractItem>&, const char*, int32_t)) &
                 AbstractItemModel::dropAccepted,
             arg("item_tagget"), arg("source"), arg("drop_location") = -1,
             OMNIUI_PYBIND_DOC_AbstractItemModel_dropAccepted01)
        .def("drop",
             (void (AbstractItemModel::*)(const std::shared_ptr<const AbstractItemModel::AbstractItem>&,
                                          const std::shared_ptr<const AbstractItemModel::AbstractItem>&, int32_t)) &
                 AbstractItemModel::drop,
             arg("item_tagget"), arg("item_source"), arg("drop_location") = -1, OMNIUI_PYBIND_DOC_AbstractItemModel_drop)
        .def("drop",
             (void (AbstractItemModel::*)(
                 const std::shared_ptr<const AbstractItemModel::AbstractItem>&, const char*, int32_t)) &
                 AbstractItemModel::drop,
             arg("item_tagget"), arg("source"), arg("drop_location") = -1, OMNIUI_PYBIND_DOC_AbstractItemModel_drop01)
        .def("get_drag_mime_data", &AbstractItemModel::getDragMimeData, arg("item") = nullptr,
             OMNIUI_PYBIND_DOC_AbstractItemModel_getDragMimeData)
        .def("_item_changed", &PyAbstractItemModel::_itemChanged)
        .def("add_item_changed_fn",
             [](AbstractItemModel& self,
                std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
             { return self.addItemChangedFn(wrapPythonCallback(std::move(fn))); },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addItemChangedFn)
        .def("remove_item_changed_fn", &AbstractItemModel::removeItemChangedFn,
             OMNIUI_PYBIND_DOC_AbstractItemModel_removeItemChangedFn)
        .def("add_begin_edit_fn",
             [](AbstractItemModel& self,
                std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
             { return self.addBeginEditFn(wrapPythonCallback(std::move(fn))); },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addBeginEditFn)
        .def("remove_begin_edit_fn", &AbstractItemModel::removeBeginEditFn,
             OMNIUI_PYBIND_DOC_AbstractItemModel_removeBeginEditFn)
        .def("add_end_edit_fn",
             [](AbstractItemModel& self,
                std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)> fn)
             { return self.addEndEditFn(wrapPythonCallback(std::move(fn))); },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addEndEditFn)
        .def("remove_end_edit_fn", &AbstractItemModel::removeEndEditFn,
             OMNIUI_PYBIND_DOC_AbstractItemModel_removeEndEditFn)
        .def("subscribe_item_changed_fn",
             [](std::shared_ptr<AbstractItemModel>& self,
                const std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractItemModel::addItemChangedFn, &AbstractItemModel::removeItemChangedFn);
             },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addItemChangedFn)
        .def("subscribe_begin_edit_fn",
             [](std::shared_ptr<AbstractItemModel>& self,
                const std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractItemModel::addBeginEditFn, &AbstractItemModel::removeBeginEditFn);
             },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addBeginEditFn)
        .def("subscribe_end_edit_fn",
             [](std::shared_ptr<AbstractItemModel>& self,
                const std::function<void(const AbstractItemModel*, const AbstractItemModel::AbstractItem*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractItemModel::addEndEditFn, &AbstractItemModel::removeEndEditFn);
             },
             OMNIUI_PYBIND_DOC_AbstractItemModel_addEndEditFn);
}
