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

#include <omni/ui/StyleStore.h>
#include <omni/ui/bind/BindUtils.h>
#include <omni/ui/scene/bind/BindMath.h>

using namespace pybind11;

OMNIUI_SCENE_NAMESPACE_OPEN_SCOPE

/**
 * @brief We need this class because pybind11 wants to have different classes
 * for Vector4 and Color4.
 */
class _Color4 : public Color4
{
public:
    _Color4(const Color4& color) : Color4{ color }
    {
    }

    _Color4(Float r = Float(0.0)) : Color4{ r }
    {
    }

    _Color4(Float r, Float g, Float b, Float a) : Color4{ r, g, b, a }
    {
    }
};

static Color4 intToColor(uint32_t color)
{
    float s = 1.0f / 255.0f;
    return { ((color >> 0) & 0xFF) * s, ((color >> 8) & 0xFF) * s, ((color >> 16) & 0xFF) * s,
             ((color >> 24) & 0xFF) * s };
}

object matrix4ToPython(const Matrix44& matrix)
{
    list result{ 16 };
    result[0] = matrix[0][0];
    result[1] = matrix[0][1];
    result[2] = matrix[0][2];
    result[3] = matrix[0][3];
    result[4] = matrix[1][0];
    result[5] = matrix[1][1];
    result[6] = matrix[1][2];
    result[7] = matrix[1][3];
    result[8] = matrix[2][0];
    result[9] = matrix[2][1];
    result[10] = matrix[2][2];
    result[11] = matrix[2][3];
    result[12] = matrix[3][0];
    result[13] = matrix[3][1];
    result[14] = matrix[3][2];
    result[15] = matrix[3][3];
    return result;
}

Matrix44 pythonToMatrix4(const handle& obj)
{
    if (isinstance<Matrix44>(obj))
    {
        return obj.cast<Matrix44>();
    }
    else if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 16)
        {
            return Matrix44(
                static_cast<Float>(pythonList[0].cast<float_>()), static_cast<Float>(pythonList[1].cast<float_>()),
                static_cast<Float>(pythonList[2].cast<float_>()), static_cast<Float>(pythonList[3].cast<float_>()),
                static_cast<Float>(pythonList[4].cast<float_>()), static_cast<Float>(pythonList[5].cast<float_>()),
                static_cast<Float>(pythonList[6].cast<float_>()), static_cast<Float>(pythonList[7].cast<float_>()),
                static_cast<Float>(pythonList[8].cast<float_>()), static_cast<Float>(pythonList[9].cast<float_>()),
                static_cast<Float>(pythonList[10].cast<float_>()), static_cast<Float>(pythonList[11].cast<float_>()),
                static_cast<Float>(pythonList[12].cast<float_>()), static_cast<Float>(pythonList[13].cast<float_>()),
                static_cast<Float>(pythonList[14].cast<float_>()), static_cast<Float>(pythonList[15].cast<float_>()));
        }
        else if (pythonList.size() == 1)
        {
            return Matrix44{ static_cast<Float>(pythonList[0].cast<float_>()) };
        }
    }
    else if (isinstance<float_>(obj) || isinstance<int_>(obj))
    {
        return Matrix44{ static_cast<Float>(obj.cast<float_>()) };
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to Matrix4");

    return Matrix44{ (Float)1.0 };
}

pybind11::object vector2ToPython(const Vector2& vec)
{
    list result{ 2 };
    result[0] = vec.x;
    result[1] = vec.y;
    return result;
}

Vector2 pythonToVector2(const handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 2)
        {
            return Vector2{ static_cast<Float>(pythonList[0].cast<float_>()),
                            static_cast<Float>(pythonList[1].cast<float_>()) };
        }
        else if (pythonList.size() == 1)
        {
            return Vector2{ static_cast<Float>(pythonList[0].cast<float_>()) };
        }
    }
    else if (isinstance<float_>(obj) || isinstance<int_>(obj))
    {
        return Vector2{ static_cast<Float>(obj.cast<float_>()) };
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to Vector2");

    return Vector2{};
}

pybind11::object vector3ToPython(const Vector3& vec)
{
    list result{ 3 };
    result[0] = vec.x;
    result[1] = vec.y;
    result[2] = vec.z;
    return result;
}

