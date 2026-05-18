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

#include "platform/Assert.h"
#include "platform/Log.h"

#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/RadioButton.h>
#include <omni/ui/RadioCollection.h>
#include <omni/ui/SimpleNumericModel.h>

#include "ValueModelHelperData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

struct RadioCollection::RadioCollectionData : public ValueModelHelper::ValueModelHelperData
{
    using ValueModelHelperData::ValueModelHelperData;

    ~RadioCollectionData()override = default;

    // The list of the radio button that are part of this collection.
    //
    // RadioButton keeps the shared pointer to this collection, and here the collection keeps the pointer to the
    // RadioButton. To avoid circular dependency, we use weak pointers from this side because of the Python API. We
    // never require the user to keep a Python object and do all the work that is related to the object's life. It means
    // the user can create UI like this, and the created objects will not be immediately removed with Python garbage
    // collector:
    //
    //    with ui.HStack():
    //        ui.Label("Hello")
    //        ui.Label("World")
    //
    // The RadioCollection is not a widget, and to make sure the collection will not be removed right after it's
    // created, we use shared pointers in RadioButtons and not here, which makes them the owners of the collection.
    std::vector<std::weak_ptr<RadioButton>> m_radioButtons;
};


RadioCollection::RadioCollection(std::shared_ptr<AbstractValueModel> inModel)
    : ValueModelHelper(new RadioCollectionData(std::move(inModel)))
{
    auto& model = _getModelData<RadioCollectionData>().m_model;
    if (!model)
    {
        // If there is no model, create a simple one.
        this->setModel(SimpleIntModel::create());
    }
    else
    {
        // We can't call it from the base class because it's not possible to call inherited methods in the
        this->onModelUpdated();
    }
}

RadioCollection::~RadioCollection() = default;

void RadioCollection::onModelUpdated()
{
    auto model = this->getModel();
    if (OMNIUI_UNLIKELY(static_cast<bool>(model) == false))
    {
        OMNIUI_LOG_ERROR("RadioCollection has no model");
        return;
    }

    auto& data = _getModelData<RadioCollectionData>();
    int64_t selected = model->getValue<int64_t>();
    for (size_t i = 0, n = data.m_radioButtons.size(); i < n; ++i)
    {
        std::shared_ptr<RadioButton> currentButton = data.m_radioButtons[i].lock();
        if (!currentButton)
        {
            OMNIUI_LOG_WARN("The RadionButton #%zu is removed from RadioCollection\n", i);
            continue;
        }

        // We set the state of all the radio buttons because when we receive the callback that the model is changed, we
        // don't know the previous state. If the state is not changed, nothing should happen.
        currentButton->setChecked(static_cast<int64_t>(i) == selected);
    }
}

void RadioCollection::_addRadioButton(std::shared_ptr<RadioButton> button)
{
    auto& data = _getModelData<RadioCollectionData>();
    data.m_radioButtons.push_back(std::move(button));
    onModelUpdated();
}

void RadioCollection::_clicked(const RadioButton* button)
{
    auto& data = _getModelData<RadioCollectionData>();
    auto begin = data.m_radioButtons.begin();
    auto end = data.m_radioButtons.end();

    auto found = std::find_if(begin, end, [button](std::weak_ptr<RadioButton>& it) { return it.lock().get() == button; });
    if (found != end)
    {
        auto model = this->getModel();
        if (OMNIUI_LIKELY(static_cast<bool>(model)))
        {
            model->setValue(static_cast<int64_t>(std::distance(begin, found)));
        }
        else
        {
            OMNIUI_LOG_ERROR("RadioCollection::_clicked called without a model");
        }
    }
    else
    {
        OMNIUI_LOG_WARN("Can't find RadioButton in the collection");
    }
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
