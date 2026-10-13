/*
 * SPDX-FileCopyrightText: Copyright (c) 2019-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindUtils.h"
#include "DocAbstractValueModel.h"
#include "DocSimpleBoolModel.h"
#include "DocSimpleFloatModel.h"
#include "DocSimpleIntModel.h"
#include "DocSimpleNumericModel.h"
#include "DocSimpleStringModel.h"

// Protected section is not exported
#define OMNIUI_PYBIND_DOC_AbstractValueModel__valueChanged                                                             \
    "Called when any data of the model is changed. It will notify the subscribed widgets."

#define OMNIUI_PYBIND_INIT_AbstractValueModel
#define OMNIUI_PYBIND_KWARGS_DOC_AbstractValueModel
