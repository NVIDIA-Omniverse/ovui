/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Raster-invalidation contract for multi-fields.
 *
 * An AUTO-rasterized frame or window replays its cached image until forceRasterDirty() reaches it. A multi-field
 * (MultiFloatDragField, MultiFloatField, ...) keeps its value fields in an internal layout that has no parent, so the
 * invalidation each field raises when its value changes stops inside the multi-field. When its model reports a change,
 * the multi-field itself must invalidate its ancestors, or a window that rasterizes keeps drawing the old numbers:
 * Property > Transform > Orient after a Rotate-gizmo drag in Isaac Sim, whose windows rasterize (QA1008-007).
 *
 * A probe frame counts the invalidations that reach it. Widgets lay themselves out with an ImGui context and its
 * default font; no frame is drawn and no window or GPU is involved.
 */

#include <omni/ui/AbstractItemModel.h>
#include <omni/ui/ContainerScope.h>
#include <omni/ui/FloatDrag.h>
#include <omni/ui/Frame.h>
#include <omni/ui/MultiDragField.h>
#include <omni/ui/MultiField.h>
#include <omni/ui/SimpleListModel.h>
#include <omni/ui/SimpleNumericModel.h>

#include <imgui/imgui.h>

#include <iostream>
#include <memory>
#include <string>
#include <vector>

using namespace omni::ui;

namespace
{

int g_failures = 0;

void check(bool condition, const std::string& what)
{
    if (!condition)
    {
        ++g_failures;
        std::cerr << "FAILED: " << what << std::endl;
    }
    else
    {
        std::cout << "ok: " << what << std::endl;
    }
}

/// A frame that counts the raster invalidations that reach it.
class ProbeFrame : public Frame
{
    OMNIUI_OBJECT(ProbeFrame)

public:
    void forceRasterDirty(BakeDirtyReason reason) override
    {
        ++invalidations;
        Frame::forceRasterDirty(reason);
    }

    size_t invalidations = 0;

protected:
    ProbeFrame() = default;
};

/**
 * Three float values refreshed the way the Property window's vector, quaternion and Euler models refresh after an
 * edit made outside the panel: the new values reach the value models while the multi-field re-reads the children,
 * after one root notification.
 */
class VectorModel : public AbstractItemModel
{
public:
    static std::shared_ptr<VectorModel> create()
    {
        return std::shared_ptr<VectorModel>(new VectorModel);
    }

    void refresh(double x, double y, double z)
    {
        m_pending = { x, y, z };
        _itemChanged(nullptr);
    }

    double value(size_t i) const
    {
        return m_models[i]->getValueAsFloat();
    }

    std::vector<std::shared_ptr<const AbstractItem>> getItemChildren(const std::shared_ptr<const AbstractItem>&) override
    {
        if (!m_pending.empty())
        {
            for (size_t i = 0; i < m_models.size(); ++i)
            {
                m_models[i]->setValue(m_pending[i]);
            }
            m_pending.clear();
        }
        return { m_items.begin(), m_items.end() };
    }

    size_t getItemValueModelCount(const std::shared_ptr<const AbstractItem>&) override
    {
        return 1;
    }

    std::shared_ptr<AbstractValueModel> getItemValueModel(const std::shared_ptr<const AbstractItem>& item,
                                                          size_t) override
    {
        for (size_t i = 0; i < m_items.size(); ++i)
        {
            if (m_items[i] == item)
            {
                return m_models[i];
            }
        }
        return m_root;
    }

private:
    VectorModel()
    {
        for (int i = 0; i < 3; ++i)
        {
            m_items.push_back(std::make_shared<AbstractItem>());
            m_models.push_back(SimpleFloatModel::create(0.0));
        }
    }

    std::shared_ptr<AbstractValueModel> m_root = SimpleIntModel::create(0);
    std::vector<std::shared_ptr<AbstractItem>> m_items;
    std::vector<std::shared_ptr<AbstractValueModel>> m_models;
    std::vector<double> m_pending;
};

template <class Field>
void rootRefreshReachesTheFrame(const char* name)
{
    auto frame = ProbeFrame::create();
    auto model = VectorModel::create();
    std::shared_ptr<Field> field;
    OMNIKIT_WITH_CONTAINER(frame)
    {
        field = Field::create(model);
    }
    frame->invalidations = 0;

    model->refresh(12.5, -50.25, 26.0);

    check(model->value(0) == 12.5 && model->value(1) == -50.25 && model->value(2) == 26.0,
          std::string(name) + ": the root refresh reached the value models");
    check(frame->invalidations > 0,
          std::string(name) + ": a root refresh (_itemChanged(nullptr)) invalidates the enclosing raster frame");
}

template <class Field>
void valueModelChangeReachesTheFrame(const char* name)
{
    auto frame = ProbeFrame::create();
    auto model = SimpleListModel::create(std::vector<double>{ 0.0, 0.0, 0.0 });
    std::shared_ptr<Field> field;
    OMNIKIT_WITH_CONTAINER(frame)
    {
        field = Field::create(model);
    }
    frame->invalidations = 0;

    auto children = model->getItemChildren();
    model->getItemValueModel(children[1])->setValue(-75.5);

    check(model->getItemValueModel(children[1])->getValueAsFloat() == -75.5,
          std::string(name) + ": the value model holds the new value");
    check(frame->invalidations > 0,
          std::string(name) + ": setting one value model of the default list model invalidates the raster frame");
}

void probeSeesADirectChild()
{
    // Control: a single field that is an ordinary child of the frame reaches it on its own.
    auto frame = ProbeFrame::create();
    std::shared_ptr<AbstractValueModel> model = SimpleFloatModel::create(0.0);
    std::shared_ptr<FloatDrag> drag;
    OMNIKIT_WITH_CONTAINER(frame)
    {
        drag = FloatDrag::create(model);
    }
    frame->invalidations = 0;
    // The no-change path: the model already holds 0.0, so setting 0.0 again changes nothing and must not invalidate.
    model->setValue(0.0);
    check(frame->invalidations == 0, "control: no invalidation without a change");
    model->setValue(3.0);
    check(frame->invalidations > 0, "control: a FloatDrag child invalidates its raster frame when its value changes");
}

} // namespace

int main()
{
    // Layout (sizes of the fields) asks ImGui for frame heights and text sizes.
    ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1024.0f, 768.0f);
    io.Fonts->AddFontDefault();

    probeSeesADirectChild();
    rootRefreshReachesTheFrame<MultiFloatDragField>("MultiFloatDragField");
    rootRefreshReachesTheFrame<MultiFloatField>("MultiFloatField");
    valueModelChangeReachesTheFrame<MultiFloatDragField>("MultiFloatDragField");
    valueModelChangeReachesTheFrame<MultiFloatField>("MultiFloatField");

    ImGui::DestroyContext();
    std::cout << (g_failures ? "FAILED" : "PASSED") << " (" << g_failures << " failed checks)" << std::endl;
    return g_failures ? 1 : 0;
}