Vector3 pythonToVector3(const handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 3)
        {
            return Vector3{ static_cast<Float>(pythonList[0].cast<float_>()),
                            static_cast<Float>(pythonList[1].cast<float_>()),
                            static_cast<Float>(pythonList[2].cast<float_>()) };
        }
        else if (pythonList.size() == 1)
        {
            return Vector3{ static_cast<Float>(pythonList[0].cast<float_>()) };
        }
    }
    else if (isinstance<float_>(obj) || isinstance<int_>(obj))
    {
        return Vector3{ static_cast<Float>(obj.cast<float_>()) };
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to Vector3");

    return Vector3{};
}

pybind11::object vector4ToPython(const Vector4& vec)
{
    list result{ 4 };
    result[0] = vec.x;
    result[1] = vec.y;
    result[2] = vec.z;
    result[3] = vec.w;
    return result;
}

Vector4 pythonToVector4(const handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 4)
        {
            return Vector4{ static_cast<Float>(pythonList[0].cast<float_>()),
                            static_cast<Float>(pythonList[1].cast<float_>()),
                            static_cast<Float>(pythonList[2].cast<float_>()),
                            static_cast<Float>(pythonList[3].cast<float_>()) };
        }
        else if (pythonList.size() == 1)
        {
            return Vector4{ static_cast<Float>(pythonList[0].cast<float_>()) };
        }
    }
    else if (isinstance<float_>(obj) || isinstance<int_>(obj))
    {
        return Vector4{ static_cast<Float>(obj.cast<float_>()) };
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to Vector4");

    return Vector4{};
}

Color4 pythonToColor4(const handle& obj)
{
    if (isinstance<int_>(obj))
    {
        uint32_t color = static_cast<uint32_t>(obj.cast<int_>());
        return intToColor(color);
    }
    else if (isinstance<pybind11::str>(obj))
    {
        auto& store = omni::ui::ColorStore::getInstance();
        size_t found = store.find(obj.cast<std::string>());
        if (found != SIZE_MAX)
        {
            uint32_t color = store.get(found);
            return intToColor(color);
        }
    }

    return pythonToVector4(obj);
}

std::vector<Vector2> pythonListToVector2(const pybind11::handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 2 && (isinstance<float_>(pythonList[0]) || isinstance<int_>(pythonList[0])))
        {
            std::vector<Vector2> result;
            result.emplace_back(static_cast<Float>(pythonList[0].cast<float_>()),
                                static_cast<Float>(pythonList[1].cast<float_>()));
            return result;
        }
        else
        {
            std::vector<Vector2> result;
            result.reserve(pythonList.size());
            for (const auto& a : pythonList)
            {
                result.push_back(pythonToVector2(a));
            }
            return result;
        }
    }
    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                    " can't be converted to std::vector<Vector2>");

    return {};
}

std::vector<Vector3> pythonListToVector3(const pybind11::handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 3 && (isinstance<float_>(pythonList[0]) || isinstance<int_>(pythonList[0])))
        {
            std::vector<Vector3> result;
            result.emplace_back(static_cast<Float>(pythonList[0].cast<float_>()),
                                static_cast<Float>(pythonList[1].cast<float_>()),
                                static_cast<Float>(pythonList[2].cast<float_>()));
            return result;
        }
        else
        {
            std::vector<Vector3> result;
            result.reserve(pythonList.size());
            for (const auto& a : pythonList)
            {
                if (!isinstance<tuple>(a) && !isinstance<list>(a))
                {
                    throw type_error("One of the members is of type " +
                                     static_cast<std::string>(pybind11::str(a.get_type())) +
                                     " can't be converted it to Vector3");
                }

                list pythonSubList = a.cast<list>();
                result.emplace_back(static_cast<Float>(pythonSubList[0].cast<float_>()),
                                    static_cast<Float>(pythonSubList[1].cast<float_>()),
                                    static_cast<Float>(pythonSubList[2].cast<float_>()));
            }
            return result;
        }
    }

    throw type_error("The value of type " + static_cast<std::string>(pybind11::str(obj.get_type())) +
                     " can't be converted to std::vector<Vector3>");

    return {};
}

