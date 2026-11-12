/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Vertex and index upload of the ImGui OpenGL3 renderer.
 *
 * The renderer gets its OpenGL entry points from the imgl3w table of its
 * loader. This test fills the table with fake entry points, so the real
 * renderer code runs with no GPU, window or driver. The fakes record each
 * glBufferData() call and each draw call.
 *
 * What is checked:
 *   - with OpenGL 3.3, a frame with several draw lists makes one glBufferData()
 *     call for the vertices and one for the indices. Upstream made one of each
 *     for every draw list, and the NVIDIA OpenGL driver on Windows kept about
 *     16 KB of private memory for each frame of that pattern;
 *   - the uploaded bytes are the vertices and indices of all draw lists, in
 *     draw-list order;
 *   - each draw call reads its own commands: the index offset and the base
 *     vertex include the start of its draw list in the shared buffers, the
 *     index count is the command's count, in command order;
 *   - with OpenGL 3.1 (no glDrawElementsBaseVertex), each draw list keeps its
 *     own upload, and the draws read from the start of the buffers.
 *
 * Each case runs to the end and reports alone. On the old renderer the upload
 * count and offset checks fail.
 */

#include <imgui.h>

#include "imgui_impl_opengl3.h"
#include "imgui_impl_opengl3_loader.h"

#include <cstdint>
#include <cstring>
#include <iostream>
#include <string>
#include <vector>

// Values from the OpenGL headers that the minimal loader header leaves out.
#ifndef GL_NO_ERROR
#    define GL_NO_ERROR 0
#endif
#ifndef GL_CONTEXT_CORE_PROFILE_BIT
#    define GL_CONTEXT_CORE_PROFILE_BIT 0x00000001
#endif
#ifndef GL_SHADING_LANGUAGE_VERSION
#    define GL_SHADING_LANGUAGE_VERSION 0x8B8C
#endif

