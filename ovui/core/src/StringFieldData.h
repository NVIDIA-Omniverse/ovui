/*
 * SPDX-FileCopyrightText: Copyright (c) 2020-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include <omni/ui/StringField.h>

#include "AbstractFieldData.h"

OMNIUI_NAMESPACE_OPEN_SCOPE

struct StringField::StringFieldData : public AbstractField::AbstractFieldData
{
    ~StringFieldData() override = default;
};

OMNIUI_NAMESPACE_CLOSE_SCOPE
