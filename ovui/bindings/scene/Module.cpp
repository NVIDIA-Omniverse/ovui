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

// Standalone variant: carb/BindingsUtils.h and CARB_BINDINGS removed.
// The _scene module is a plain pybind11 extension — no Carbonite plugin
// registration is needed in standalone mode.
//
#include <omni/ui/bind/BindUtils.h>

PYBIND11_MODULE(_scene, m)
{
    pybind11::module::import("omni.ui");

    OMNIUI_BIND(AbstractGesture);
    {
        OMNIUI_BIND(ShapeGesture);
        OMNIUI_BIND(ManipulatorGesture);
    }
    OMNIUI_BIND(GestureManager);
    OMNIUI_BIND(Math);
    OMNIUI_BIND(Space);
    OMNIUI_BIND(Culling);

    OMNIUI_BIND(AbstractItem);
    {
        OMNIUI_BIND(AbstractContainer);
        {
            OMNIUI_BIND(Scene);
            OMNIUI_BIND(TransformBasis);
            OMNIUI_BIND(Transform);
            OMNIUI_BIND(Manipulator);
            {
                OMNIUI_BIND(AbstractManipulatorModel);
                {
                    OMNIUI_BIND(CameraModel);
                }
            }
        }

        OMNIUI_BIND(AbstractShape);
        {
            OMNIUI_BIND(Arc);
            OMNIUI_BIND(Curve);
            OMNIUI_BIND(Label);
            OMNIUI_BIND(Line);
            OMNIUI_BIND(Points);
            OMNIUI_BIND(PolygonMesh);
            {
                OMNIUI_BIND(TexturedMesh);
            }
            OMNIUI_BIND(Rectangle);
            {
                OMNIUI_BIND(Image);
                OMNIUI_BIND(Widget);
            }

            OMNIUI_BIND(Screen);
        }
    }

    OMNIUI_BIND(SceneView);
}
