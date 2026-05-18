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

#include "BindBezierCurve.h"
#include "BindCircle.h"
#include "BindEllipse.h"
#include "BindLine.h"
#include "BindRectangle.h"
#include "BindShape.h"
#include "BindTriangle.h"
#include "BindUtils.h"
#include "DocFreeShape.h"

#define OMNIUI_PYBIND_DOC_FreeBezierCurve OMNIUI_PYBIND_DOC_BezierCurve OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeBezierCurve_FreeBezierCurve OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeBezierCurve OMNIUI_PYBIND_INIT_BezierCurve
#define OMNIUI_PYBIND_KWARGS_DOC_FreeBezierCurve OMNIUI_PYBIND_KWARGS_DOC_BezierCurve

#define OMNIUI_PYBIND_DOC_FreeCircle OMNIUI_PYBIND_DOC_Circle OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeCircle_FreeCircle OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeCircle OMNIUI_PYBIND_INIT_Circle
#define OMNIUI_PYBIND_KWARGS_DOC_FreeCircle OMNIUI_PYBIND_KWARGS_DOC_Circle

#define OMNIUI_PYBIND_DOC_FreeEllipse OMNIUI_PYBIND_DOC_Ellipse OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeEllipse_FreeEllipse OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeEllipse OMNIUI_PYBIND_INIT_Ellipse
#define OMNIUI_PYBIND_KWARGS_DOC_FreeEllipse OMNIUI_PYBIND_KWARGS_DOC_Ellipse

#define OMNIUI_PYBIND_DOC_FreeLine OMNIUI_PYBIND_DOC_Line OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeLine_FreeLine OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeLine OMNIUI_PYBIND_INIT_Line
#define OMNIUI_PYBIND_KWARGS_DOC_FreeLine OMNIUI_PYBIND_KWARGS_DOC_Line

#define OMNIUI_PYBIND_DOC_FreeRectangle OMNIUI_PYBIND_DOC_Rectangle OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeRectangle_FreeRectangle OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeRectangle OMNIUI_PYBIND_INIT_Rectangle
#define OMNIUI_PYBIND_KWARGS_DOC_FreeRectangle OMNIUI_PYBIND_KWARGS_DOC_Rectangle

#define OMNIUI_PYBIND_DOC_FreeTriangle OMNIUI_PYBIND_DOC_Triangle OMNIUI_PYBIND_DOC_FreeShape
#define OMNIUI_PYBIND_DOC_FreeTriangle_FreeTriangle OMNIUI_PYBIND_DOC_FreeShape_FreeShape
#define OMNIUI_PYBIND_INIT_FreeTriangle OMNIUI_PYBIND_INIT_Triangle
#define OMNIUI_PYBIND_KWARGS_DOC_FreeTriangle OMNIUI_PYBIND_KWARGS_DOC_Triangle
