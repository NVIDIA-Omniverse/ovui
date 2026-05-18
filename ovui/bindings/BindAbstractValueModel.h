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

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/SimpleNumericModel.h>
#include <omni/ui/SimpleStringModel.h>
#include <omni/ui/bind/BindAbstractValueModel.h>
#include <omni/ui/bind/Pybind.h>

#include <functional>
#include <memory>
#include <string>
#include <utility>

using namespace pybind11;

OMNIUI_NAMESPACE_OPEN_SCOPE

/**
 * @brief Class-helper that redirects all the abstract methods to python so that it's possible to reimplement this class
 * in python.
 */
class PyAbstractValueModel : public AbstractValueModel
{
public:
    using AbstractValueModel::_valueChanged;

    // Redirect all the abstract methods to python.
    bool getValueAsBool() const override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD(bool, AbstractValueModel, get_value_as_bool);

        return false;
    }

    double getValueAsFloat() const override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD(double, AbstractValueModel, get_value_as_float);

        return 0.0;
    }

    int64_t getValueAsInt() const override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD(int64_t, AbstractValueModel, get_value_as_int);

        return 0;
    }

    std::string getValueAsString() const override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD(std::string, AbstractValueModel, get_value_as_string);

        return {};
    }

    void beginEdit() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, AbstractValueModel, beginEdit, begin_edit);
    }

    void endEdit() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, AbstractValueModel, endEdit, end_edit);
    }

    void setValue(bool value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractValueModel, set_value, value);
    }

    void setValue(double value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractValueModel, set_value, value);
    }

    void setValue(int64_t value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractValueModel, set_value, value);
    }

    void setValue(std::string value) override
    {
        OMNIUI_PYBIND_ABSTRACT_METHOD_VA(void, AbstractValueModel, set_value, value);
    }
};

// It's very similar to PyAbstractValueModel, but pybind11 requires to have it because PyAbstractValueModel has
// implementation of abstract methods and PySimpleModel has implementation of virtual methods. For pybind11 there is a
// difference.
template <class T, typename U>
class PySimpleModel : public T
{
public:
    PySimpleModel(U defaultValue) : T{ defaultValue }
    {
    }

    // Redirect all the methods to python.
    bool getValueAsBool() const override
    {
        OMNIUI_PYBIND_OVERLOAD(bool, T, getValueAsBool, get_value_as_bool);

        return false;
    }

    double getValueAsFloat() const override
    {
        OMNIUI_PYBIND_OVERLOAD(double, T, getValueAsFloat, get_value_as_float);

        return 0.0f;
    }

    int64_t getValueAsInt() const override
    {
        OMNIUI_PYBIND_OVERLOAD(int64_t, T, getValueAsInt, get_value_as_int);

        return 0;
    }

    std::string getValueAsString() const override
    {
        OMNIUI_PYBIND_OVERLOAD(std::string, T, getValueAsString, get_value_as_string);

        return {};
    }

    void beginEdit() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, T, beginEdit, begin_edit);
    }

    void endEdit() override
    {
        OMNIUI_PYBIND_OVERLOAD(void, T, endEdit, end_edit);
    }

    void setValue(bool value) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::Base::setValue, set_value, value);
    }

    void setValue(double value) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::Base::setValue, set_value, value);
    }

    void setValue(int64_t value) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::Base::setValue, set_value, value);
    }

    void setValue(std::string value) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::setValue, set_value, value);
    }
};

template <class T, typename U>
class PySimpleNumericModel : public PySimpleModel<T, U>
{
public:
    using This = PySimpleModel<T, U>;

    template <typename... Args>
    static std::shared_ptr<This> create(Args&&... args)
    {
        return std::shared_ptr<This>{ new This{ std::forward<Args>(args)... } };
    }

    PySimpleNumericModel(U defaultValue, kwargs kwargs) : PySimpleModel<T, U>{ defaultValue }
    {
        for (auto item : kwargs)
        {
            auto name = item.first.cast<std::string>();
            const auto& value = item.second;

            if (name == "min")
            {
                this->setMin(value.cast<U>());
            }
            else if (name == "max")
            {
                this->setMax(value.cast<U>());
            }
        }
    }

    U getMin() const override
    {
        OMNIUI_PYBIND_OVERLOAD(U, T, getMin, get_min);

        return T::getMin();
    }

    void setMin(U const& min) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::setMin, set_min, min);
    }

    U getMax() const override
    {
        OMNIUI_PYBIND_OVERLOAD(U, T, getMax, get_max);

        return T::getMax();
    }

    void setMax(U const& max) override
    {
        OMNIUI_PYBIND_OVERLOAD_VA(void, T, T::setMax, set_max, max);
    }

protected:
};