namespace
{

int g_totalCases = 0;
int g_failedCases = 0;
bool g_caseFailed = false;

void check(bool ok, const std::string& what)
{
    if (!ok)
    {
        g_caseFailed = true;
        std::cout << "  FAIL: " << what << std::endl;
    }
}

struct Upload
{
    GLenum target;
    std::vector<unsigned char> bytes;
};

struct Draw
{
    GLsizei count;
    std::uintptr_t indexByteOffset;
    GLint baseVertex;
};

struct FakeGl
{
    GLint major = 3;
    GLint minor = 3;
    GLuint nextName = 1;
    std::vector<Upload> uploads;
    std::vector<Draw> draws;
};

FakeGl g_gl;

void APIENTRY fakeActiveTexture(GLenum) {}
void APIENTRY fakeAttachShader(GLuint, GLuint) {}
void APIENTRY fakeBindBuffer(GLenum, GLuint) {}
void APIENTRY fakeBindSampler(GLuint, GLuint) {}
void APIENTRY fakeBindTexture(GLenum, GLuint) {}
void APIENTRY fakeBindVertexArray(GLuint) {}
void APIENTRY fakeBlendEquation(GLenum) {}
void APIENTRY fakeBlendEquationSeparate(GLenum, GLenum) {}
void APIENTRY fakeBlendFuncSeparate(GLenum, GLenum, GLenum, GLenum) {}
void APIENTRY fakeBufferData(GLenum target, GLsizeiptr size, const void* data, GLenum)
{
    Upload upload{target, {}};
    if (data && size > 0)
    {
        const auto* bytes = static_cast<const unsigned char*>(data);
        upload.bytes.assign(bytes, bytes + size);
    }
    else
    {
        upload.bytes.resize(static_cast<size_t>(size > 0 ? size : 0));
    }
    g_gl.uploads.push_back(std::move(upload));
}
void APIENTRY fakeBufferSubData(GLenum, GLintptr, GLsizeiptr, const void*) {}
void APIENTRY fakeClear(GLbitfield) {}
void APIENTRY fakeClearColor(GLfloat, GLfloat, GLfloat, GLfloat) {}
void APIENTRY fakeCompileShader(GLuint) {}
GLuint APIENTRY fakeCreateProgram()
{
    return g_gl.nextName++;
}
GLuint APIENTRY fakeCreateShader(GLenum)
{
    return g_gl.nextName++;
}
void APIENTRY fakeDeleteBuffers(GLsizei, const GLuint*) {}
void APIENTRY fakeDeleteProgram(GLuint) {}
void APIENTRY fakeDeleteSamplers(GLsizei, const GLuint*) {}
void APIENTRY fakeDeleteShader(GLuint) {}
void APIENTRY fakeDeleteTextures(GLsizei, const GLuint*) {}
void APIENTRY fakeDeleteVertexArrays(GLsizei, const GLuint*) {}
void APIENTRY fakeDetachShader(GLuint, GLuint) {}
void APIENTRY fakeDisable(GLenum) {}
void APIENTRY fakeDisableVertexAttribArray(GLuint) {}
void APIENTRY fakeDrawElements(GLenum, GLsizei count, GLenum, const void* indices)
{
    g_gl.draws.push_back({count, reinterpret_cast<std::uintptr_t>(indices), 0});
}
void APIENTRY fakeDrawElementsBaseVertex(GLenum, GLsizei count, GLenum, const void* indices, GLint baseVertex)
{
    g_gl.draws.push_back({count, reinterpret_cast<std::uintptr_t>(indices), baseVertex});
}
void APIENTRY fakeEnable(GLenum) {}
void APIENTRY fakeEnableVertexAttribArray(GLuint) {}
void APIENTRY fakeFlush() {}
void fakeGen(GLsizei n, GLuint* names)
{
    for (GLsizei i = 0; i < n; ++i)
        names[i] = g_gl.nextName++;
}
void APIENTRY fakeGenBuffers(GLsizei n, GLuint* names)
{
    fakeGen(n, names);
}
void APIENTRY fakeGenSamplers(GLsizei n, GLuint* names)
{
    fakeGen(n, names);
}
void APIENTRY fakeGenTextures(GLsizei n, GLuint* names)
{
    fakeGen(n, names);
}
void APIENTRY fakeGenVertexArrays(GLsizei n, GLuint* names)
{
    fakeGen(n, names);
}
GLint APIENTRY fakeGetAttribLocation(GLuint, const GLchar* name)
{
    return std::strcmp(name, "Position") == 0 ? 0 : (std::strcmp(name, "UV") == 0 ? 1 : 2);
}
GLenum APIENTRY fakeGetError()
{
    return GL_NO_ERROR;
}
void APIENTRY fakeGetIntegerv(GLenum pname, GLint* data)
{
    switch (pname)
    {
    case GL_MAJOR_VERSION:
        data[0] = g_gl.major;
        return;
    case GL_MINOR_VERSION:
        data[0] = g_gl.minor;
        return;
    case GL_CONTEXT_PROFILE_MASK:
        data[0] = GL_CONTEXT_CORE_PROFILE_BIT;
        return;
    case GL_MAX_TEXTURE_SIZE:
        data[0] = 16384;
        return;
    case GL_VIEWPORT:
    case GL_SCISSOR_BOX:
        data[0] = data[1] = data[2] = data[3] = 0;
        return;
    case GL_POLYGON_MODE:
        data[0] = data[1] = GL_FILL;
        return;
    default:
        data[0] = 0;
        return;
    }
}
void APIENTRY fakeGetProgramInfoLog(GLuint, GLsizei, GLsizei* length, GLchar* log)
{
    if (length)
        *length = 0;
    if (log)
        log[0] = 0;
}
void APIENTRY fakeGetProgramiv(GLuint, GLenum pname, GLint* params)
{
    params[0] = pname == GL_LINK_STATUS ? GL_TRUE : 0;
}
void APIENTRY fakeGetShaderInfoLog(GLuint, GLsizei, GLsizei* length, GLchar* log)
{
    if (length)
        *length = 0;
    if (log)
        log[0] = 0;
}
void APIENTRY fakeGetShaderiv(GLuint, GLenum pname, GLint* params)
{
    params[0] = pname == GL_COMPILE_STATUS ? GL_TRUE : 0;
}
const GLubyte* APIENTRY fakeGetString(GLenum name)
{
    static const char* vendor = "Fake";
    static const char* version = "3.3.0 Fake";
    static const char* glsl = "3.30";
    const char* text = name == GL_VERSION ? version : (name == GL_SHADING_LANGUAGE_VERSION ? glsl : vendor);
    return reinterpret_cast<const GLubyte*>(text);
}
const GLubyte* APIENTRY fakeGetStringi(GLenum, GLuint)
{
    return reinterpret_cast<const GLubyte*>("");
}
GLint APIENTRY fakeGetUniformLocation(GLuint, const GLchar* name)
{
    return std::strcmp(name, "Texture") == 0 ? 0 : 1;
}
void APIENTRY fakeGetVertexAttribPointerv(GLuint, GLenum, void** pointer)
{
    *pointer = nullptr;
}
void APIENTRY fakeGetVertexAttribiv(GLuint, GLenum, GLint* params)
{
    params[0] = 0;
}
GLboolean APIENTRY fakeIsEnabled(GLenum)
{
    return GL_FALSE;
}
GLboolean APIENTRY fakeIsProgram(GLuint)
{
    return GL_TRUE;
}
void APIENTRY fakeLinkProgram(GLuint) {}
void APIENTRY fakePixelStorei(GLenum, GLint) {}
void APIENTRY fakePolygonMode(GLenum, GLenum) {}
void APIENTRY fakeReadPixels(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void*) {}
void APIENTRY fakeSamplerParameteri(GLuint, GLenum, GLint) {}
void APIENTRY fakeScissor(GLint, GLint, GLsizei, GLsizei) {}
void APIENTRY fakeShaderSource(GLuint, GLsizei, const GLchar* const*, const GLint*) {}
void APIENTRY fakeTexImage2D(GLenum, GLint, GLint, GLsizei, GLsizei, GLint, GLenum, GLenum, const void*) {}
void APIENTRY fakeTexParameteri(GLenum, GLenum, GLint) {}
void APIENTRY fakeTexSubImage2D(GLenum, GLint, GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, const void*) {}
void APIENTRY fakeUniform1i(GLint, GLint) {}
void APIENTRY fakeUniformMatrix4fv(GLint, GLsizei, GLboolean, const GLfloat*) {}
void APIENTRY fakeUseProgram(GLuint) {}
void APIENTRY fakeVertexAttribPointer(GLuint, GLint, GLenum, GLboolean, GLsizei, const void*) {}
void APIENTRY fakeViewport(GLint, GLint, GLsizei, GLsizei) {}

void installFakeGl()
{
    auto& gl = imgl3wProcs.gl;
    gl.ActiveTexture = fakeActiveTexture;
    gl.AttachShader = fakeAttachShader;
    gl.BindBuffer = fakeBindBuffer;
    gl.BindSampler = fakeBindSampler;
    gl.BindTexture = fakeBindTexture;
    gl.BindVertexArray = fakeBindVertexArray;
    gl.BlendEquation = fakeBlendEquation;
    gl.BlendEquationSeparate = fakeBlendEquationSeparate;
    gl.BlendFuncSeparate = fakeBlendFuncSeparate;
    gl.BufferData = fakeBufferData;
    gl.BufferSubData = fakeBufferSubData;
    gl.Clear = fakeClear;
    gl.ClearColor = fakeClearColor;
    gl.CompileShader = fakeCompileShader;
    gl.CreateProgram = fakeCreateProgram;
    gl.CreateShader = fakeCreateShader;
    gl.DeleteBuffers = fakeDeleteBuffers;
    gl.DeleteProgram = fakeDeleteProgram;
    gl.DeleteSamplers = fakeDeleteSamplers;
    gl.DeleteShader = fakeDeleteShader;
    gl.DeleteTextures = fakeDeleteTextures;
    gl.DeleteVertexArrays = fakeDeleteVertexArrays;
    gl.DetachShader = fakeDetachShader;
    gl.Disable = fakeDisable;
    gl.DisableVertexAttribArray = fakeDisableVertexAttribArray;
    gl.DrawElements = fakeDrawElements;
    gl.DrawElementsBaseVertex = fakeDrawElementsBaseVertex;
    gl.Enable = fakeEnable;
    gl.EnableVertexAttribArray = fakeEnableVertexAttribArray;
    gl.Flush = fakeFlush;
    gl.GenBuffers = fakeGenBuffers;
    gl.GenSamplers = fakeGenSamplers;
    gl.GenTextures = fakeGenTextures;
    gl.GenVertexArrays = fakeGenVertexArrays;
    gl.GetAttribLocation = fakeGetAttribLocation;
    gl.GetError = fakeGetError;
    gl.GetIntegerv = fakeGetIntegerv;
    gl.GetProgramInfoLog = fakeGetProgramInfoLog;
    gl.GetProgramiv = fakeGetProgramiv;
    gl.GetShaderInfoLog = fakeGetShaderInfoLog;
    gl.GetShaderiv = fakeGetShaderiv;
    gl.GetString = fakeGetString;
    gl.GetStringi = fakeGetStringi;
    gl.GetUniformLocation = fakeGetUniformLocation;
    gl.GetVertexAttribPointerv = fakeGetVertexAttribPointerv;
    gl.GetVertexAttribiv = fakeGetVertexAttribiv;
    gl.IsEnabled = fakeIsEnabled;
    gl.IsProgram = fakeIsProgram;
    gl.LinkProgram = fakeLinkProgram;
    gl.PixelStorei = fakePixelStorei;
    gl.PolygonMode = fakePolygonMode;
    gl.ReadPixels = fakeReadPixels;
    gl.SamplerParameteri = fakeSamplerParameteri;
    gl.Scissor = fakeScissor;
    gl.ShaderSource = fakeShaderSource;
    gl.TexImage2D = fakeTexImage2D;
    gl.TexParameteri = fakeTexParameteri;
    gl.TexSubImage2D = fakeTexSubImage2D;
    gl.Uniform1i = fakeUniform1i;
    gl.UniformMatrix4fv = fakeUniformMatrix4fv;
    gl.UseProgram = fakeUseProgram;
    gl.VertexAttribPointer = fakeVertexAttribPointer;
    gl.Viewport = fakeViewport;
    for (GL3WglProc proc : imgl3wProcs.ptr)
        check(proc != nullptr, "every entry of the fake OpenGL table is set");
}

// One frame with several separate windows, so the draw data holds several draw lists.
ImDrawData* buildFrame(int frame)
{
    ImGuiIO& io = ImGui::GetIO();
    io.DisplaySize = ImVec2(1280.0f, 720.0f);
    io.DeltaTime = 1.0f / 60.0f;
    ImGui::NewFrame();
    const char* names[] = {"Stage", "Layers", "Property", "Content"};
    for (int i = 0; i < 4; ++i)
    {
        ImGui::SetNextWindowPos(ImVec2(20.0f + 300.0f * i, 20.0f), ImGuiCond_Always);
        ImGui::SetNextWindowSize(ImVec2(280.0f, 200.0f), ImGuiCond_Always);
        ImGui::Begin(names[i]);
        ImGui::Text("frame %d window %d", frame, i);
        for (int line = 0; line <= i; ++line)
            ImGui::Button("button");
        ImGui::End();
    }
    ImGui::Render();
    return ImGui::GetDrawData();
}

struct Expected
{
    std::vector<unsigned char> vertices;
    std::vector<unsigned char> indices;
    std::vector<Draw> draws;
};

// The draws the renderer must issue for this draw data when all draw lists share one upload.
Expected expectedShared(const ImDrawData* data)
{
    Expected e;
    int vtxBase = 0;
    int idxBase = 0;
    for (const ImDrawList* list : data->CmdLists)
    {
        const auto* v = reinterpret_cast<const unsigned char*>(list->VtxBuffer.Data);
        const auto* i = reinterpret_cast<const unsigned char*>(list->IdxBuffer.Data);
        e.vertices.insert(e.vertices.end(), v, v + list->VtxBuffer.size_in_bytes());
        e.indices.insert(e.indices.end(), i, i + list->IdxBuffer.size_in_bytes());
        for (const ImDrawCmd& cmd : list->CmdBuffer)
        {
            if (cmd.UserCallback || cmd.ClipRect.z <= cmd.ClipRect.x || cmd.ClipRect.w <= cmd.ClipRect.y)
                continue;
            e.draws.push_back({static_cast<GLsizei>(cmd.ElemCount),
                               static_cast<std::uintptr_t>(idxBase + cmd.IdxOffset) * sizeof(ImDrawIdx),
                               static_cast<GLint>(vtxBase + cmd.VtxOffset)});
        }
        vtxBase += list->VtxBuffer.Size;
        idxBase += list->IdxBuffer.Size;
    }
    return e;
}

int countUploads(GLenum target)
{
    int n = 0;
    for (const Upload& u : g_gl.uploads)
        n += u.target == target ? 1 : 0;
    return n;
}

void runCase(const char* name, GLint major, GLint minor, void (*body)())
{
    ++g_totalCases;
    g_caseFailed = false;
    std::cout << "case: " << name << std::endl;
    g_gl = FakeGl{};
    g_gl.major = major;
    g_gl.minor = minor;
    installFakeGl();
    ImGui::CreateContext();
    check(ImGui_ImplOpenGL3_Init("#version 330"), "the renderer starts on the fake OpenGL");
    body();
    ImGui_ImplOpenGL3_Shutdown();
    ImGui::DestroyContext();
    if (g_caseFailed)
        ++g_failedCases;
    std::cout << (g_caseFailed ? "  failed" : "  passed") << std::endl;
}

void caseOneUploadPerFrame()
{
    for (int frame = 0; frame < 3; ++frame)
    {
        ImDrawData* data = buildFrame(frame);
        check(data->CmdListsCount >= 4, "the frame has a draw list for each window");
        const Expected expected = expectedShared(data);
        g_gl.uploads.clear();
        g_gl.draws.clear();
        ImGui_ImplOpenGL3_RenderDrawData(data);

        const int vertexUploads = countUploads(GL_ARRAY_BUFFER);
        const int indexUploads = countUploads(GL_ELEMENT_ARRAY_BUFFER);
        check(vertexUploads == 1,
              "frame " + std::to_string(frame) + ": one vertex upload for " +
                  std::to_string(data->CmdListsCount) + " draw lists (seen " + std::to_string(vertexUploads) + ")");
        check(indexUploads == 1,
              "frame " + std::to_string(frame) + ": one index upload (seen " + std::to_string(indexUploads) + ")");
        for (const Upload& u : g_gl.uploads)
        {
            if (u.target == GL_ARRAY_BUFFER && vertexUploads == 1)
                check(u.bytes == expected.vertices, "the vertex upload holds every draw list in order");
            if (u.target == GL_ELEMENT_ARRAY_BUFFER && indexUploads == 1)
                check(u.bytes == expected.indices, "the index upload holds every draw list in order");
        }

        check(g_gl.draws.size() == expected.draws.size(),
              "one draw call for each visible command (seen " + std::to_string(g_gl.draws.size()) + ", expected " +
                  std::to_string(expected.draws.size()) + ")");
        // Not std::min: on Windows the loader header includes windows.h, whose min macro breaks the call.
        const size_t n = g_gl.draws.size() < expected.draws.size() ? g_gl.draws.size() : expected.draws.size();
        int wrong = 0;
        for (size_t i = 0; i < n; ++i)
        {
            const Draw& seen = g_gl.draws[i];
            const Draw& want = expected.draws[i];
            if (seen.count != want.count || seen.indexByteOffset != want.indexByteOffset ||
                seen.baseVertex != want.baseVertex)
                ++wrong;
        }
        check(wrong == 0, "each draw reads its own draw list in the shared buffers (" + std::to_string(wrong) +
                              " draws read another place)");
    }
}

void caseOpenGl31KeepsOneUploadPerDrawList()
{
    ImDrawData* data = buildFrame(0);
    g_gl.uploads.clear();
    g_gl.draws.clear();
    ImGui_ImplOpenGL3_RenderDrawData(data);
    check(countUploads(GL_ARRAY_BUFFER) == data->CmdListsCount,
          "without glDrawElementsBaseVertex each draw list uploads its own vertices");
    check(countUploads(GL_ELEMENT_ARRAY_BUFFER) == data->CmdListsCount,
          "without glDrawElementsBaseVertex each draw list uploads its own indices");
    size_t d = 0;
    int wrong = 0;
    for (const ImDrawList* list : data->CmdLists)
    {
        for (const ImDrawCmd& cmd : list->CmdBuffer)
        {
            if (cmd.UserCallback || cmd.ClipRect.z <= cmd.ClipRect.x || cmd.ClipRect.w <= cmd.ClipRect.y)
                continue;
            if (d >= g_gl.draws.size() || g_gl.draws[d].count != static_cast<GLsizei>(cmd.ElemCount) ||
                g_gl.draws[d].indexByteOffset != cmd.IdxOffset * sizeof(ImDrawIdx))
                ++wrong;
            ++d;
        }
    }
    check(d == g_gl.draws.size() && wrong == 0, "each draw reads its draw list from the start of the buffers");
}

} // namespace

int main()
{
    runCase("OpenGL 3.3: one upload for each frame", 3, 3, caseOneUploadPerFrame);
    runCase("OpenGL 3.1: one upload for each draw list", 3, 1, caseOpenGl31KeepsOneUploadPerDrawList);
    std::cout << (g_totalCases - g_failedCases) << "/" << g_totalCases << " cases passed" << std::endl;
    return g_failedCases == 0 ? 0 : 1;
}