std::vector<Vector4> pythonListToVector4(const pybind11::handle& obj)
{
    if (isinstance<tuple>(obj) || isinstance<list>(obj))
    {
        list pythonList = obj.cast<list>();
        if (pythonList.size() == 4 && (isinstance<float_>(pythonList[0]) || isinstance<int_>(pythonList[0])))
        {
            // It's one vector
        }
        else
        {
            std::vector<Vector4> result;
            result.reserve(pythonList.size());
            for (const auto& a : pythonList)
            {
                result.push_back(pythonToColor4(a));
            }
            return result;
        }
    }

    std::vector<Vector4> result;
    result.push_back(pythonToColor4(obj));
    return result;
}

pybind11::object vector2ToPythonList(const std::vector<Vector2>& vec)
{
    list result{ vec.size() };

    for (size_t i = 0, n = vec.size(); i < n; ++i)
    {
        list sublist = list{ 2 };
        sublist[0] = vec[i].x;
        sublist[1] = vec[i].y;
        result[i] = std::move(sublist);
    }
    return result;
}

pybind11::object vector3ToPythonList(const std::vector<Vector3>& vec)
{
    list result{ vec.size() };

    for (size_t i = 0, n = vec.size(); i < n; ++i)
    {
        list sublist = list{ 3 };
        sublist[0] = vec[i].x;
        sublist[1] = vec[i].y;
        sublist[2] = vec[i].z;
        result[i] = std::move(sublist);
    }
    return result;
}

pybind11::object vector4ToPythonList(const std::vector<Vector4>& vec)
{
    list result{ vec.size() };

    for (size_t i = 0, n = vec.size(); i < n; ++i)
    {
        list sublist = list{ 4 };
        sublist[0] = vec[i].x;
        sublist[1] = vec[i].y;
        sublist[2] = vec[i].z;
        sublist[3] = vec[i].w;
        result[i] = std::move(sublist);
    }
    return result;
}

OMNIUI_SCENE_NAMESPACE_CLOSE_SCOPE
OMNIUI_SCENE_NAMESPACE_USING_DIRECTIVE

