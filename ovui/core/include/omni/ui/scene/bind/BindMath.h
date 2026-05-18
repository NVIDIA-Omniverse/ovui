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

#include "DocMatrix44.h"

#include <omni/ui/scene/Math.h>
#include <omni/ui/bind/Pybind.h>

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

pybind11::object matrix4ToPython(const Matrix44& matrix);
Matrix44 pythonToMatrix4(const pybind11::handle& obj);
pybind11::object vector2ToPython(const Vector2& vec);
Vector2 pythonToVector2(const pybind11::handle& obj);
pybind11::object vector3ToPython(const Vector3& vec);
Vector3 pythonToVector3(const pybind11::handle& obj);
pybind11::object vector4ToPython(const Vector4& vec);
Vector4 pythonToVector4(const pybind11::handle& obj);
Color4 pythonToColor4(const pybind11::handle& obj);

std::vector<Vector4> pythonListToVector4(const pybind11::handle& obj);
std::vector<Vector3> pythonListToVector3(const pybind11::handle& obj);
std::vector<Vector2> pythonListToVector2(const pybind11::handle& obj);
pybind11::object vector4ToPythonList(const std::vector<Vector4>& vec);
pybind11::object vector3ToPythonList(const std::vector<Vector3>& vec);
pybind11::object vector2ToPythonList(const std::vector<Vector2>& vec);

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
