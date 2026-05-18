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
