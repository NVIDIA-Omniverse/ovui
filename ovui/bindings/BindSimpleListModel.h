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
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/bind/DocSimpleListModel.h>

#include <cstdint>
#include <string>
#include <vector>

using namespace pybind11;

OMNIUI_NAMESPACE_USING_DIRECTIVE

void wrapSimpleListModel(module& m)
{
    static constexpr char simpleListModelConstructorDoc[] =
        "Construct a SimpleListModel.\n"
        "\n"
        "### Arguments:\n"
        "    `values : list, optional`\n"
        "        A homogeneous list of bool, int, float, or str values. Each value becomes a\n"
        "        child item backed by the matching simple value model. If omitted the model\n"
        "        starts empty.\n"
        "    `default_value : int, optional`\n"
        "        Initial value of the root SimpleIntModel (typically the selected index in a\n"
        "        ComboBox-like view). Defaults to 0.\n";

    class_<SimpleListModel, AbstractItemModel, std::shared_ptr<SimpleListModel>>(
        m, "SimpleListModel", OMNIUI_PYBIND_DOC_SimpleListModel)
        .def(init([](args args, kwargs kwargs) {
                 // Optional first positional arg: list of values.
                 // Optional second positional arg or kwarg "default_value": root int value.
                 int32_t rootValue = 0;
                 if (kwargs.contains("default_value"))
                 {
                     rootValue = kwargs["default_value"].cast<int32_t>();
                 }

                 auto argsBegin = args.begin();
                 auto argsEnd = args.end();
                 if (argsBegin == argsEnd)
                 {
                     return SimpleListModel::create();
                 }

                 auto& valuesHandle = *argsBegin;
                 ++argsBegin;
                 if (argsBegin != argsEnd)
                 {
                     rootValue = (*argsBegin).cast<int32_t>();
                 }

                 if (!isinstance<sequence>(valuesHandle))
                 {
                     throw pybind11::type_error(
                         "SimpleListModel: first argument must be a list of bool/int/float/str values");
                 }

                 auto seq = valuesHandle.cast<sequence>();
                 if (seq.size() == 0)
                 {
                     return SimpleListModel::create();
                 }

                 // Detect element type from the first element. Mixed-type lists are not
                 // supported because SimpleListModel::create is templated on a single T.
                 auto first = seq[0];
                 if (isinstance<str>(first))
                 {
                     std::vector<std::string> values;
                     values.reserve(seq.size());
                     for (auto h : seq)
                     {
                         values.push_back(h.cast<std::string>());
                     }
                     return SimpleListModel::create(values, rootValue);
                 }
                 if (isinstance<bool_>(first))
                 {
                     std::vector<bool> values;
                     values.reserve(seq.size());
                     for (auto h : seq)
                     {
                         values.push_back(h.cast<bool>());
                     }
                     return SimpleListModel::create(values, rootValue);
                 }
                 if (isinstance<int_>(first))
                 {
                     std::vector<int32_t> values;
                     values.reserve(seq.size());
                     for (auto h : seq)
                     {
                         values.push_back(h.cast<int32_t>());
                     }
                     return SimpleListModel::create(values, rootValue);
                 }
                 if (isinstance<float_>(first))
                 {
                     std::vector<double> values;
                     values.reserve(seq.size());
                     for (auto h : seq)
                     {
                         values.push_back(h.cast<double>());
                     }
                     return SimpleListModel::create(values, rootValue);
                 }

                 throw pybind11::type_error(
                     "SimpleListModel: unsupported value type; expected bool, int, float, or str");
             }),
             simpleListModelConstructorDoc);
}