void wrapMath(module& m)
{
    m.def("Cross", [](const handle& v1, const handle& v2) { return vector3ToPython(glm::cross(pythonToVector3(v1), pythonToVector3(v2))); });
    m.def("Dot", [](const handle& a, const handle& b) { return glm::dot(pythonToVector3(a), pythonToVector3(b)); });

    constexpr const char* matrixDoc = OMNIUI_PYBIND_CLASS_DOC(Matrix44);

    class_<Matrix44>(m, "Matrix44", matrixDoc)
        .def(init<Matrix44>(), arg("m"))
        .def(init<Float>(), arg("x") = 1.0)
        .def(init<Float, Float, Float, Float, Float, Float, Float, Float, Float, Float, Float, Float, Float, Float,
                  Float, Float>(),
             arg("a1"), arg("a2"), arg("a3"), arg("a4"), arg("a5"), arg("a6"), arg("a7"), arg("a8"), arg("a9"),
             arg("a10"), arg("a11"), arg("a12"), arg("a13"), arg("a14"), arg("a15"), arg("a16"))
        .def("get_inverse", &Matrix44::getInverse)
        .def_property_readonly("inversed", &Matrix44::getInverse)
        .def_static("get_translation_matrix", &Matrix44::getTranslationMatrix, arg("x"), arg("y"), arg("z"),
                    OMNIUI_PYBIND_DOC_Matrix44_getTranslationMatrix)
        .def_static("get_scale_matrix", &Matrix44::getScaleMatrix, arg("x"), arg("y"), arg("z"),
                    OMNIUI_PYBIND_DOC_Matrix44_getScaleMatrix)
        .def_static("get_rotation_matrix", &Matrix44::getRotationMatrix, arg("x"), arg("y"), arg("z"),
                    arg("degrees") = false, OMNIUI_PYBIND_DOC_Matrix44_getRotationMatrix)
        .def("__mul__", [](const Matrix44& self, const Matrix44& other) -> Matrix44 { return self * other; })
        .def("__mul__", [](const Matrix44& self, const Vector4& other) -> Vector4 { return self * other; })
        .def("__mul__",
             [](const Matrix44& self, const Vector3& other) -> Vector3 {
                 Vector4 result = self * Vector4(other, Float(0.0));
                 return Vector3(result.x, result.y, result.z);
             })
        .def("__rmul__", [](const Matrix44& self, const Matrix44& other) -> Matrix44 { return other * self; })
        .def("__eq__", [](const Matrix44& self, const Matrix44& other) -> bool { return self == other; })
        .def("__ne__", [](const Matrix44& self, const Matrix44& other) -> bool { return other != self; })
        .def("__getitem__",
             [](const Matrix44& self, int index)
             {
                 if (index < 0 || index > 15)
                 {
                     throw index_error("Can't get index " + std::to_string(index) + " of omni.ui.scene.Matrix44");
                     return Float(0.0);
                 }
                 return self[index / 4][index % 4];
             })
        .def("__setitem__",
             [](Matrix44& self, int index, Float value)
             {
                 if (index < 0 || index > 15)
                 {
                     throw index_error("Can't set index " + std::to_string(index) + " of omni.ui.scene.Matrix44");
                     return;
                 }
                 self[index / 4][index % 4] = value;
             })
        .def("__repr__",
             [](const Matrix44& self) -> std::string
             {
                 return "<omni.ui.scene.Matrix44 " + std::to_string(self[0][0]) + ", " + std::to_string(self[0][1]) +
                        ", " + std::to_string(self[0][2]) + ", " + std::to_string(self[0][3]) + ", " +
                        std::to_string(self[1][0]) + ", " + std::to_string(self[1][1]) + ", " +
                        std::to_string(self[1][2]) + ", " + std::to_string(self[1][3]) + ", " +
                        std::to_string(self[2][0]) + ", " + std::to_string(self[2][1]) + ", " +
                        std::to_string(self[2][2]) + ", " + std::to_string(self[2][3]) + ", " +
                        std::to_string(self[3][0]) + ", " + std::to_string(self[3][1]) + ", " +
                        std::to_string(self[3][2]) + ", " + std::to_string(self[3][3]) + ">";
             })
        .def("get_inverse", &Matrix44::getInverse)
        .def("set_look_at_view", &Matrix44::setLookAtView)
        /**/;

    class_<Vector2>(m, "Vector2")
        .def(init<Vector2>(), arg("v"))
        .def(init<Float>(), arg("x") = 0.0)
        .def(init<Float, Float>(), arg("x"), arg("y"))
        .def("__eq__", [](const Vector2& self, const Vector2& other) -> bool { return self == other; })
        .def("__add__", [](const Vector2& self, const Vector2& other) -> Vector2 { return self + other; })
        .def("__getitem__",
             [](const Vector2& self, int index)
             {
                 if (index < 0 || index > 1)
                 {
                     throw index_error("Can't get index " + std::to_string(index) + " of omni.ui.scene.Vector2");
                     return Float(0.0);
                 }
                 return self[index];
             })
        .def("__setitem__",
             [](Vector2& self, int index, Float value)
             {
                 if (index < 0 || index > 1)
                 {
                     throw index_error("Can't set index " + std::to_string(index) + " of omni.ui.scene.Vector2");
                     return;
                 }
                 self[index] = value;
             })
        .def("__repr__",
             [](const Vector2& self) -> std::string {
                 return "<omni.ui.scene.Vector2 " + std::to_string(self[0]) + ", " + std::to_string(self[1]) + ">";
             })
        .def("get_normalized", [](const Vector2& self) -> Vector2 { return glm::normalize(self); })
        .def("get_length", [](const Vector2& self) -> Float { return glm::length(self); })
        .def_readwrite("x", &Vector2::x)
        .def_readwrite("y", &Vector2::y)
        /**/;

    class_<Vector3>(m, "Vector3")
        .def(init<Vector3>(), arg("v"))
        .def(init<Float>(), arg("x") = 0.0)
        .def(init<Float, Float, Float>(), arg("x"), arg("y"), arg("z"))
        .def("__eq__", [](const Vector3& self, const Vector3& other) -> bool { return self == other; })
        .def("__add__", [](const Vector3& self, const Vector3& other) -> Vector3 { return self + other; })
        .def("__mul__", [](const Vector3& self, const Vector3& other) -> Vector3 { return glm::cross(self, other); })
        .def("__matmul__", [](const Vector3& self, const Vector3& other) -> Float { return glm::dot(self, other); })
        .def("__getitem__",
             [](const Vector3& self, int index)
             {
                 if (index < 0 || index > 2)
                 {
                     throw index_error("Can't get index " + std::to_string(index) + " of omni.ui.scene.Vector3");
                     return Float(0.0);
                 }
                 return self[index];
             })
        .def("__setitem__",
             [](Vector3& self, int index, Float value)
             {
                 if (index < 0 || index > 2)
                 {
                     throw index_error("Can't set index " + std::to_string(index) + " of omni.ui.scene.Vector3");
                     return;
                 }
                 self[index] = value;
             })
        .def("__repr__",
             [](const Vector3& self) -> std::string {
                 return "<omni.ui.scene.Vector3 " + std::to_string(self[0]) + ", " + std::to_string(self[1]) + ", " +
                        std::to_string(self[2]) + ">";
             })
        .def("get_normalized", [](const Vector3& self) -> Vector3 { return glm::normalize(self); })
        .def("get_length", [](const Vector3& self) -> Float { return glm::length(self); })
        .def_readwrite("x", &Vector3::x)
        .def_readwrite("y", &Vector3::y)
        .def_readwrite("z", &Vector3::z)
        /**/;

    class_<Vector4>(m, "Vector4")
        .def(init<Vector4>(), arg("v"))
        .def(init<Float>(), arg("x") = 0.0)
        .def(init<Float, Float, Float, Float>(), arg("x"), arg("y"), arg("z"), arg("w"))
        .def(init<Vector3, Float>(), arg("v"), arg("w"))
        .def("__eq__", [](const Vector4& self, const Vector4& other) -> bool { return self == other; })
        .def("__add__", [](const Vector4& self, const Vector4& other) -> Vector4 { return self + other; })
        .def("__getitem__",
             [](const Vector4& self, int index)
             {
                 if (index < 0 || index > 3)
                 {
                     throw index_error("Can't get index " + std::to_string(index) + " of omni.ui.scene.Vector4");
                     return Float(0.0);
                 }
                 return self[index];
             })
        .def("__setitem__",
             [](Vector4& self, int index, Float value)
             {
                 if (index < 0 || index > 3)
                 {
                     throw index_error("Can't set index " + std::to_string(index) + " of omni.ui.scene.Vector4");
                     return;
                 }
                 self[index] = value;
             })
        .def("__repr__",
             [](const Vector4& self) -> std::string {
                 return "<omni.ui.scene.Vector4 " + std::to_string(self[0]) + ", " + std::to_string(self[1]) + ", " +
                        std::to_string(self[2]) + ", " + std::to_string(self[3]) + ">";
             })
        .def("get_normalized", [](const Vector4& self) -> Vector4 { return glm::normalize(self); })
        .def("get_length", [](const Vector4& self) -> Float { return glm::length(self); })
        .def_readwrite("x", &Vector4::x)
        .def_readwrite("y", &Vector4::y)
        .def_readwrite("z", &Vector4::z)
        .def_readwrite("w", &Vector4::w)
        /**/;

    class_<_Color4>(m, "Color4")
        .def(init<Color4>(), arg("c"))
        .def(init<Float>(), arg("r") = 0.0)
        .def(init<Float, Float, Float, Float>(), arg("r"), arg("g"), arg("b"), arg("a"))
        .def("__add__", [](const Color4& self, const Color4& other) -> Color4 { return self + other; })
        .def("__eq__", [](const Color4& self, const Color4& other) -> bool { return self == other; })
        .def("__getitem__",
             [](const Color4& self, int index)
             {
                 if (index < 0 || index > 3)
                 {
                     throw index_error("Can't get index " + std::to_string(index) + " of omni.ui.scene.Color4");
                     return Float(0.0);
                 }
                 return self[index];
             })
        .def("__setitem__",
             [](Color4& self, int index, Float value)
             {
                 if (index < 0 || index > 3)
                 {
                     throw index_error("Can't set index " + std::to_string(index) + " of omni.ui.scene.Color4");
                     return;
                 }
                 self[index] = value;
             })
        .def("__repr__",
             [](const Color4& self) -> std::string {
                 return "<omni.ui.scene.Color4 " + std::to_string(self[0]) + ", " + std::to_string(self[1]) + ", " +
                        std::to_string(self[2]) + ", " + std::to_string(self[3]) + ">";
             })
        .def_readwrite("r", &Vector4::r)
        .def_readwrite("g", &Vector4::g)
        .def_readwrite("b", &Vector4::b)
        .def_readwrite("a", &Vector4::a)
        /**/;
}