std::shared_ptr<omni::ui::Subscription> createSubscription(
    std::shared_ptr<AbstractValueModel>& self,
    std::function<void(const AbstractValueModel*)> fn,
    uint32_t (AbstractValueModel::*ptrAdd)(std::function<void(const AbstractValueModel*)>),
    void (AbstractValueModel::*ptrRemove)(uint32_t id))
{
    auto callbackId = (*self.get().*ptrAdd)(wrapPythonCallback(std::move(fn)));
    std::weak_ptr<AbstractValueModel> weakPtr = self;

    return std::make_shared<omni::ui::Subscription>([=]() {
        auto ptr = weakPtr.lock();
        if (ptr)
        {
            (*ptr.get().*ptrRemove)(callbackId);
        }
    });
}

OMNIUI_NAMESPACE_CLOSE_SCOPE

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapAbstractValueModel(module& m)
{
    constexpr const char* abstractValueModelDoc = OMNIUI_PYBIND_CLASS_DOC(AbstractValueModel);
    static constexpr char abstractValueModelConstructorDoc[] =
        OMNIUI_PYBIND_CONSTRUCTOR_DOC(AbstractValueModel, AbstractValueModel);

    class_<AbstractValueModel, PyAbstractValueModel, std::shared_ptr<AbstractValueModel>> abstractValueModel(
        m, "AbstractValueModel", abstractValueModelDoc);

    abstractValueModel
        .def(init<>(), abstractValueModelConstructorDoc)
        // TODO: invent the way to overload "get_value" depending on the type. It will be possible if we introduce the
        // type of the model data.
        .def("get_value_as_bool", &AbstractValueModel::getValueAsBool, OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsBool)
        .def("get_value_as_float", &AbstractValueModel::getValueAsFloat,
             OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsFloat)
        .def("get_value_as_int", &AbstractValueModel::getValueAsInt, OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsInt)
        .def("get_value_as_string", &AbstractValueModel::getValueAsString,
             OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsString)
        .def("begin_edit", &AbstractValueModel::beginEdit, OMNIUI_PYBIND_DOC_AbstractValueModel_beginEdit)
        .def("end_edit", &AbstractValueModel::endEdit, OMNIUI_PYBIND_DOC_AbstractValueModel_endEdit)
        .def("set_value", (void (AbstractValueModel::*)(bool)) & AbstractValueModel::setValue, arg("value"),
             OMNIUI_PYBIND_DOC_AbstractValueModel_setValue)
        .def("set_value", (void (AbstractValueModel::*)(int64_t)) & AbstractValueModel::setValue, arg("value"),
             OMNIUI_PYBIND_DOC_AbstractValueModel_setValue)
        .def("set_value", (void (AbstractValueModel::*)(double)) & AbstractValueModel::setValue, arg("value"),
             OMNIUI_PYBIND_DOC_AbstractValueModel_setValue)
        .def("set_value", (void (AbstractValueModel::*)(std::string)) & AbstractValueModel::setValue, arg("value"),
             OMNIUI_PYBIND_DOC_AbstractValueModel_setValue)
        .def_property("as_bool", &AbstractValueModel::getValueAsBool,
                      (void (AbstractValueModel::*)(bool)) & AbstractValueModel::setValue,
                      OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsBool)
        .def_property("as_float", &AbstractValueModel::getValueAsFloat,
                      (void (AbstractValueModel::*)(double)) & AbstractValueModel::setValue,
                      OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsFloat)
        .def_property("as_int", &AbstractValueModel::getValueAsInt,
                      (void (AbstractValueModel::*)(int64_t)) & AbstractValueModel::setValue,
                      OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsInt)
        .def_property("as_string", &AbstractValueModel::getValueAsString,
                      (void (AbstractValueModel::*)(std::string)) & AbstractValueModel::setValue,
                      OMNIUI_PYBIND_DOC_AbstractValueModel_getValueAsString)
        .def("_value_changed", &PyAbstractValueModel::_valueChanged, OMNIUI_PYBIND_DOC_AbstractValueModel__valueChanged)
        .def("add_value_changed_fn",
             [](AbstractValueModel& self, std::function<void(const AbstractValueModel*)> fn) {
                 return self.addValueChangedFn(wrapPythonCallback(std::move(fn)));
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addValueChangedFn)
        .def("remove_value_changed_fn", &AbstractValueModel::removeValueChangedFn,
             OMNIUI_PYBIND_DOC_AbstractValueModel_removeValueChangedFn)
        .def("add_begin_edit_fn",
             [](AbstractValueModel& self, std::function<void(const AbstractValueModel*)> fn) {
                 return self.addBeginEditFn(wrapPythonCallback(std::move(fn)));
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addBeginEditFn)
        .def("remove_begin_edit_fn", &AbstractValueModel::removeBeginEditFn,
             OMNIUI_PYBIND_DOC_AbstractValueModel_removeBeginEditFn)
        .def("add_end_edit_fn",
             [](AbstractValueModel& self, std::function<void(const AbstractValueModel*)> fn) {
                 return self.addEndEditFn(wrapPythonCallback(std::move(fn)));
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addEndEditFn)
        .def("remove_end_edit_fn", &AbstractValueModel::removeEndEditFn,
             OMNIUI_PYBIND_DOC_AbstractValueModel_removeEndEditFn)
        .def("subscribe_item_changed_fn",
             [](std::shared_ptr<AbstractValueModel>& self, const std::function<void(const AbstractValueModel*)>& fn) {
                 OMNIUI_LOG_WARN(
                     "[deprecated] subscribe_item_changed_fn is deprecated. Please use subscribe_value_changed_fn");
                 return createSubscription(
                     self, fn, &AbstractValueModel::addValueChangedFn, &AbstractValueModel::removeValueChangedFn);
             })
        .def("subscribe_value_changed_fn",
             [](std::shared_ptr<AbstractValueModel>& self, const std::function<void(const AbstractValueModel*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractValueModel::addValueChangedFn, &AbstractValueModel::removeValueChangedFn);
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addValueChangedFn)
        .def("subscribe_begin_edit_fn",
             [](std::shared_ptr<AbstractValueModel>& self, const std::function<void(const AbstractValueModel*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractValueModel::addBeginEditFn, &AbstractValueModel::removeBeginEditFn);
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addBeginEditFn)
        .def("subscribe_end_edit_fn",
             [](std::shared_ptr<AbstractValueModel>& self, const std::function<void(const AbstractValueModel*)>& fn) {
                 return createSubscription(
                     self, fn, &AbstractValueModel::addEndEditFn, &AbstractValueModel::removeEndEditFn);
             },
             OMNIUI_PYBIND_DOC_AbstractValueModel_addEndEditFn)
        /* */;

    // It's not in a separate file because we need the variable abstractValueModel to let pybind11 know that
    // SimpleStringModel is derived from AbstractValueModel
    using PySimpleStringModel = PySimpleModel<SimpleStringModel, const std::string&>;
    using PySimpleBoolModel = PySimpleNumericModel<SimpleBoolModel, bool>;
    using PySimpleFloatModel = PySimpleNumericModel<SimpleFloatModel, double>;
    using PySimpleIntModel = PySimpleNumericModel<SimpleIntModel, int64_t>;

    class_<SimpleStringModel, PySimpleStringModel, std::shared_ptr<SimpleStringModel>>(
        m, "SimpleStringModel", abstractValueModel, OMNIUI_PYBIND_DOC_SimpleStringModel)
        .def(init<const std::string&>(), arg("defaultValue") = std::string{});

    class_<SimpleBoolModel, PySimpleBoolModel, std::shared_ptr<SimpleBoolModel>>(
        m, "SimpleBoolModel", abstractValueModel, OMNIUI_PYBIND_DOC_SimpleBoolModel)
        .def(init_alias<bool, kwargs>(), arg("default_value") = false)
        .def_property("min", &SimpleBoolModel::getMin, &SimpleBoolModel::setMin, OMNIUI_PYBIND_DOC_SimpleNumericModel_min)
        .def_property("max", &SimpleBoolModel::getMax, &SimpleBoolModel::setMax, OMNIUI_PYBIND_DOC_SimpleNumericModel_max)
        .def("set_min", &SimpleBoolModel::setMin)
        .def("get_min", &SimpleBoolModel::getMin)
        .def("set_max", &SimpleBoolModel::setMax)
        .def("get_max", &SimpleBoolModel::getMax)
        /* */;

    class_<SimpleFloatModel, PySimpleFloatModel, std::shared_ptr<SimpleFloatModel>>(
        m, "SimpleFloatModel", abstractValueModel, OMNIUI_PYBIND_DOC_SimpleFloatModel)
        .def(init_alias<double, kwargs>(), arg("default_value") = 0.0)
        .def_property(
            "min", &SimpleFloatModel::getMin, &SimpleFloatModel::setMin, OMNIUI_PYBIND_DOC_SimpleNumericModel_min)
        .def_property(
            "max", &SimpleFloatModel::getMax, &SimpleFloatModel::setMax, OMNIUI_PYBIND_DOC_SimpleNumericModel_min)
        .def("set_min", &SimpleFloatModel::setMin)
        .def("get_min", &SimpleFloatModel::getMin)
        .def("set_max", &SimpleFloatModel::setMax)
        .def("get_max", &SimpleFloatModel::getMax)
        /* */;

    class_<SimpleIntModel, PySimpleIntModel, std::shared_ptr<SimpleIntModel>>(
        m, "SimpleIntModel", abstractValueModel, OMNIUI_PYBIND_DOC_SimpleIntModel)
        .def(init_alias<int64_t, kwargs>(), arg("default_value") = 0)
        .def_property("min", &SimpleIntModel::getMin, &SimpleIntModel::setMin, OMNIUI_PYBIND_DOC_SimpleNumericModel_min)
        .def_property("max", &SimpleIntModel::getMax, &SimpleIntModel::setMax, OMNIUI_PYBIND_DOC_SimpleNumericModel_min)
        .def("set_min", &SimpleIntModel::setMin)
        .def("get_min", &SimpleIntModel::getMin)
        .def("set_max", &SimpleIntModel::setMax)
        .def("get_max", &SimpleIntModel::getMax)
        /* */;
}
