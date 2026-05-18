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

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/ComboBox.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/bind/BindComboBox.h>
#include <omni/ui/bind/BindUtils.h>

#include <memory>
#include <string>
#include <vector>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapComboBox(module& m)
{
    constexpr const char* comboBoxDoc = OMNIUI_PYBIND_CLASS_DOC(ComboBox);
    static constexpr char comboBoxConstructorDoc[] = OMNIUI_PYBIND_CONSTRUCTOR_DOC(ComboBox, ComboBox);
    class_<ComboBox, Widget, ItemModelHelper, std::shared_ptr<ComboBox>>(m, "ComboBox", comboBoxDoc)
        .def(init([](args args, kwargs kwargs) {
                 // The arguments of the coonstructor can be dynamic. It can be a AbstractItemModel, or it's possible to
                 // specify the selected index and all the items.
                 std::shared_ptr<AbstractItemModel> model;

                 auto argsBegin = args.begin();
                 auto argsEnd = args.end();
                 if (argsBegin != argsEnd)
                 {
                     auto& arg = *argsBegin;
                     if (isinstance<AbstractItemModel>(arg))
                     {
                         model = arg.cast<std::shared_ptr<AbstractItemModel>>();
                     }
                     else if (isinstance<int_>(arg))
                     {
                         int32_t currentIndex = arg.cast<int32_t>();

                         std::vector<std::string> items;
                         while (++argsBegin != argsEnd)
                         {
                             auto& optionHandle = *argsBegin;
                             if (isinstance<str>(optionHandle))
                             {
                                 items.push_back(optionHandle.cast<std::string>());
                             }
                             else
                             {
                                 OMNIUI_LOG_WARN("ComboBox Constructor: argument is not str");
                             }
                         }

                         model = SimpleListModel::create(items, currentIndex);
                     }
                     else
                     {
                         OMNIUI_LOG_WARN("ComboBox Constructor: unknown argument");
                     }
                 }

                 OMNIUI_PYBIND_INIT(ComboBox, model)
             }),
             comboBoxConstructorDoc);
}
