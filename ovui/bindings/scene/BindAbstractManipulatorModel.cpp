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

// Standalone variant: carb/BindingsPythonUtils.h and carb::Subscription replaced
// with omni::ui::Subscription (core/include/omni/ui/Subscription.h).
//
#include <omni/ui/Subscription.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/Manipulator.h>
#include <omni/ui/scene/bind/BindAbstractManipulatorModel.h>
#include <omni/ui/scene/bind/BindManipulator.h>
#include <omni/ui/scene/bind/BindMath.h>
#include <pybind11/stl.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief The trampoline class for AbstractManipulatorModel
 */
class PyAbstractManipulatorModel : public AbstractManipulatorModel
{
public:
    using AbstractManipulatorModel::_itemChanged;

    PyAbstractManipulatorModel() : AbstractManipulatorModel{}
    {
    }

    // Redirect all the abstract methods to python.
    std::shared_ptr<const AbstractManipulatorItem> getItem(const std::string& identifier) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(std::shared_ptr<const AbstractManipulatorItem>, AbstractManipulatorModel,
                                  AbstractManipulatorModel::getItem, get_item, identifier);
    }

    std::vector<Float> getAsFloats(const std::shared_ptr<const AbstractManipulatorItem>& item) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(std::vector<Float>, AbstractManipulatorModel, get_as_floats, item);

        return {};
    }

    std::vector<int64_t> getAsInts(const std::shared_ptr<const AbstractManipulatorItem>& item) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(std::vector<int64_t>, AbstractManipulatorModel, get_as_ints, item);

        return {};
    }

    void setFloats(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<Float> value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractManipulatorModel, set_floats, item, std::move(value));
    }

    void setInts(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<int64_t> value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractManipulatorModel, set_ints, item, std::move(value));
    }

    // Single value shortcuts for Python

    Float getAsFloat(const std::shared_ptr<const AbstractManipulatorItem>& item)
    {
        auto list = this->getAsFloats(item);
        if (list.empty())
        {
            return {};
        }

        return list[0];
    }

    void setFloat(const std::shared_ptr<const AbstractManipulatorItem>& item, Float value)
    {
        this->setFloats(item, { value });
    }

    int64_t getAsInt(const std::shared_ptr<const AbstractManipulatorItem>& item)
    {
        auto list = this->getAsInts(item);
        if (list.empty())
        {
            return {};
        }

        return list[0];
    }

    void setInt(const std::shared_ptr<const AbstractManipulatorItem>& item, int64_t value)
    {
        this->setInts(item, { value });
    }

    bool getAsBool(const std::shared_ptr<const AbstractManipulatorItem>& item)
    {
        auto list = this->getAsInts(item);
        if (list.empty())
        {
            return {};
        }

        return list[0] != 0;
    }

    void setBool(const std::shared_ptr<const AbstractManipulatorItem>& item, bool value)
    {
        this->setInts(item, { value });
    }
};

template <typename Model, typename CallbackFn>
std::shared_ptr<omni::ui::Subscription> createSubscription(std::shared_ptr<Model>& self,
                                                           CallbackFn&& fn,
                                                           uint32_t (Model::*ptrAdd)(CallbackFn&&),
                                                           void (Model::*ptrRemove)(uint32_t))
{
    auto callbackId = (*self.get().*ptrAdd)(wrapPythonCallback(std::move(fn)));
    std::weak_ptr<Model> weakPtr = self;

    return std::make_shared<omni::ui::Subscription>(
        [=]()
        {
            auto ptr = weakPtr.lock();
            if (ptr)
            {
                (*self.get().*ptrRemove)(callbackId);
            }
        });
}

