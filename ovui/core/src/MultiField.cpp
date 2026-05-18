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

#include <omni/ui/FloatField.h>
#include <omni/ui/IntField.h>
#include <omni/ui/MultiField.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/StringField.h>

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

MultiFloatField::MultiFloatField(std::shared_ptr<AbstractItemModel> model)
    : AbstractMultiField(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleListModel::create(std::vector<float>{ { 0.f, 0.f, 0.f } }));
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }
}

std::shared_ptr<Widget> MultiFloatField::_createField(std::shared_ptr<AbstractValueModel> model)
{
    return FloatField::create(std::move(model));
}

void MultiFloatField::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model)
{
    std::static_pointer_cast<FloatField>(widget)->setModel(std::move(model));
}

MultiIntField::MultiIntField(std::shared_ptr<AbstractItemModel> model)
    : AbstractMultiField(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleListModel::create(std::vector<int>{ { 0, 0, 0 } }));
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }
}

std::shared_ptr<Widget> MultiIntField::_createField(std::shared_ptr<AbstractValueModel> model)
{
    return IntField::create(std::move(model));
}

void MultiIntField::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model)
{
    std::static_pointer_cast<IntField>(widget)->setModel(std::move(model));
}

MultiStringField::MultiStringField(std::shared_ptr<AbstractItemModel> model)
    : AbstractMultiField(std::move(model))
{
    if (!static_cast<bool>(getModel()))
    {
        // If there is no model, create a simple string one.
        this->setModel(SimpleListModel::create(std::vector<std::string>{ { "", "", "" } }));
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the constructor.
        this->onModelUpdated(nullptr);
    }
}

std::shared_ptr<Widget> MultiStringField::_createField(std::shared_ptr<AbstractValueModel> model)
{
    return StringField::create(std::move(model), nullptr);
}

void MultiStringField::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model)
{
    std::static_pointer_cast<StringField>(widget)->setModel(std::move(model));
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
