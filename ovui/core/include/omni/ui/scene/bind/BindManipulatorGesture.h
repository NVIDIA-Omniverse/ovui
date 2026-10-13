/*
 * SPDX-FileCopyrightText: Copyright (c) 2021-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

#include "BindAbstractGesture.h"
#include "DocManipulatorGesture.h"

#include <omni/ui/bind/BindUtils.h>

OMNIUI_PROTECT_PYBIND11_OBJECT(OMNIUI_SCENE_NS::ManipulatorGesture, ManipulatorGesture);

#define OMNIUI_PYBIND_INIT_ManipulatorGesture OMNIUI_PYBIND_INIT_AbstractGesture
#define OMNIUI_PYBIND_INIT_PyManipulatorGesture OMNIUI_PYBIND_INIT_ManipulatorGesture
#define OMNIUI_PYBIND_KWARGS_DOC_ManipulatorGesture OMNIUI_PYBIND_KWARGS_DOC_AbstractGesture
#define OMNIUI_PYBIND_KWARGS_DOC_PyManipulatorGesture OMNIUI_PYBIND_KWARGS_DOC_ManipulatorGesture

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

class PyManipulatorGesture : public ManipulatorGesture
{
public:
    static std::shared_ptr<PyManipulatorGesture> create(pybind11::handle derivedFrom);

    void process() override;

    const pybind11::handle& getHandle() const;

private:
    pybind11::handle m_derivedFrom;
};

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
