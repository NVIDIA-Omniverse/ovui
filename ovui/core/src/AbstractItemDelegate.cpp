/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#include <omni/ui/AbstractItemDelegate.h>


OMNIUI_NAMESPACE_OPEN_SCOPE

AbstractItemDelegate::AbstractItemDelegate() = default;
AbstractItemDelegate::~AbstractItemDelegate() = default;

void AbstractItemDelegate::buildBranch(const std::shared_ptr<AbstractItemModel>& model,
                                       const std::shared_ptr<const AbstractItemModel::AbstractItem>& item,
                                       size_t index,
                                       uint32_t level,
                                       bool expanded)
{
}

void AbstractItemDelegate::buildHeader(size_t index)
{
}

OMNIUI_NAMESPACE_CLOSE_SCOPE