template <typename ClassT, typename ReturnT, typename... Args>
auto _itemBasedCall(
    ReturnT (ClassT::*MethodT)(const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>&, Args...))
{
    return [MethodT](ClassT& self, const pybind11::handle& item, Args... args)
    {
        if (isinstance<pybind11::none>(item))
        {
            return (self.*MethodT)(nullptr, std::forward<Args>(args)...);
        }
        if (isinstance<pybind11::str>(item))
        {
            return (self.*MethodT)(self.getItem(item.cast<std::string>()), std::forward<Args>(args)...);
        }
        if (isinstance<AbstractManipulatorModel::AbstractManipulatorItem>(item))
        {
            return (self.*MethodT)(
                item.cast<const std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem>>(),
                std::forward<Args>(args)...);
        }

        throw type_error("The value of type " + static_cast<std::string>(pybind11::str(item.get_type())) +
                         " can be converted to neither string nor AbstractManipulatorItem");

        return ReturnT();
    };
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE

OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapAbstractManipulatorModel(module& m)
{
    constexpr const char* abstractManipulatorModelDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractManipulatorModel);
    static constexpr char _item_changed[] = "Called when any data of the model is changed. It will notify the subscribed widgets.";
    static constexpr char get_as_float[] = "Shortcut for `get_as_floats` that returns the first item of the list.";
    static constexpr char get_as_int[] = "Shortcut for `get_as_ints` that returns the first item of the list.";
    static constexpr char get_as_bool[] = "Shortcut for `get_as_ints` that returns the first item of the list.";
    static constexpr char set_float[] = "Shortcut for `set_floats` that sets an array with the size of one.";
    static constexpr char set_int[] = "Shortcut for `set_ints` that sets an array with the size of one.";
    static constexpr char set_bool[] = "Shortcut for `set_ints` that sets an array with the size of one.";

    class_<AbstractManipulatorModel::AbstractManipulatorItem,
           std::shared_ptr<AbstractManipulatorModel::AbstractManipulatorItem>>(m, "AbstractManipulatorItem")
        .def(init<>());

    class_<AbstractManipulatorModel, PyAbstractManipulatorModel, std::shared_ptr<AbstractManipulatorModel>>(
        m, "AbstractManipulatorModel", abstractManipulatorModelDoc)
        .def(init<>())
        .def("_item_changed", _itemBasedCall(&PyAbstractManipulatorModel::_itemChanged), _item_changed)
        .def("get_item", &AbstractManipulatorModel::getItem, OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getItem)
        .def("get_as_floats", _itemBasedCall(&AbstractManipulatorModel::getAsFloats),
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getAsFloats)
        .def("get_as_ints", _itemBasedCall(&AbstractManipulatorModel::getAsInts),
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_getAsInts)
        .def("set_floats", _itemBasedCall(&AbstractManipulatorModel::setFloats),
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_setFloats)
        .def("set_ints", _itemBasedCall(&AbstractManipulatorModel::setInts),
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_setInts)
        .def("get_as_float", _itemBasedCall(&PyAbstractManipulatorModel::getAsFloat), get_as_float)
        .def("get_as_int", _itemBasedCall(&PyAbstractManipulatorModel::getAsInt), get_as_int)
        .def("get_as_bool", _itemBasedCall(&PyAbstractManipulatorModel::getAsBool), get_as_bool)
        .def("set_float", _itemBasedCall(&PyAbstractManipulatorModel::setFloat), set_float)
        .def("set_int", _itemBasedCall(&PyAbstractManipulatorModel::setInt), set_int)
        .def("set_bool", _itemBasedCall(&PyAbstractManipulatorModel::setBool), set_bool)
        .def("add_item_changed_fn",
             [](AbstractManipulatorModel& self, AbstractManipulatorModel::ItemChangedCallback&& fn)
             { return self.addItemChangedFn(wrapPythonCallback(std::move(fn))); },
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_addItemChangedFn)
        .def("remove_item_changed_fn", &AbstractManipulatorModel::removeItemChangedFn,
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_removeItemChangedFn)
        .def("subscribe_item_changed_fn",
             [](std::shared_ptr<AbstractManipulatorModel>& self, AbstractManipulatorModel::ItemChangedCallback&& fn)
             {
                 return createSubscription(self, std::move(fn), &AbstractManipulatorModel::addItemChangedFn,
                                           &AbstractManipulatorModel::removeItemChangedFn);
             },
             OMNIUI_PYBIND_DOC_AbstractManipulatorModel_addItemChangedFn)
        /**/;
}
