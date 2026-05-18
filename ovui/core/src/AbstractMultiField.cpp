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

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/AbstractMultiField.h>
#include <omni/ui/AbstractValueModel.h>
#include <omni/ui/HStack.h>
#include <omni/ui/VStack.h>

#include "AbstractMultiFieldData.h"

#include <algorithm>

OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractMultiField::AbstractMultiFieldData::~AbstractMultiFieldData()
{
}

AbstractMultiField::AbstractMultiField(std::shared_ptr<AbstractItemModel> model, AbstractMultiFieldData* dataPtr)
    : Widget(dataPtr ? dataPtr : new AbstractMultiFieldData)
    , ItemModelHelper(std::move(model))
{
    this->setHSpacingChangedFn(std::bind(&This::_onSpacingChanged, this));
    this->setVSpacingChangedFn(std::bind(&This::_onSpacingChanged, this));

    this->setColumnCountChangedFn(std::bind(&This::_onColumnCountChanged, this));

    auto& data = _getData<AbstractMultiFieldData>();
    // Don't push created object to any container
    OMNIKIT_WITH_CONTAINER(nullptr)
    {
        data.m_mainLayout = VStack::create();
        data.m_mainLayout->useMarginFromStyle(false);
    }

    this->setSelectedChangedFn([this](const auto& selected) {
        _getData<AbstractMultiFieldData>().m_mainLayout->setSelected(selected);
    });
    this->setCheckedChangedFn([this](const auto& checked) {
        _getData<AbstractMultiFieldData>().m_mainLayout->setChecked(checked);
    });
    this->setEnabledChangedFn([this](const auto& enabled) {
        _getData<AbstractMultiFieldData>().m_mainLayout->setEnabled(enabled);
    });
    this->_setScaleChangedFn([this](const auto& scale) {
        _getData<AbstractMultiFieldData>().m_mainLayout->setScale(scale);
    });
    this->_setCanvasZoomChangedFn([this](const auto& zoom) {
        _getData<AbstractMultiFieldData>().m_mainLayout->setCanvasZoom(zoom);
    });
    this->setNameChangedFn(
        [this](const auto& name)
        {
            for (auto& child : _getData<AbstractMultiFieldData>().m_children)
            {
                if (OMNIUI_LIKELY(child))
                {
                    child->setName(name);
                }
            }
        });
}

AbstractMultiField::~AbstractMultiField() = default;

void AbstractMultiField::setComputedContentWidth(float width)
{
    // Get size from m_mainLayout
    auto& data = _getData<AbstractMultiFieldData>();
    data.m_mainLayout->forceWidthDirty(SizeDirtyReason::eParentDirty);
    data.m_mainLayout->setComputedWidth(width);
    Widget::setComputedContentWidth(data.m_mainLayout->getComputedWidth());
}

void AbstractMultiField::setComputedContentHeight(float height)
{
    // Get size from m_mainLayout
    auto& data = _getData<AbstractMultiFieldData>();
    data.m_mainLayout->forceHeightDirty(SizeDirtyReason::eParentDirty);
    data.m_mainLayout->setComputedHeight(height);
    Widget::setComputedContentHeight(data.m_mainLayout->getComputedHeight());
}

void AbstractMultiField::onStyleUpdated()
{
    Widget::onStyleUpdated();

    // Propogate the style to the children. No necessary to call updateStyle if setStyle is called.
    auto& data = _getData<AbstractMultiFieldData>();
    data.m_mainLayout->setStyle(this->_getResolvedStyle());
}

void AbstractMultiField::onModelUpdated(const std::shared_ptr<const AbstractItemModel::AbstractItem>& item)
{
    if (item != nullptr)
    {
        return;
    }

    // We are here because the root item is changed. We will remove all the widgets and recreate them again.

    auto model = this->getModel();
    if (OMNIUI_LIKELY(static_cast<bool>(model)))
    {
        auto& myChildren = _getData<AbstractMultiFieldData>().m_children;
        auto modelChildItems = model->getItemChildren();
        if (myChildren.size() == modelChildItems.size())
        {
            // Just update widgets without recreating them.
            for (size_t i = 0, n = myChildren.size(); i < n; ++i)
            {
                auto subModel = this->getModel()->getItemValueModel(modelChildItems[i]);
                OMNIUI_ASSERT(subModel);
                this->_setFieldModel(myChildren[i], subModel);
                subModel->_valueChanged();
            }

            return;
        }
    }

    // We are here because the number of items is changed. We need to recreate them.
    this->_onColumnCountChanged();
}

void AbstractMultiField::_drawContent(float elapsedTime)
{
    // Draw layout
    auto& data = _getData<AbstractMultiFieldData>();
    data.m_mainLayout->draw(elapsedTime);
}

void AbstractMultiField::_onSpacingChanged()
{
    float hSpacing = this->getHSpacing();
    float vSpacing = this->getVSpacing();

    auto& data = _getData<AbstractMultiFieldData>();
    data.m_mainLayout->setSpacing(vSpacing);
    for (const auto& stack : data.m_stacks)
    {
        stack->setSpacing(hSpacing);
    }
}

void AbstractMultiField::_onColumnCountChanged()
{
    auto& data = _getData<AbstractMultiFieldData>();

    data.m_children.clear();
    data.m_stacks.clear();
    // TODO: m_stacks.reserve()
    data.m_mainLayout->clear();

    OMNIKIT_WITH_CONTAINER(data.m_mainLayout)
    {
        auto model = this->getModel();
        OMNIUI_ASSERT(model);

        uint8_t columnCount = this->getColumnCount();

        auto modelChildItems = model->getItemChildren();

        // This double loop creates an HStack per columnCount items
        for (auto it = modelChildItems.begin(); it < modelChildItems.end();)
        {
            data.m_stacks.push_back(HStack::create());
            OMNIKIT_WITH_CONTAINER(data.m_stacks.back())
            {
                for (uint8_t i = 0; i < columnCount && it < modelChildItems.end(); ++i, ++it)
                {
                    auto subModel = this->getModel()->getItemValueModel(*it);
                    OMNIUI_ASSERT(subModel);

                    auto field = this->_createField(subModel);
                    field->setName(this->getName());
                    data.m_children.push_back(field);
                }
            }
        }
    }

    // Restore spacing because the new items don't have it.
    this->_onSpacingChanged();

    // Set the size of new items because if the columnCount was updated in the draw cycle, the size of children will be marked
    // as not dirty at the end of draw cycle.
    data.m_mainLayout->setComputedContentWidth(data.m_mainLayout->getComputedContentWidth());
    data.m_mainLayout->setComputedContentHeight(data.m_mainLayout->getComputedContentHeight());
}

std::shared_ptr<Widget> AbstractMultiField::_createField(std::shared_ptr<AbstractValueModel> model)
{
    return {};
}

void AbstractMultiField::_setFieldModel(std::shared_ptr<Widget> widget, std::shared_ptr<AbstractValueModel> model)
{
}

const std::vector<std::shared_ptr<Widget>>& AbstractMultiField::_getChildren() const
{
    return _getData<AbstractMultiFieldData>().m_children;
}


OMNIUI_NAMESPACE_CLOSE_SCOPE
