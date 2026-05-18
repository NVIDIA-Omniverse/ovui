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

#include <omni/ui/platform/Assert.h>
#include <omni/ui/platform/Log.h>

#include <omni/ui/scene/CameraModel.h>

#include "AbstractManipulatorModelData.h"

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

struct CameraModel::CameraModelData : public AbstractManipulatorModel::AbstractManipulatorModelData
{
    class MatrixItem : public AbstractManipulatorItem
    {
    public:
        MatrixItem(const Matrix44& matrix)
        {
            setMatrix(matrix);
        }
        ~MatrixItem() override = default;

        const std::vector<Float>& getAsFloats() const
        {
            return m_floats;
        }

        Matrix44 getAsMatrix() const
        {
            return {
                m_floats[0], m_floats[1], m_floats[2],  m_floats[3],  m_floats[4],  m_floats[5],  m_floats[6],  m_floats[7],
                m_floats[8], m_floats[9], m_floats[10], m_floats[11], m_floats[12], m_floats[13], m_floats[14], m_floats[15],
            };
        }

        void setFloats(std::vector<Float>&& value)
        {
            m_floats = std::move(value);
        }

        void setMatrix(const Matrix44& matrix)
        {
            m_floats = { matrix[0][0], matrix[0][1], matrix[0][2], matrix[0][3], matrix[1][0], matrix[1][1],
                         matrix[1][2], matrix[1][3], matrix[2][0], matrix[2][1], matrix[2][2], matrix[2][3],
                         matrix[3][0], matrix[3][1], matrix[3][2], matrix[3][3] };
        }

    private:
        std::vector<Float> m_floats;
    };

    CameraModelData(const Matrix44& projection, const Matrix44& view)
        : m_projection(new MatrixItem(projection))
        , m_view(new MatrixItem(view))
    {
    }

    ~CameraModelData() override = default;


    std::shared_ptr<MatrixItem> m_projection;
    std::shared_ptr<MatrixItem> m_view;
};

CameraModel::CameraModel(const Matrix44& projection, const Matrix44& view)
    : AbstractManipulatorModel(new CameraModelData(projection, view))
{
}

CameraModel::~CameraModel() = default;

std::shared_ptr<const AbstractManipulatorModel::AbstractManipulatorItem> CameraModel::getItem(const std::string& identifier)
{
    if (identifier == "projection")
    {
        return _getModelData<CameraModelData>().m_projection;
    }

    if (identifier == "view")
    {
        return _getModelData<CameraModelData>().m_view;
    }

    OMNIUI_LOG_ERROR(
        "[CameraModel::getItem] There is no requested item '%s'. 'projection' and 'view' are the supported keys.",
        identifier.c_str());
    OMNIUI_ASSERT(0);
    return {};
}

std::vector<Float> CameraModel::getAsFloats(const std::shared_ptr<const AbstractManipulatorItem>& item)
{
    auto& modelData = _getModelData<CameraModelData>();
    if (item.get() == modelData.m_projection.get())
    {
        return modelData.m_projection->getAsFloats();
    }

    if (item.get() == modelData.m_view.get())
    {
        return modelData.m_view->getAsFloats();
    }

    OMNIUI_LOG_ERROR("[CameraModel::getAsFloats] There is no requested item in the model.");
    OMNIUI_ASSERT(0);
    return {};
}

std::vector<int64_t> CameraModel::getAsInts(const std::shared_ptr<const AbstractManipulatorItem>& item)
{
    OMNIUI_LOG_ERROR("[CameraModel::getAsInts] CameraModel doesn't support ints.");
    OMNIUI_ASSERT(0);
    return {};
}

void CameraModel::setFloats(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<Float> value)
{
    if (value.size() != 16)
    {
        OMNIUI_LOG_ERROR("[CameraModel::setFloats] It's only possible to set a list with 16 floats");
        return;
    }

    auto& modelData = _getModelData<CameraModelData>();
    if (item.get() == modelData.m_projection.get())
    {
        modelData.m_projection->setFloats(std::move(value));
        this->_itemChanged(modelData.m_projection);
        return;
    }

    if (item.get() == modelData.m_view.get())
    {
        modelData.m_view->setFloats(std::move(value));
        this->_itemChanged(modelData.m_view);
        return;
    }

    OMNIUI_LOG_ERROR("[CameraModel::setFloats] There is no requested item in the model.");
    OMNIUI_ASSERT(0);
}

void CameraModel::setInts(const std::shared_ptr<const AbstractManipulatorItem>& item, std::vector<int64_t> value)
{
    OMNIUI_LOG_ERROR("[CameraModel::setInts] CameraModel doesn't support ints.");
    OMNIUI_ASSERT(0);
}

Matrix44 CameraModel::getProjection() const
{
    return _getModelData<CameraModelData>().m_projection->getAsMatrix();
}

Matrix44 CameraModel::getView() const
{
    return _getModelData<CameraModelData>().m_view->getAsMatrix();
}

void CameraModel::setProjection(const Matrix44& projection)
{
    auto& modelData = _getModelData<CameraModelData>();
    modelData.m_projection->setMatrix(projection);
    this->_itemChanged(modelData.m_projection);
}

void CameraModel::setView(const Matrix44& view)
{
    auto& modelData = _getModelData<CameraModelData>();
    modelData.m_view->setMatrix(view);
    this->_itemChanged(modelData.m_view);
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
