/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

#pragma once

// The SVG reader and painter of the standalone backend, written for this
// project. parseSvgDocument() turns SVG text into a tree of shapes and groups;
// renderSvgDocument() paints that tree into an RGBA8 bitmap.
//
// What is drawn: <svg>, <g>, <a>, <switch>, <use>, <symbol>, <defs>, <path>,
// <rect>, <circle>, <ellipse>, <line>, <polyline>, <polygon>; fill and stroke
// with colors, linear and radial gradients; fill rules; stroke width, caps,
// joins, miter limit and dashes; transforms; opacity, fill-opacity and
// stroke-opacity (group opacity uses a separate layer); clip-path; presentation
// attributes, the style attribute and <style> sheets with type, class, id and
// descendant selectors.
//
// What is not drawn, and is reported in Document::skipped: <text>, <image>,
// <foreignObject>, <pattern> paint, masks, filters and markers (also on the
// root <svg>), and a transform attribute on an <svg> element.
//
// Limits: a small file must not take unbounded time or memory. The reader and
// the painter count their work before they do it, and refuse a file that
// needs more than these limits with a cause that names the limit: the text
// that entity references add (1 MiB), XML elements (1,000,000), groups and
// shapes after <use> references are followed (100,000), path points after
// <use> references are followed (4,000,000), <style> rules (100,000
// selector and declaration pairs; 10,000,000 selector tests and applied
// declarations), stops of one gradient (4,096), line pieces of curves and
// strokes (4,000,000), pixels visited while painting (64 times the bitmap,
// and at least 16,777,216) and group layers (256 MiB at a time). Parts nested
// deeper than 256 levels, counting <use> references, are not drawn and are
// reported.

#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace omni {
namespace ui {
namespace standalone {
namespace svg {

struct Point
{
    double x = 0.0;
    double y = 0.0;
};

/// A 2D affine transform: x' = a*x + c*y + e, y' = b*x + d*y + f.
struct Transform
{
    double a = 1.0, b = 0.0, c = 0.0, d = 1.0, e = 0.0, f = 0.0;

    static Transform translate(double x, double y);
    static Transform scale(double x, double y);
    static Transform rotate(double degrees);
    static Transform skewX(double degrees);
    static Transform skewY(double degrees);

    /// The transform that applies `inner` first and then this one.
    Transform operator*(const Transform& inner) const;
    Point apply(Point p) const { return { a * p.x + c * p.y + e, b * p.x + d * p.y + f }; }
    bool invert(Transform& out) const;
    /// The largest length that a unit vector can get from this transform.
    double maxScale() const;
};

struct Rect
{
    double x0 = 0.0, y0 = 0.0, x1 = 0.0, y1 = 0.0;
    bool empty() const { return !(x1 > x0) || !(y1 > y0); }
};

/// Lines and cubic curves in user space. Quadratic curves and arcs are stored
/// as cubic curves.
struct Path
{
    enum class Verb : uint8_t
    {
        eMove,
        eLine,
        eCubic,
        eClose
    };
    std::vector<Verb> verbs;
    std::vector<Point> points; // eMove and eLine: 1 point, eCubic: 3 points, eClose: none

    void moveTo(Point p);
    void lineTo(Point p);
    void cubicTo(Point c1, Point c2, Point p);
    void quadTo(Point c, Point p);
    /// An SVG elliptical arc from the current point to `p`.
    void arcTo(double rx, double ry, double xAxisRotationDegrees, bool largeArc, bool sweep, Point p);
    void close();
    bool empty() const { return verbs.empty(); }
    Point currentPoint() const;
    /// The exact bounds of the geometry (curve extremes, not control points).
    Rect bounds() const;
};

struct Color
{
    float r = 0.0f, g = 0.0f, b = 0.0f, a = 1.0f; // straight alpha, 0..1
};

struct GradientStop
{
    float offset = 0.0f;
    Color color;
};

struct Gradient
{
    enum class Spread : uint8_t
    {
        ePad,
        eReflect,
        eRepeat
    };
    bool radial = false;
    bool userSpaceUnits = false; ///< gradientUnits="userSpaceOnUse"
    Spread spread = Spread::ePad;
    Transform transform; ///< gradientTransform
    double x1 = 0.0, y1 = 0.0, x2 = 1.0, y2 = 0.0; ///< linear
    double cx = 0.5, cy = 0.5, r = 0.5, fx = 0.5, fy = 0.5, fr = 0.0; ///< radial
    std::vector<GradientStop> stops;
};

struct Paint
{
    enum class Kind : uint8_t
    {
        eNone,
        eColor,
        eGradient
    };
    Kind kind = Kind::eNone;
    Color color;
    std::shared_ptr<const Gradient> gradient;
};

enum class FillRule : uint8_t
{
    eNonZero,
    eEvenOdd
};

enum class LineCap : uint8_t
{
    eButt,
    eRound,
    eSquare
};

enum class LineJoin : uint8_t
{
    eMiter,
    eRound,
    eBevel
};

struct Stroke
{
    Paint paint;
    float opacity = 1.0f;
    double width = 1.0;
    LineCap cap = LineCap::eButt;
    LineJoin join = LineJoin::eMiter;
    double miterLimit = 4.0;
    std::vector<double> dashes; ///< empty: a solid line
    double dashOffset = 0.0;
};

/// One shape of a clip path, in the user space of the clipped node.
struct ClipShape
{
    Path path;
    Transform transform;
    FillRule rule = FillRule::eNonZero;
};

/// A node of the drawing: a shape, or a group of nodes.
struct Node
{
    bool isGroup = false;
    Transform transform; ///< from the node's user space to the parent's

    // Shape
    Path path;
    Paint fill;
    float fillOpacity = 1.0f;
    FillRule fillRule = FillRule::eNonZero;
    Stroke stroke;

    // Group. The children are painted into a layer when opacity < 1 or when
    // there is a clip; the layer is then put on the parent with the opacity,
    // inside the clip.
    float opacity = 1.0f;
    std::vector<ClipShape> clip; ///< union of shapes; empty: no clip
    bool clipToNothing = false; ///< a clip path with no shapes: nothing is drawn
    std::vector<Node> children;
};

struct Document
{
    double width = 0.0; ///< intrinsic size in pixels
    double height = 0.0;
    Node root; ///< a group; its transform maps the viewBox to width x height
    size_t shapeCount = 0;
    /// Parts of the file that are not drawn, for example "<text>" or "filter".
    std::vector<std::string> skipped;
    /// Parts of the file that are drawn differently from the file, each with
    /// its cause, for example a path that is drawn up to an error in its data.
    std::vector<std::string> changed;
};

/// Read SVG text. Returns false and sets `error` to the cause when the text is
/// not a usable SVG (not XML, no <svg> root, no size) or needs more than a
/// limit (see the top of this file). An SVG with no shape is returned as a
/// document with shapeCount 0.
bool parseSvgDocument(const std::string& text, Document& doc, std::string& error);

/// Paint the document into a straight-alpha RGBA8 bitmap of width x height
/// pixels, rows without padding. The document is stretched to the bitmap:
/// x by width / doc.width and y by height / doc.height. Returns false, with an
/// empty bitmap and the cause in `error`, when the painting needs more than a
/// limit. Parts that are painted differently from the file (for example a dash
/// pattern too fine to draw dash by dash) are added to `changed` with their
/// cause.
bool renderSvgDocument(const Document& doc,
                       uint32_t width,
                       uint32_t height,
                       std::vector<uint8_t>& rgba,
                       std::string& error,
                       std::vector<std::string>& changed);

} // namespace svg
} // namespace standalone
} // namespace ui
} // namespace omni
