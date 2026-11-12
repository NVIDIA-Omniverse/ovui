/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// Paints a svg::Document into a bitmap. See StandaloneSvgDocument.h.
//
// Curves are cut into short lines in user space. A stroke becomes outline
// polygons: the line moved half the stroke width to each side, with the joins
// on the outer side of each turn and the caps at the ends. The rasterizer
// adds, for every edge and every pixel that the edge crosses, the signed area
// that the edge leaves to its right in that pixel. A running sum along each
// row then gives the signed coverage of each pixel, and the fill rule turns it
// into a coverage from 0 to 1. Between the pixels that edges cross, the
// coverage does not change, so those runs are painted as one span. The cost
// grows with the length of the edges and the area of the shape, not with a
// number of samples per pixel. The bitmap holds premultiplied 8-bit colors
// while painting, as browsers do, and straight alpha at the end.

#include "StandaloneSvgDocument.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <string>

#if defined(_MSC_VER)
#    include <intrin.h>
#    define OVUI_SVG_ALWAYS_INLINE __forceinline
#else
#    define OVUI_SVG_ALWAYS_INLINE inline __attribute__((always_inline))
#endif

namespace omni {
namespace ui {
namespace standalone {
namespace svg {

namespace {

constexpr double kPi = 3.14159265358979323846;
/// Largest distance, in pixels, between a curve and the lines that replace it.
constexpr double kTolerance = 0.1;
/// Device coordinates are kept within this range, so that the arithmetic of
/// an absurd file stays finite. The bitmap is at most 2048 pixels wide.
constexpr double kCoordinateLimit = 1e9;
/// Entries of the color table of a gradient.
constexpr int kGradientTableSize = 1024;
/// A dash pattern that would cut a path into more dashes than this is drawn
/// as one line with the average cover of its dashes, and this is reported, so
/// that a tiny pattern cannot take unbounded time.
constexpr double kMaxDashes = 100000.0;

// Painting limits (see StandaloneSvgDocument.h). Each is checked before the
// work that it limits is done.
/// Line pieces made from curves, dashes, joins and caps, for the whole bitmap.
constexpr size_t kMaxLinePieces = 4000000;
/// Pixels that painting may visit (rows and columns of each shape, clip and
/// layer): this many times the pixels of the bitmap...
constexpr size_t kPaintPixelsPerBitmapPixel = 64;
/// ...and at least this many.
constexpr size_t kMinPaintPixels = 16 * 1024 * 1024;
/// Memory of the group layers that exist at the same time.
constexpr size_t kMaxLayerBytes = 256 * 1024 * 1024;

/// A drawing that needs more than a painting limit. renderSvgDocument()
/// returns its text as the error.
class PaintLimitError : public std::runtime_error
{
public:
    explicit PaintLimitError(const std::string& what)
        : std::runtime_error("the SVG is too complex to draw: painting it needs more than " + what)
    {
    }
};

/// The work of painting one bitmap, counted against the limits.
struct PaintBudget
{
    size_t pieces = 0;
    size_t pixels = 0;
    size_t maxPixels = kMinPaintPixels;
    size_t layerBytes = 0;

    void addPieces(size_t n)
    {
        pieces += n;
        if (pieces > kMaxLinePieces)
            tooManyPieces();
    }

    void addPixels(size_t n)
    {
        pixels += n;
        if (pixels > maxPixels)
            tooManyPixels();
    }

    /// The pixel visits that are left.
    size_t pixelsLeft() const { return maxPixels - std::min(pixels, maxPixels); }

    [[noreturn]] static void tooManyPieces()
    {
        throw PaintLimitError(std::to_string(kMaxLinePieces) + " line pieces for its curves and strokes");
    }

    [[noreturn]] void tooManyPixels() const
    {
        throw PaintLimitError(std::to_string(maxPixels) + " pixel visits (" +
                              std::to_string(kPaintPixelsPerBitmapPixel) + " times the bitmap)");
    }

    void addLayer(size_t bytes)
    {
        if (bytes > kMaxLayerBytes - layerBytes)
            throw PaintLimitError(std::to_string(kMaxLayerBytes / (1024 * 1024)) + " MiB for its group layers");
        layerBytes += bytes;
    }
};

/// Frees the memory of a vector that is larger than `keepBytes`.
template <class T>
void trimVector(std::vector<T>& v, size_t keepBytes)
{
    if (v.capacity() * sizeof(T) > keepBytes)
        std::vector<T>().swap(v);
}

double length(Point a, Point b)
{
    const double dx = b.x - a.x, dy = b.y - a.y;
    return std::sqrt(dx * dx + dy * dy);
}

// ---------------------------------------------------------------------------
// Flattening: curves to lines, in user space
// ---------------------------------------------------------------------------

struct Contour
{
    std::vector<Point> points;
    /// 1 where a point is inside a curve (between two lines of the same
    /// curve) or where two parts of the path meet without a corner; 0 where
    /// it is a corner of the path.
    std::vector<uint8_t> smooth;
    bool closed = false;
    bool hasSegments = false; ///< false for a lone "M x y"
};

/// A list of contours whose memory is kept from one use to the next.
struct ContourList
{
    std::vector<Contour> items;
    size_t count = 0;
    PaintBudget* budget = nullptr; ///< the work of the painter that owns the list

    void clear() { count = 0; }
    Contour& add()
    {
        if (count == items.size())
            items.emplace_back();
        Contour& c = items[count++];
        c.points.clear();
        c.smooth.clear();
        c.closed = false;
        c.hasSegments = false;
        return c;
    }
    const Contour* begin() const { return items.data(); }
    const Contour* end() const { return items.data() + count; }

    /// Frees all contours when they hold more than `keepBytes`.
    void trim(size_t keepBytes)
    {
        size_t bytes = items.capacity() * sizeof(Contour);
        for (const Contour& c : items)
            bytes += c.points.capacity() * sizeof(Point) + c.smooth.capacity();
        if (bytes > keepBytes)
        {
            std::vector<Contour>().swap(items);
            count = 0;
        }
    }
};

/// True when the directions a and b are the same (within about half a degree).
bool sameDirection(Point a, Point b)
{
    const double la = std::sqrt(a.x * a.x + a.y * a.y);
    const double lb = std::sqrt(b.x * b.x + b.y * b.y);
    if (!(la > 0.0) || !(lb > 0.0))
        return false;
    const double cross = (a.x * b.y - a.y * b.x) / (la * lb);
    const double dot = (a.x * b.x + a.y * b.y) / (la * lb);
    return dot > 0.0 && std::fabs(cross) < 0.01;
}

/// The direction at the start and at the end of a cubic curve.
void cubicTangents(Point p0, Point p1, Point p2, Point p3, Point& startDir, Point& endDir)
{
    auto diff = [](Point a, Point b) { return Point{ b.x - a.x, b.y - a.y }; };
    auto zero = [](Point d) { return d.x == 0.0 && d.y == 0.0; };
    startDir = diff(p0, p1);
    if (zero(startDir))
        startDir = diff(p0, p2);
    if (zero(startDir))
        startDir = diff(p0, p3);
    endDir = diff(p2, p3);
    if (zero(endDir))
        endDir = diff(p1, p3);
    if (zero(endDir))
        endDir = diff(p0, p3);
}

/// Cuts a path into contours of lines. A point between two parts of the path
/// that meet without a corner (the direction does not change) is marked
/// smooth, like the points inside a curve.
void flatten(const Path& path, double tolerance, ContourList& out)
{
    out.clear();
    PaintBudget& budget = *out.budget;
    // Only the curves are counted here: each adds up to 4096 pieces, so a path
    // of curves can grow far past its point count. A straight line adds one
    // piece for one path point, which the reader already counted against the
    // point budget, so it needs no count in this hot loop.
    size_t curvePieces = 0;
    const size_t piecesLeft = kMaxLinePieces - std::min(budget.pieces, kMaxLinePieces);
    size_t pi = 0;
    Point start;
    Point current;
    Point firstDir; // direction at the start of the contour
    Point lastDir; // direction at the end of the last part
    bool hasDir = false;
    Contour* contour = nullptr;
    auto begin = [&](Point p) {
        contour = &out.add();
        contour->points.push_back(p);
        contour->smooth.push_back(0);
        start = p;
        hasDir = false;
    };
    // Called with the direction at the start of each new part.
    auto meet = [&](Point dir) {
        if (!hasDir)
            firstDir = dir;
        else if (sameDirection(lastDir, dir))
            contour->smooth.back() = 1;
    };
    for (Path::Verb verb : path.verbs)
    {
        switch (verb)
        {
        case Path::Verb::eMove:
            current = path.points[pi++];
            begin(current);
            break;
        case Path::Verb::eLine:
        {
            if (!contour || contour->closed)
                begin(current);
            const Point p = path.points[pi++];
            const Point dir{ p.x - current.x, p.y - current.y };
            if (dir.x != 0.0 || dir.y != 0.0)
            {
                meet(dir);
                lastDir = dir;
                hasDir = true;
            }
            current = p;
            contour->points.push_back(current);
            contour->smooth.push_back(0);
            contour->hasSegments = true;
            break;
        }
        case Path::Verb::eCubic:
        {
            if (!contour || contour->closed)
                begin(current);
            const Point p0 = current, p1 = path.points[pi], p2 = path.points[pi + 1], p3 = path.points[pi + 2];
            pi += 3;
            Point startDir, endDir;
            cubicTangents(p0, p1, p2, p3, startDir, endDir);
            if (startDir.x != 0.0 || startDir.y != 0.0)
            {
                meet(startDir);
                lastDir = endDir;
                hasDir = true;
            }
            const double ddx = std::max(std::fabs(p0.x - 2.0 * p1.x + p2.x), std::fabs(p1.x - 2.0 * p2.x + p3.x));
            const double ddy = std::max(std::fabs(p0.y - 2.0 * p1.y + p2.y), std::fabs(p1.y - 2.0 * p2.y + p3.y));
            const double dd = std::sqrt(ddx * ddx + ddy * ddy);
            // The distance of a cubic from its chord is at most 3/4 * dd / n^2
            // for n equal pieces.
            int n = 1;
            if (dd > 0.0 && std::isfinite(dd))
                n = static_cast<int>(std::min(4096.0, std::ceil(std::sqrt(0.75 * dd / tolerance))));
            n = std::max(n, 1);
            curvePieces += static_cast<size_t>(n);
            if (curvePieces > piecesLeft)
                PaintBudget::tooManyPieces();
            for (int i = 1; i <= n; ++i)
            {
                const double t = static_cast<double>(i) / n;
                const double u = 1.0 - t;
                const double w0 = u * u * u, w1 = 3.0 * u * u * t, w2 = 3.0 * u * t * t, w3 = t * t * t;
                const Point p = (i == n) ? p3 :
                                           Point{ w0 * p0.x + w1 * p1.x + w2 * p2.x + w3 * p3.x,
                                                  w0 * p0.y + w1 * p1.y + w2 * p2.y + w3 * p3.y };
                contour->points.push_back(p);
                contour->smooth.push_back(i < n ? 1 : 0);
            }
            contour->hasSegments = true;
            current = p3;
            break;
        }
        case Path::Verb::eClose:
            if (contour && !contour->closed)
            {
                contour->closed = true;
                contour->hasSegments = true;
                if (hasDir)
                {
                    // The closing line, if it has a length, and the first part.
                    const Point closing{ start.x - current.x, start.y - current.y };
                    if (closing.x != 0.0 || closing.y != 0.0)
                    {
                        if (sameDirection(lastDir, closing))
                            contour->smooth.back() = 1;
                        lastDir = closing;
                    }
                    if (sameDirection(lastDir, firstDir))
                        contour->smooth.front() = 1;
                }
            }
            current = start;
            break;
        }
    }
    budget.addPieces(curvePieces);
}

// ---------------------------------------------------------------------------
// Edges and the rasterizer
// ---------------------------------------------------------------------------

struct Edge
{
    double x0, y0, x1, y1; ///< y0 < y1
    double slope; ///< dx / dy
    int dir; ///< +1 for an edge that goes down in the original path, -1 up

    double xAt(double y) const { return x0 + (y - y0) * slope; }
};

class EdgeList
{
public:
    /// A closed polygon of user-space points, in device space.
    void addPolygon(const std::vector<Point>& points, const Transform& toDevice)
    {
        const size_t n = points.size();
        if (n < 2)
            return;
        // The device points and their bounds. A point that is not finite or
        // is beyond kCoordinateLimit fails the range test (NaN fails every
        // comparison).
        m_device.resize(n);
        double minX = std::numeric_limits<double>::infinity(), maxX = -minX, minY = minX, maxY = -minX;
        bool inRange = true;
        for (size_t i = 0; i < n; ++i)
        {
            const Point q = toDevice.apply(points[i]);
            inRange = inRange & (q.x >= -kCoordinateLimit) & (q.x <= kCoordinateLimit) & (q.y >= -kCoordinateLimit) &
                      (q.y <= kCoordinateLimit);
            minX = std::min(minX, q.x);
            maxX = std::max(maxX, q.x);
            minY = std::min(minY, q.y);
            maxY = std::max(maxY, q.y);
            m_device[i] = q;
        }
        if (!inRange)
        {
            addPolygonSlow(points, toDevice);
            return;
        }
        m_minX = std::min(m_minX, minX);
        m_maxX = std::max(m_maxX, maxX);
        m_minY = std::min(m_minY, minY);
        m_maxY = std::max(m_maxY, maxY);
        for (size_t i = 0; i + 1 < n; ++i)
            add(m_device[i], m_device[i + 1]);
        add(m_device[n - 1], m_device[0]);
    }

    const std::vector<Edge>& edges() const { return m_edges; }
    /// The bounds of the edges; only valid when there are edges.
    double minX() const { return m_minX; }
    double maxX() const { return m_maxX; }
    double minY() const { return m_minY; }
    double maxY() const { return m_maxY; }

    void clear()
    {
        m_edges.clear();
        m_minX = m_minY = std::numeric_limits<double>::infinity();
        m_maxX = m_maxY = -std::numeric_limits<double>::infinity();
    }

    void trim(size_t keepBytes)
    {
        trimVector(m_edges, keepBytes);
        trimVector(m_device, keepBytes);
    }

private:
    /// addPolygon() for points of which some are not finite or are far out:
    /// those are kept within kCoordinateLimit, and an edge with a point that
    /// is not finite is left out.
    void addPolygonSlow(const std::vector<Point>& points, const Transform& toDevice)
    {
        const size_t n = points.size();
        auto finite = [&](size_t i) {
            const Point q = toDevice.apply(points[i]);
            return std::isfinite(q.x) && std::isfinite(q.y);
        };
        auto limit = [](double v) { return std::min(kCoordinateLimit, std::max(-kCoordinateLimit, v)); };
        for (size_t i = 0; i < n; ++i)
        {
            const size_t j = (i + 1) % n;
            if (!finite(i) || !finite(j))
                continue;
            const Point a{ limit(m_device[i].x), limit(m_device[i].y) };
            const Point b{ limit(m_device[j].x), limit(m_device[j].y) };
            if (a.y == b.y)
                continue;
            m_minX = std::min(m_minX, std::min(a.x, b.x));
            m_maxX = std::max(m_maxX, std::max(a.x, b.x));
            m_minY = std::min(m_minY, std::min(a.y, b.y));
            m_maxY = std::max(m_maxY, std::max(a.y, b.y));
            add(a, b);
        }
    }

    /// An edge between two finite device points; the caller updates the bounds.
    void add(Point a, Point b)
    {
        if (a.y == b.y)
            return; // a horizontal edge does not change the coverage
        Edge e;
        if (a.y < b.y)
            e = { a.x, a.y, b.x, b.y, 0.0, 1 };
        else
            e = { b.x, b.y, a.x, a.y, 0.0, -1 };
        e.slope = (e.x1 - e.x0) / (e.y1 - e.y0);
        // An edge of a height below about 1e-299 has a slope that overflows;
        // x at its start would be 0 * infinity. Its coverage is that height,
        // so any x is as good: take the start.
        if (!std::isfinite(e.slope))
            e.slope = 0.0;
        m_edges.push_back(e);
    }

    std::vector<Edge> m_edges;
    std::vector<Point> m_device;
    double m_minX = std::numeric_limits<double>::infinity();
    double m_maxX = -std::numeric_limits<double>::infinity();
    double m_minY = std::numeric_limits<double>::infinity();
    double m_maxY = -std::numeric_limits<double>::infinity();
};

/// The coverage of a set of edges inside a clip rectangle. Each edge is walked
/// once through the pixel rows it crosses and adds, to each pixel cell it
/// passes, the signed area it leaves to its right; a running sum along each
/// row then gives the coverage of each pixel. The coverage changes only at the
/// cells that an edge changed (a bit for each cell records that), so each run
/// of pixels with the same coverage is given as one call to
/// `sink.span(x, n, coverage)` after `sink.row(y)`. Runs with no coverage are
/// skipped.
class Rasterizer
{
public:
    explicit Rasterizer(PaintBudget& budget) : m_budget(budget) {}

    /// The budget counts the pixels that the run visits: the rows and columns
    /// of its region before the sweep, and the rows of each edge before the
    /// edge is walked.
    template <class Sink>
    void run(const EdgeList& list, FillRule rule, int clipX0, int clipY0, int clipX1, int clipY1, Sink& sink)
    {
        PaintBudget& budget = m_budget;
        const std::vector<Edge>& edges = list.edges();
        if (edges.empty() || clipX1 <= clipX0 || clipY1 <= clipY0)
            return;
        // Edge coordinates are within kCoordinateLimit, so these fit an int.
        const int rowStart = std::max(clipY0, static_cast<int>(std::floor(list.minY())));
        const int rowEnd = std::min(clipY1, static_cast<int>(std::ceil(list.maxY())));
        // A shape left of the clip covers its first column; edges right of
        // the clip do not change any visible pixel.
        const int colStart = std::max(clipX0, static_cast<int>(std::floor(list.minX())));
        const int colEnd = std::min(clipX1, static_cast<int>(std::ceil(list.maxX())) + 1);
        if (rowStart >= rowEnd || colStart >= colEnd)
            return;
        budget.addPixels(static_cast<size_t>(rowEnd - rowStart) * static_cast<size_t>(colEnd - colStart));
        // The rows of the edges, counted in a local while they are walked.
        const size_t edgeRowsLeft = budget.pixelsLeft();
        size_t edgeRows = 0;
        sink.region(colStart, rowStart, colEnd, rowEnd);
        const size_t rows = static_cast<size_t>(rowEnd - rowStart);
        m_width = colEnd - colStart;
        m_stride = static_cast<size_t>(m_width) + 2;
        m_words = (m_stride + 63) / 64;
        // The cells and the bits are all zero between uses: the sweep clears
        // what it reads.
        if (m_cells.size() < m_stride * rows)
            m_cells.resize(m_stride * rows, 0.0f);
        if (m_bits.size() < m_words * rows)
            m_bits.resize(m_words * rows, 0);

        for (const Edge& e : edges)
        {
            const double ya = std::max(e.y0, static_cast<double>(rowStart));
            const double yb = std::min(e.y1, static_cast<double>(rowEnd));
            if (!(yb > ya))
                continue;
            const float sign = static_cast<float>(e.dir);
            int row = static_cast<int>(ya); // ya >= rowStart, so this is the floor
            const int firstRow = row;
            float* cells = m_cells.data() + static_cast<size_t>(row - rowStart) * m_stride;
            uint64_t* bits = m_bits.data() + static_cast<size_t>(row - rowStart) * m_words;
            double yTop = ya;
            double xTop = e.xAt(ya) - colStart;
            while (yTop < yb)
            {
                const double yBottom = std::min(yb, row + 1.0);
                const double xBottom = e.xAt(yBottom) - colStart;
                accumulate(cells, bits, xTop, xBottom, static_cast<float>(yBottom - yTop) * sign);
                yTop = yBottom;
                xTop = xBottom;
                ++row;
                cells += m_stride;
                bits += m_words;
            }
            // At most one edge (at most the rows of the region) is walked
            // past the limit before it is found.
            edgeRows += static_cast<unsigned>(row - firstRow);
            if (edgeRows > edgeRowsLeft)
                budget.tooManyPixels();
        }

        budget.pixels += edgeRows;

        float* cells = m_cells.data();
        uint64_t* bits = m_bits.data();
        for (int y = rowStart; y < rowEnd; ++y, cells += m_stride, bits += m_words)
        {
            // Visit the changed cells in order; between two of them the
            // coverage is the same for every pixel.
            float sum = 0.0f;
            int previous = -1;
            for (size_t w = 0; w < m_words; ++w)
            {
                uint64_t word = bits[w];
                if (word == 0)
                    continue;
                bits[w] = 0;
                if (previous < 0)
                    sink.row(y);
                do
                {
                    const int c = static_cast<int>(w * 64) + lowestBit(word);
                    word &= word - 1;
                    if (previous >= 0 && previous < m_width)
                    {
                        const float k = coverage(sum, rule);
                        if (k > kMinCoverage)
                            sink.span(colStart + previous, std::min(c, m_width) - previous, k);
                    }
                    sum += cells[c];
                    cells[c] = 0.0f;
                    previous = c;
                } while (word);
            }
            if (previous >= 0 && previous < m_width)
            {
                // To the end of the row; nothing when the shape ended here.
                const float k = coverage(sum, rule);
                if (k > kMinCoverage)
                    sink.span(colStart + previous, m_width - previous, k);
            }
        }
    }

    /// Frees the cell grid when it is larger than `keepBytes`, after a big shape.
    void trim(size_t keepBytes)
    {
        if (m_cells.capacity() * sizeof(float) > keepBytes)
        {
            std::vector<float>().swap(m_cells);
            std::vector<uint64_t>().swap(m_bits);
        }
    }

private:
    PaintBudget& m_budget;

    /// Coverage below this is not painted: it is less than half a step of an
    /// 8-bit channel.
    static constexpr float kMinCoverage = 1e-4f;

    static float coverage(float sum, FillRule rule)
    {
        float c = std::fabs(sum);
        if (rule == FillRule::eEvenOdd)
        {
            c = std::fmod(c, 2.0f);
            if (c > 1.0f)
                c = 2.0f - c;
        }
        return std::min(1.0f, c);
    }

    /// The index of the lowest set bit of a nonzero word (one processor
    /// instruction on x86-64 and ARM64). Inlined into the sweep, which calls
    /// it once for each span boundary.
    static OVUI_SVG_ALWAYS_INLINE int lowestBit(uint64_t word)
    {
#if defined(_MSC_VER)
        unsigned long index = 0;
        _BitScanForward64(&index, word);
        return static_cast<int>(index);
#else
        return __builtin_ctzll(word);
#endif
    }

    /// Records that the cells first .. last of a row may have changed.
    static void touch(uint64_t* bits, int first, int last)
    {
        const int w0 = first >> 6, w1 = last >> 6;
        const uint64_t from = ~uint64_t(0) << (first & 63);
        const uint64_t to = ~uint64_t(0) >> (63 - (last & 63));
        if (w0 == w1)
        {
            bits[w0] |= from & to;
            return;
        }
        bits[w0] |= from;
        for (int w = w0 + 1; w < w1; ++w)
            bits[w] = ~uint64_t(0);
        bits[w1] |= to;
    }

    /// Adds the area to the right of a straight edge piece that goes from
    /// x = xa to x = xb (in either direction) inside one pixel row, whose
    /// cells and bits are given. `h` is its height with the sign of its
    /// direction.
    void accumulate(float* cells, uint64_t* bits, double x0, double x1, float h) const
    {
        const double w = static_cast<double>(m_width);
        double xa = std::min(x0, x1);
        double xb = std::max(x0, x1);
        if (xb <= 0.0)
        {
            cells[0] += h;
            bits[0] |= 1;
            return;
        }
        if (xa >= w)
            return;
        if (xa >= 0.0 && xb < w)
        {
            const int c0 = static_cast<int>(xa);
            if (static_cast<int>(xb) == c0)
            {
                // The whole piece is inside one pixel column.
                const float fx = static_cast<float>(0.5 * (xa + xb) - c0);
                cells[c0] += h * (1.0f - fx);
                cells[c0 + 1] += h * fx;
                touch(bits, c0, c0 + 1);
                return;
            }
        }
        const double k = h / (xb - xa); // height per unit of x
        int first = std::numeric_limits<int>::max();
        if (xa < 0.0)
        {
            cells[0] += static_cast<float>(-xa * k);
            first = 0;
            xa = 0.0;
        }
        if (xb > w)
            xb = w;
        const int c0 = static_cast<int>(xa);
        const int c1 = std::min(m_width - 1, static_cast<int>(xb));
        for (int c = c0; c <= c1; ++c)
        {
            const double left = std::max(xa, static_cast<double>(c));
            const double right = std::min(xb, c + 1.0);
            if (right <= left)
                continue;
            const float part = static_cast<float>((right - left) * k);
            const float fx = static_cast<float>(0.5 * (left + right) - c);
            cells[c] += part * (1.0f - fx);
            cells[c + 1] += part * fx;
        }
        touch(bits, std::min(first, c0), c1 + 1);
    }

    int m_width = 0;
    size_t m_stride = 0;
    size_t m_words = 0;
    std::vector<float> m_cells;
    std::vector<uint64_t> m_bits;
};

// ---------------------------------------------------------------------------
// Strokes: outline polygons in user space
// ---------------------------------------------------------------------------

class Stroker
{
public:
    Stroker(EdgeList& edges, PaintBudget& budget) : m_edges(edges), m_budget(budget) {}

    void reset(const Stroke& stroke, const Transform& toDevice)
    {
        m_stroke = &stroke;
        m_toDevice = toDevice;
        const double scale = std::max(toDevice.maxScale(), 1e-12);
        const double halfWidth = stroke.width * 0.5;
        if (halfWidth == m_halfWidth && scale == m_scale)
            return; // the same steps as the last stroke
        m_halfWidth = halfWidth;
        m_scale = scale;
        m_tolerance = kTolerance / scale;
        // The angle of one step of a round join or cap: the arc stays within
        // the tolerance of the circle.
        const double radius = m_halfWidth * scale;
        m_arcStep = radius > kTolerance ? 2.0 * std::acos(1.0 - kTolerance / radius) : kPi / 4.0;
        m_arcStep = std::min(kPi / 4.0, std::max(m_arcStep, 2.0 * kPi / 1024.0));
        m_capTurns.clear();
    }

    double tolerance() const { return m_tolerance; }

    void stroke(const Contour& input)
    {
        // Remove repeated points. A contour of one point is a dot.
        m_points.clear();
        m_smooth.clear();
        const double eps = m_tolerance * 1e-3;
        const double eps2 = eps * eps;
        auto near = [eps2](Point a, Point b) {
            const double dx = b.x - a.x, dy = b.y - a.y;
            return dx * dx + dy * dy <= eps2;
        };
        for (size_t i = 0; i < input.points.size(); ++i)
        {
            if (!m_points.empty() && near(m_points.back(), input.points[i]))
            {
                m_smooth.back() = m_smooth.back() && input.smooth[i];
                continue;
            }
            m_points.push_back(input.points[i]);
            m_smooth.push_back(input.smooth[i]);
        }
        const bool closed = input.closed;
        if (closed && m_points.size() > 1 && near(m_points.back(), m_points.front()))
        {
            m_points.pop_back();
            m_smooth.pop_back();
        }
        if (m_points.empty())
            return;
        if (m_points.size() == 1)
        {
            if (input.hasSegments)
                dot(m_points[0]);
            return;
        }
        // Each point gets at most 3 outline points without a round join or
        // cap; arc() and cap() count their own.
        m_budget.addPieces(3 * m_points.size());

        const size_t n = m_points.size();
        const size_t segments = closed ? n : n - 1;
        m_dirs.resize(segments);
        m_lengths.resize(segments);
        for (size_t i = 0; i < segments; ++i)
        {
            const Point& a = m_points[i];
            const Point& b = m_points[i + 1 < n ? i + 1 : 0];
            const double len = length(a, b);
            const double inv = 1.0 / len;
            m_dirs[i] = { (b.x - a.x) * inv, (b.y - a.y) * inv };
            m_lengths[i] = len;
        }

        // Side A is the left normal (-dy, dx) of each line, side B the other.
        m_sideA.clear();
        m_sideB.clear();
        if (closed)
        {
            for (size_t i = 0; i < n; ++i)
                join(i, i > 0 ? i - 1 : segments - 1, i);
            polygon(m_sideA);
            m_outline.assign(m_sideB.rbegin(), m_sideB.rend());
            polygon(m_outline);
            return;
        }
        const Point d0 = m_dirs.front();
        const Point d1 = m_dirs.back();
        m_sideA.push_back(offset(m_points.front(), d0, 1.0));
        m_sideB.push_back(offset(m_points.front(), d0, -1.0));
        for (size_t i = 1; i + 1 < n; ++i)
            join(i, i - 1, i);
        m_sideA.push_back(offset(m_points.back(), d1, 1.0));
        m_sideB.push_back(offset(m_points.back(), d1, -1.0));

        // A forward, the end cap, B backward, the start cap.
        m_outline = m_sideA;
        cap(m_outline, m_points.back(), d1, m_sideB.back());
        m_outline.insert(m_outline.end(), m_sideB.rbegin() + 1, m_sideB.rend());
        cap(m_outline, m_points.front(), { -d0.x, -d0.y }, m_sideA.front());
        m_outline.pop_back(); // the cap ended on the first point again
        polygon(m_outline);
    }

private:
    Point offset(Point p, Point d, double side) const
    {
        return { p.x - d.y * m_halfWidth * side, p.y + d.x * m_halfWidth * side };
    }

    void polygon(const std::vector<Point>& points)
    {
        if (points.size() < 3)
            return;
        m_edges.addPolygon(points, m_toDevice);
    }

    /// Adds points of the arc around `center` from `from` to `to`, through the
    /// side that `through` points to; `from` and `to` themselves are not added.
    void arc(std::vector<Point>& out, Point center, Point from, Point to, Point through)
    {
        const double ux = from.x - center.x, uy = from.y - center.y;
        const double vx = to.x - center.x, vy = to.y - center.y;
        const double cross = ux * vy - uy * vx, dot = ux * vx + uy * vy;
        double delta = std::atan2(cross, dot);
        if (!std::isfinite(delta))
            return;
        // The short arc passes the middle direction m, u turned by delta / 2
        // (half-angle formulas); else take the long way.
        const double cosDelta =
            std::max(-1.0, std::min(1.0, dot / std::sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))));
        const double mc = std::sqrt((1.0 + cosDelta) / 2.0);
        const double ms = std::copysign(std::sqrt((1.0 - cosDelta) / 2.0), delta);
        const double mx = ux * mc - uy * ms, my = ux * ms + uy * mc;
        if (mx * through.x + my * through.y < 0.0)
            delta = delta > 0.0 ? delta - 2.0 * kPi : delta + 2.0 * kPi;
        const int steps = static_cast<int>(std::ceil(std::fabs(delta) / m_arcStep));
        m_budget.addPieces(static_cast<size_t>(std::max(steps, 0)));
        const double c = std::cos(delta / steps), s = std::sin(delta / steps);
        double x = ux, y = uy;
        for (int i = 1; i < steps; ++i)
        {
            const double nx = x * c - y * s;
            y = x * s + y * c;
            x = nx;
            out.push_back({ center.x + x, center.y + y });
        }
    }

    void dot(Point p)
    {
        m_outline.clear();
        if (m_stroke->cap == LineCap::eRound)
        {
            const int steps = std::max(8, static_cast<int>(std::ceil(2.0 * kPi / m_arcStep)));
            m_budget.addPieces(static_cast<size_t>(steps));
            for (int i = 0; i < steps; ++i)
            {
                const double a = 2.0 * kPi * i / steps;
                m_outline.push_back({ p.x + m_halfWidth * std::cos(a), p.y + m_halfWidth * std::sin(a) });
            }
        }
        else if (m_stroke->cap == LineCap::eSquare)
        {
            const double h = m_halfWidth;
            m_outline = { { p.x - h, p.y - h }, { p.x + h, p.y - h }, { p.x + h, p.y + h }, { p.x - h, p.y + h } };
        }
        polygon(m_outline);
    }

    /// The cap at `end` of a line going in direction `d`. `out` ends with the
    /// offset point on one side; the cap goes around to `other`, which it adds.
    void cap(std::vector<Point>& out, Point end, Point d, Point other)
    {
        const Point from = out.back();
        if (m_stroke->cap == LineCap::eSquare)
        {
            out.push_back({ from.x + d.x * m_halfWidth, from.y + d.y * m_halfWidth });
            out.push_back({ other.x + d.x * m_halfWidth, other.y + d.y * m_halfWidth });
        }
        else if (m_stroke->cap == LineCap::eRound)
        {
            // Half a turn around `end`, through the direction d. Every round
            // cap of the stroke has the same steps, so their cosines and sines
            // are made once.
            if (m_capTurns.empty())
            {
                const int steps = static_cast<int>(std::ceil(kPi / m_arcStep));
                for (int i = 1; i < steps; ++i)
                    m_capTurns.push_back({ std::cos(kPi * i / steps), std::sin(kPi * i / steps) });
            }
            const double ux = from.x - end.x, uy = from.y - end.y;
            const double wx = d.x * m_halfWidth, wy = d.y * m_halfWidth;
            m_budget.addPieces(m_capTurns.size());
            for (const Point& turn : m_capTurns)
                out.push_back({ end.x + ux * turn.x + wx * turn.y, end.y + uy * turn.x + wy * turn.y });
        }
        out.push_back(other);
    }

    /// The join at point `i` between line `in` and line `out`.
    void join(size_t i, size_t in, size_t out)
    {
        const Point p = m_points[i];
        const Point d0 = m_dirs[in];
        const Point d1 = m_dirs[out];
        const double cross = d0.x * d1.y - d0.y * d1.x;
        const double dot = d0.x * d1.x + d0.y * d1.y;
        if (std::fabs(cross) < 1e-12 && dot > 0.0)
        {
            m_sideA.push_back(offset(p, d1, 1.0));
            m_sideB.push_back(offset(p, d1, -1.0));
            return;
        }
        if (m_smooth[i] && dot > 0.9)
        {
            // A small turn inside a curve. The outer side gets the miter tip,
            // p + w/2 (n0 + n1) / (1 + dot) for the normals n0 and n1, and the
            // inner side the point where its offset lines meet: the mirror
            // image of the tip. That point is w/2 |cross| / (1 + dot) from
            // the inner offset points along each line, and it must be on both.
            const double k = m_halfWidth / (1.0 + dot);
            const double tx = -(d0.y + d1.y) * k, ty = (d0.x + d1.x) * k;
            const double reach = std::fabs(cross) * k;
            if (reach <= m_lengths[in] && reach <= m_lengths[out])
            {
                m_sideA.push_back({ p.x + tx, p.y + ty });
                m_sideB.push_back({ p.x - tx, p.y - ty });
                return;
            }
        }
        // The line turns toward the left normal when cross > 0: side A is then
        // the inner side of the turn and side B the outer side.
        const bool outerIsA = cross < 0.0;
        joinOuter(outerIsA ? m_sideA : m_sideB, p, d0, d1, outerIsA ? 1.0 : -1.0, dot, m_smooth[i] != 0);
        joinInner(outerIsA ? m_sideB : m_sideA, p, d0, d1, outerIsA ? -1.0 : 1.0, in, out);
    }

    void joinOuter(std::vector<Point>& side, Point p, Point d0, Point d1, double s, double dot, bool smooth)
    {
        const Point o0 = offset(p, d0, s);
        const Point o1 = offset(p, d1, s);
        LineJoin type = m_stroke->join;
        if (smooth)
        {
            // Inside a curve the true outline is round. A miter of a small
            // angle is the same within the tolerance; a larger angle (a cusp,
            // or a tight curve) gets a round join.
            if (dot > 0.9)
            {
                // The tip of the miter: the offset normals n0 and n1 have the
                // dot product `dot`, and the tip is p + w/2 (n0 + n1) / (1 + dot).
                const double k = 1.0 / (1.0 + dot);
                side.push_back({ p.x + (o0.x + o1.x - 2.0 * p.x) * k, p.y + (o0.y + o1.y - 2.0 * p.y) * k });
                return;
            }
            type = LineJoin::eRound;
        }
        if (type == LineJoin::eMiter)
        {
            // Miter length / stroke width = 1 / sin(theta / 2), theta the angle between the lines.
            const double cosTheta = std::max(-1.0, std::min(1.0, -dot));
            const double sinHalf = std::sqrt(std::max(0.0, (1.0 - cosTheta) / 2.0));
            const double bx = o0.x + o1.x - 2.0 * p.x;
            const double by = o0.y + o1.y - 2.0 * p.y;
            const double bl = std::sqrt(bx * bx + by * by);
            if (sinHalf > 1e-12 && bl > 0.0 && (smooth || 1.0 / sinHalf <= m_stroke->miterLimit))
            {
                // The tip is on both offset lines, so o0 and o1 are not needed.
                const double tip = m_halfWidth / sinHalf;
                side.push_back({ p.x + bx / bl * tip, p.y + by / bl * tip });
                return;
            }
        }
        side.push_back(o0);
        if (type == LineJoin::eRound)
            arc(side, p, o0, o1, { o0.x + o1.x - 2.0 * p.x, o0.y + o1.y - 2.0 * p.y });
        side.push_back(o1);
    }

    void joinInner(std::vector<Point>& side, Point p, Point d0, Point d1, double s, size_t in, size_t out)
    {
        const Point i0 = offset(p, d0, s);
        const Point i1 = offset(p, d1, s);
        // Where the two inner offset lines meet, when that point is on both
        // lines; else go through the corner point, which leaves a small loop
        // inside the stroke that the nonzero rule fills.
        const double det = d0.x * d1.y - d0.y * d1.x;
        if (std::fabs(det) > 1e-12)
        {
            const double wx = i1.x - i0.x, wy = i1.y - i0.y;
            const double inv = 1.0 / det;
            const double t = (wx * d1.y - wy * d1.x) * inv; // along d0 from i0
            const double u = (wx * d0.y - wy * d0.x) * inv; // along d1 from i1
            // On both lines: back from the end i0 of the first offset line,
            // and forward from the start i1 of the second.
            if (t <= 0.0 && -t <= m_lengths[in] && u >= 0.0 && u <= m_lengths[out])
            {
                side.push_back({ i0.x + d0.x * t, i0.y + d0.y * t });
                return;
            }
        }
        side.push_back(i0);
        side.push_back(p);
        side.push_back(i1);
    }

public:
    void trim(size_t keepBytes)
    {
        trimVector(m_points, keepBytes);
        trimVector(m_smooth, keepBytes);
        trimVector(m_dirs, keepBytes);
        trimVector(m_lengths, keepBytes);
        trimVector(m_sideA, keepBytes);
        trimVector(m_sideB, keepBytes);
        trimVector(m_outline, keepBytes);
    }

private:
    const Stroke* m_stroke = nullptr;
    Transform m_toDevice;
    EdgeList& m_edges;
    PaintBudget& m_budget;
    double m_halfWidth = -1.0; ///< no stroke yet
    double m_scale = 0.0;
    double m_tolerance = kTolerance;
    double m_arcStep = kPi / 4.0;
    std::vector<Point> m_points;
    std::vector<uint8_t> m_smooth;
    std::vector<Point> m_dirs;
    std::vector<double> m_lengths;
    std::vector<Point> m_sideA;
    std::vector<Point> m_sideB;
    std::vector<Point> m_outline;
    /// (cos, sin) of the steps of a round cap of this stroke; empty until used.
    std::vector<Point> m_capTurns;
};

enum class Dashing
{
    eNone, ///< no dash pattern: the stroke is one line
    eDashed, ///< the dashes are in `out`
    eTooFine ///< more than kMaxDashes dashes: drawn as one line with their average cover
};

/// The share of a line that a dash pattern covers, with its caps (a cap adds
/// half the width at each end of a dash, a round one a little less), at most 1.
double dashCover(const Stroke& stroke)
{
    double on = 0.0, total = 0.0;
    size_t dashes = 0;
    for (size_t i = 0; i < stroke.dashes.size(); ++i)
    {
        total += stroke.dashes[i];
        if (i % 2 == 0)
        {
            on += stroke.dashes[i];
            ++dashes;
        }
    }
    double capLength = 0.0;
    if (stroke.cap == LineCap::eSquare)
        capLength = stroke.width;
    else if (stroke.cap == LineCap::eRound)
        capLength = stroke.width * kPi / 4.0; // a circle of the stroke width, as a length of the line
    if (!(total > 0.0))
        return 1.0;
    return std::min(1.0, (on + capLength * static_cast<double>(dashes)) / total);
}

/// Cuts contours into dashes.
Dashing dash(const ContourList& contours, const Stroke& stroke, ContourList& out)
{
    out.clear();
    PaintBudget& budget = *out.budget;
    const std::vector<double>& pattern = stroke.dashes;
    if (pattern.empty())
        return Dashing::eNone;
    double total = 0.0;
    for (double d : pattern)
        total += d;
    if (!(total > 0.0) || !std::isfinite(total))
        return Dashing::eNone;
    double pathLength = 0.0;
    for (const Contour& c : contours)
    {
        for (size_t i = 0; i + 1 < c.points.size(); ++i)
            pathLength += length(c.points[i], c.points[i + 1]);
        if (c.closed && c.points.size() > 1)
            pathLength += length(c.points.back(), c.points.front());
    }
    if (!std::isfinite(pathLength) || pathLength / total * static_cast<double>(pattern.size()) > kMaxDashes)
        return Dashing::eTooFine;

    for (const Contour& c : contours)
    {
        if (!c.hasSegments)
            continue;
        // Each contour starts the pattern again, at the offset.
        double phase = std::fmod(stroke.dashOffset, total);
        if (phase < 0.0)
            phase += total;
        size_t index = 0;
        while (phase >= pattern[index] && pattern[index] < total)
        {
            phase -= pattern[index];
            index = (index + 1) % pattern.size();
        }
        double remaining = pattern[index] - phase;
        bool on = index % 2 == 0;
        Contour* piece = nullptr;
        auto startPiece = [&](Point p) {
            budget.addPieces(1);
            piece = &out.add();
            piece->hasSegments = true;
            piece->points.push_back(p);
            piece->smooth.push_back(0);
        };
        auto endPiece = [&]() { piece = nullptr; };
        if (on && !c.points.empty())
            startPiece(c.points[0]);
        const size_t n = c.points.size();
        const size_t segments = c.closed ? n : n - 1;
        for (size_t s = 0; s < segments; ++s)
        {
            const Point a = c.points[s];
            const size_t next = s + 1 < n ? s + 1 : 0;
            const Point b = c.points[next];
            const uint8_t bSmooth = next == 0 ? 0 : c.smooth[next];
            const double len = length(a, b);
            double pos = 0.0;
            while (true)
            {
                if (remaining > len - pos)
                {
                    remaining -= len - pos;
                    if (on)
                    {
                        piece->points.push_back(b);
                        piece->smooth.push_back(bSmooth);
                    }
                    break;
                }
                pos += remaining;
                const double t = len > 0.0 ? pos / len : 1.0;
                const Point p{ a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t };
                if (on)
                {
                    piece->points.push_back(p);
                    piece->smooth.push_back(0);
                    endPiece();
                }
                index = (index + 1) % pattern.size();
                remaining = pattern[index];
                on = !on;
                if (on)
                    startPiece(p);
            }
        }
        if (on)
            endPiece();
    }
    return Dashing::eDashed;
}

// ---------------------------------------------------------------------------
// Paint
// ---------------------------------------------------------------------------

/// A color with premultiplied alpha, 0..1.
struct Pixel
{
    float r, g, b, a;
};

/// Rounds a channel value of 0..255 to 8 bits. NaN gives 0.
inline uint8_t to8(float v)
{
    // std::max(0, NaN) is 0, so the conversion always gets a value in range.
    return static_cast<uint8_t>(std::min(255.0f, std::max(0.0f, v)) + 0.5f);
}

/// Rounds a channel value that is known to be 0 .. 255.5, without branches:
/// the same result as to8() for those values.
inline uint8_t toByte(float v)
{
    return static_cast<uint8_t>(std::min(static_cast<int>(v + 0.5f), 255));
}

/// Source-over of color c (premultiplied, 0..1) with coverage k (0..1) onto
/// the stored pixel d (4 bytes, premultiplied). Each channel is the sum of
/// two terms that are not negative, at most 255 together.
inline void blend(uint8_t* d, const Pixel& c, float k)
{
    const float s = 255.0f * k;
    const float inv = 1.0f - c.a * k;
    d[0] = toByte(c.r * s + d[0] * inv);
    d[1] = toByte(c.g * s + d[1] * inv);
    d[2] = toByte(c.b * s + d[2] * inv);
    d[3] = toByte(c.a * s + d[3] * inv);
}

/// blend() of the same color and coverage onto n >= 4 pixels. Four pixels
/// at a time, the loop has no branch, so that compilers can use vector
/// instructions: the clamp of toByte() is left out, as it never applies (each
/// channel is at most 255, see blend()).
inline void blendRun(uint8_t* d, int n, const Pixel& c, float k)
{
    const float s = 255.0f * k;
    const float inv = 1.0f - c.a * k;
    float color[16];
    for (int j = 0; j < 16; j += 4)
    {
        color[j] = c.r * s;
        color[j + 1] = c.g * s;
        color[j + 2] = c.b * s;
        color[j + 3] = c.a * s;
    }
    int i = 0;
    for (; i + 4 <= n; i += 4, d += 16)
    {
        for (int j = 0; j < 16; ++j)
            d[j] = static_cast<uint8_t>(static_cast<int>(color[j] + d[j] * inv + 0.5f));
    }
    for (; i < n; ++i, d += 4)
        blend(d, c, k);
}

/// A rectangle of pixels at (x0, y0) in the bitmap: 4 bytes for each pixel,
/// 8 bits for each channel, premultiplied alpha, as browsers store a canvas.
/// A layer either owns its pixels (a group layer) or paints into the bitmap.
struct Layer
{
    int x0 = 0, y0 = 0, width = 0, height = 0;
    uint8_t* data = nullptr;
    std::vector<uint8_t> owned;
    /// The rectangle of the pixels that were painted; empty while none was.
    int paintedX0 = std::numeric_limits<int>::max(), paintedY0 = std::numeric_limits<int>::max();
    int paintedX1 = std::numeric_limits<int>::min(), paintedY1 = std::numeric_limits<int>::min();

    /// Marks the pixels left .. right-1 of the rows top .. bottom-1 as painted.
    void markPainted(int left, int top, int right, int bottom)
    {
        paintedX0 = std::min(paintedX0, left);
        paintedX1 = std::max(paintedX1, right);
        paintedY0 = std::min(paintedY0, top);
        paintedY1 = std::max(paintedY1, bottom);
    }

    Layer(int x, int y, int w, int h) : x0(x), y0(y), width(w), height(h)
    {
        owned.assign(static_cast<size_t>(w) * static_cast<size_t>(h) * 4, 0);
        data = owned.data();
    }

    Layer(int x, int y, int w, int h, uint8_t* pixels) : x0(x), y0(y), width(w), height(h), data(pixels) {}

    uint8_t* at(int y, int x) const
    {
        return data + (static_cast<size_t>(y - y0) * static_cast<size_t>(width) + static_cast<size_t>(x - x0)) * 4;
    }
};

/// The color of a paint at each pixel of a row.
class PaintSource
{
public:
    /// Returns false when nothing is painted (no paint, or a gradient that
    /// cannot be used with this shape).
    bool prepare(const Paint& paint, float opacity, const Transform& toDevice, const Path& path)
    {
        m_gradient = nullptr;
        if (paint.kind == Paint::Kind::eNone || !(opacity > 0.0f))
            return false;
        if (paint.kind == Paint::Kind::eColor)
        {
            const float a = paint.color.a * opacity;
            m_solid = Pixel{ paint.color.r * a, paint.color.g * a, paint.color.b * a, a };
            m_opaque[0] = to8(m_solid.r * 255.0f);
            m_opaque[1] = to8(m_solid.g * 255.0f);
            m_opaque[2] = to8(m_solid.b * 255.0f);
            m_opaque[3] = 255;
            return a > 0.0f;
        }
        const Gradient& g = *paint.gradient;
        Transform toGradient = toDevice;
        if (!g.userSpaceUnits)
        {
            // A bounding box with no width or no height has no gradient.
            const Rect bbox = path.bounds();
            if (!(bbox.x1 > bbox.x0) || !(bbox.y1 > bbox.y0))
                return false;
            toGradient = toGradient * Transform::translate(bbox.x0, bbox.y0) *
                         Transform::scale(bbox.x1 - bbox.x0, bbox.y1 - bbox.y0);
        }
        toGradient = toGradient * g.transform;
        if (!toGradient.invert(m_fromDevice))
            return false;
        m_gradient = &g;

        // The color table, premultiplied, with the opacity. The entries and
        // the stops are both in the order of t, so one pass goes over both:
        // the work grows with the entries plus the stops, not their product.
        m_table.resize(kGradientTableSize);
        const std::vector<GradientStop>& stops = g.stops;
        size_t next = 1; // the first stop at or after t
        for (int i = 0; i < kGradientTableSize; ++i)
        {
            const float t = static_cast<float>(i) / (kGradientTableSize - 1);
            Color c;
            if (t <= stops.front().offset)
                c = stops.front().color;
            else if (t >= stops.back().offset)
                c = stops.back().color;
            else
            {
                while (!(t <= stops[next].offset))
                    ++next; // ends: t < stops.back().offset
                c = mix(stops[next - 1], stops[next], t);
            }
            const float a = c.a * opacity;
            m_table[static_cast<size_t>(i)] = Pixel{ c.r * a, c.g * a, c.b * a, a };
        }
        if (!g.radial)
        {
            const double dx = g.x2 - g.x1, dy = g.y2 - g.y1;
            const double len2 = dx * dx + dy * dy;
            if (len2 <= 0.0)
            {
                // The same start and end: the color of the last stop.
                m_gradient = nullptr;
                m_solid = m_table.back();
                m_opaque[0] = to8(m_solid.r * 255.0f);
                m_opaque[1] = to8(m_solid.g * 255.0f);
                m_opaque[2] = to8(m_solid.b * 255.0f);
                m_opaque[3] = 255;
                return m_solid.a > 0.0f;
            }
            // t is linear in device x and y.
            const Transform& m = m_fromDevice;
            m_tx = (m.a * dx + m.b * dy) / len2;
            m_ty = (m.c * dx + m.d * dy) / len2;
            m_t0 = ((m.e - g.x1) * dx + (m.f - g.y1) * dy) / len2;
        }
        return true;
    }

    bool solid() const { return m_gradient == nullptr; }
    const Pixel& solidColor() const { return m_solid; }
    /// The bytes of the solid color where it covers a pixel fully.
    const uint8_t* opaqueBytes() const { return m_opaque; }

    /// The colors of the pixels x .. x+n-1 of row y (device pixel centers).
    void row(int x, int y, int n, Pixel* out) const
    {
        const Gradient& g = *m_gradient;
        const double py = y + 0.5;
        for (int i = 0; i < n; ++i)
        {
            const double px = x + i + 0.5;
            double t;
            if (!g.radial)
            {
                t = m_tx * px + m_ty * py + m_t0;
            }
            else
            {
                const Point q = m_fromDevice.apply({ px, py });
                if (!radialT(g, q, t))
                {
                    out[i] = Pixel{ 0, 0, 0, 0 };
                    continue;
                }
            }
            out[i] = m_table[static_cast<size_t>(tableIndex(g.spread, t))];
        }
    }

private:
    /// The color at t between the stops a and b (a.offset < t <= b.offset).
    static Color mix(const GradientStop& a, const GradientStop& b, float t)
    {
        const float span = b.offset - a.offset;
        const float u = span > 0.0f ? (t - a.offset) / span : 1.0f;
        // Straight (not premultiplied) colors are interpolated, as browsers do for SVG.
        Color c;
        c.r = a.color.r + (b.color.r - a.color.r) * u;
        c.g = a.color.g + (b.color.g - a.color.g) * u;
        c.b = a.color.b + (b.color.b - a.color.b) * u;
        c.a = a.color.a + (b.color.a - a.color.a) * u;
        return c;
    }

    static int tableIndex(Gradient::Spread spread, double t)
    {
        if (!std::isfinite(t))
            t = 0.0;
        switch (spread)
        {
        case Gradient::Spread::ePad:
            t = std::min(1.0, std::max(0.0, t));
            break;
        case Gradient::Spread::eRepeat:
            t = t - std::floor(t);
            break;
        case Gradient::Spread::eReflect:
        {
            t = std::fabs(std::fmod(t, 2.0));
            if (t > 1.0)
                t = 2.0 - t;
            break;
        }
        }
        return std::min(kGradientTableSize - 1, std::max(0, static_cast<int>(t * (kGradientTableSize - 1) + 0.5)));
    }

    /// The t of point q for the two circles (focal fx, fy, fr) and (cx, cy, r):
    /// q is on the circle at t of the circles between them. The largest t
    /// with a radius >= 0 is used.
    static bool radialT(const Gradient& g, Point q, double& t)
    {
        const double cdx = g.cx - g.fx, cdy = g.cy - g.fy, dr = g.r - g.fr;
        const double pdx = q.x - g.fx, pdy = q.y - g.fy;
        const double a = cdx * cdx + cdy * cdy - dr * dr;
        const double b = pdx * cdx + pdy * cdy + g.fr * dr;
        const double c = pdx * pdx + pdy * pdy - g.fr * g.fr;
        if (std::fabs(a) < 1e-12)
        {
            if (std::fabs(b) < 1e-12)
                return false;
            t = c / (2.0 * b);
            return g.fr + t * dr >= 0.0;
        }
        const double disc = b * b - a * c;
        if (disc < 0.0)
            return false;
        const double s = std::sqrt(disc);
        const double t1 = (b + s) / a;
        const double t2 = (b - s) / a;
        const double hi = std::max(t1, t2), lo = std::min(t1, t2);
        if (g.fr + hi * dr >= 0.0)
            t = hi;
        else if (g.fr + lo * dr >= 0.0)
            t = lo;
        else
            return false;
        return true;
    }

    const Gradient* m_gradient = nullptr;
    Pixel m_solid{ 0, 0, 0, 0 };
    uint8_t m_opaque[4] = { 0, 0, 0, 255 };
    Transform m_fromDevice;
    std::vector<Pixel> m_table;
    double m_tx = 0.0, m_ty = 0.0, m_t0 = 0.0;
};

// ---------------------------------------------------------------------------
// The painter
// ---------------------------------------------------------------------------

/// Paints the coverage of the rasterizer into a layer: source-over with the
/// color of the paint at each pixel.
struct PaintSink
{
    Layer& target;
    const PaintSource& paint;
    std::vector<Pixel>& colors;

    uint8_t* line = nullptr; ///< the first pixel of the layer in the current row
    int y = 0;

    /// The pixels that the spans of one run can touch.
    void region(int x0, int y0, int x1, int y1) { target.markPainted(x0, y0, x1, y1); }

    void row(int rowY)
    {
        y = rowY;
        line = target.data + static_cast<size_t>(rowY - target.y0) * static_cast<size_t>(target.width) * 4;
    }

    void span(int x, int n, float k)
    {
        uint8_t* dst = line + static_cast<size_t>(x - target.x0) * 4;
        if (!paint.solid())
        {
            colors.resize(static_cast<size_t>(n));
            paint.row(x, y, n, colors.data());
            for (int i = 0; i < n; ++i)
                blend(dst + i * 4, colors[static_cast<size_t>(i)], k);
            return;
        }
        const Pixel& c = paint.solidColor();
        if (c.a * k >= 1.0f)
        {
            // Opaque: the color replaces what was there.
            uint32_t opaque;
            std::memcpy(&opaque, paint.opaqueBytes(), 4);
            for (int i = 0; i < n; ++i)
                std::memcpy(dst + i * 4, &opaque, 4);
            return;
        }
        if (n >= 4)
        {
            blendRun(dst, n, c, k);
            return;
        }
        for (int i = 0; i < n; ++i)
            blend(dst + i * 4, c, k);
    }
};

/// Adds the coverage of a clip shape to a mask: the union of the shapes.
struct MaskSink
{
    float* mask;
    int x0, y0, width;
    float* line = nullptr; ///< the first value of the current row

    void region(int, int, int, int) {}

    void row(int y) { line = mask + static_cast<size_t>(y - y0) * static_cast<size_t>(width); }

    void span(int x, int n, float k)
    {
        float* values = line + (x - x0);
        for (int i = 0; i < n; ++i)
            values[i] = std::max(values[i], k);
    }
};


class Painter
{
public:
    /// Starts a bitmap of `bitmapPixels` pixels: the work is counted from 0.
    void begin(size_t bitmapPixels)
    {
        m_budget = PaintBudget{};
        if (bitmapPixels <= std::numeric_limits<size_t>::max() / kPaintPixelsPerBitmapPixel)
            m_budget.maxPixels = std::max(kMinPaintPixels, bitmapPixels * kPaintPixelsPerBitmapPixel);
        m_changed.clear();
    }

    /// The parts that were painted differently from the file, with the cause.
    const std::vector<std::string>& changed() const { return m_changed; }

    void drawNode(const Node& node, const Transform& parent, Layer& target)
    {
        const Transform ctm = parent * node.transform;
        if (!node.isGroup)
        {
            drawShape(node, ctm, target);
            return;
        }
        if (node.clipToNothing || !(node.opacity > 0.0f))
            return;
        if (node.opacity >= 1.0f && node.clip.empty())
        {
            for (const Node& child : node.children)
                drawNode(child, ctm, target);
            return;
        }
        // Paint the children into a layer that covers their pixels.
        Rect box;
        bool any = false;
        for (const Node& child : node.children)
            unionBounds(child, ctm, box, any);
        if (!any)
            return;
        const int x0 = std::max(target.x0, static_cast<int>(std::floor(std::max(box.x0, -1e9))));
        const int y0 = std::max(target.y0, static_cast<int>(std::floor(std::max(box.y0, -1e9))));
        const int x1 = std::min(target.x0 + target.width, static_cast<int>(std::ceil(std::min(box.x1, 1e9))));
        const int y1 = std::min(target.y0 + target.height, static_cast<int>(std::ceil(std::min(box.y1, 1e9))));
        if (x1 <= x0 || y1 <= y0)
            return;
        // The layer (4 bytes for each pixel) and its clip mask (a float for
        // each pixel) are counted before they are made; the layer is
        // counted again where it is put on the target.
        const size_t area = static_cast<size_t>(x1 - x0) * static_cast<size_t>(y1 - y0);
        const size_t layerBytes = area * (4 + (node.clip.empty() ? 0 : sizeof(float)));
        m_budget.addLayer(layerBytes);
        m_budget.addPixels(area);
        struct Release
        {
            PaintBudget& budget;
            size_t bytes;
            ~Release() { budget.layerBytes -= bytes; }
        } release{ m_budget, layerBytes };
        Layer layer(x0, y0, x1 - x0, y1 - y0);
        for (const Node& child : node.children)
            drawNode(child, ctm, layer);

        std::vector<float> mask;
        if (!node.clip.empty())
        {
            mask.assign(static_cast<size_t>(layer.width) * static_cast<size_t>(layer.height), 0.0f);
            for (const ClipShape& shape : node.clip)
            {
                m_edges.clear();
                addFillEdges(shape.path, ctm * shape.transform, m_edges);
                MaskSink sink{ mask.data(), layer.x0, layer.y0, layer.width };
                m_rasterizer.run(m_edges, shape.rule, layer.x0, layer.y0, layer.x0 + layer.width,
                                 layer.y0 + layer.height, sink);
            }
        }
        // Put the layer on the target: source-over, with the opacity and the clip.
        target.markPainted(layer.x0, layer.y0, layer.x0 + layer.width, layer.y0 + layer.height);
        for (int y = 0; y < layer.height; ++y)
        {
            const uint8_t* src = layer.at(layer.y0 + y, layer.x0);
            uint8_t* dst = target.at(layer.y0 + y, layer.x0);
            const float* m = mask.empty() ? nullptr : mask.data() + static_cast<size_t>(y) * layer.width;
            for (int x = 0; x < layer.width; ++x)
            {
                const float k = node.opacity * (m ? m[x] : 1.0f);
                const uint8_t* s = src + x * 4;
                uint8_t* d = dst + x * 4;
                if (k <= 0.0f || s[3] == 0)
                    continue;
                const float inv = 1.0f - s[3] * (k / 255.0f);
                d[0] = to8(s[0] * k + d[0] * inv);
                d[1] = to8(s[1] * k + d[1] * inv);
                d[2] = to8(s[2] * k + d[2] * inv);
                d[3] = to8(s[3] * k + d[3] * inv);
            }
        }
    }

private:
    void addFillEdges(const Path& path, const Transform& toDevice, EdgeList& edges)
    {
        flatten(path, kTolerance / std::max(toDevice.maxScale(), 1e-12), m_contours);
        for (const Contour& c : m_contours)
            edges.addPolygon(c.points, toDevice);
    }

    void drawShape(const Node& shape, const Transform& ctm, Layer& target)
    {
        if (m_paint.prepare(shape.fill, shape.fillOpacity, ctm, shape.path))
        {
            m_edges.clear();
            addFillEdges(shape.path, ctm, m_edges);
            fillEdges(shape.fillRule, target);
        }
        if (shape.stroke.paint.kind == Paint::Kind::eNone || !(shape.stroke.opacity > 0.0f))
            return;
        m_stroker.reset(shape.stroke, ctm);
        flatten(shape.path, m_stroker.tolerance(), m_contours);
        const Dashing dashing = dash(m_contours, shape.stroke, m_dashes);
        float opacity = shape.stroke.opacity;
        if (dashing == Dashing::eTooFine)
        {
            // Too many dashes to draw one by one: one line with the share of
            // the line that the dashes cover, the same mean color.
            opacity *= static_cast<float>(dashCover(shape.stroke));
            note("a dash pattern that cuts a path into more than " + std::to_string(static_cast<int>(kMaxDashes)) +
                 " dashes is drawn as one line with the average cover of its dashes");
        }
        if (m_paint.prepare(shape.stroke.paint, opacity, ctm, shape.path))
        {
            m_edges.clear();
            for (const Contour& c : dashing == Dashing::eDashed ? m_dashes : m_contours)
                m_stroker.stroke(c);
            fillEdges(FillRule::eNonZero, target);
        }
    }

    void fillEdges(FillRule rule, Layer& target)
    {
        PaintSink sink{ target, m_paint, m_row };
        m_rasterizer.run(m_edges, rule, target.x0, target.y0, target.x0 + target.width,
                         target.y0 + target.height, sink);
    }

    void note(const std::string& what)
    {
        if (std::find(m_changed.begin(), m_changed.end(), what) == m_changed.end())
            m_changed.push_back(what);
    }

    /// A box in device space that holds all pixels the node can paint.
    static void unionBounds(const Node& node, const Transform& parent, Rect& box, bool& any)
    {
        const Transform ctm = parent * node.transform;
        if (node.isGroup)
        {
            for (const Node& child : node.children)
                unionBounds(child, ctm, box, any);
            return;
        }
        const Rect b = node.path.bounds();
        double grow = 1.0;
        if (node.stroke.paint.kind != Paint::Kind::eNone)
        {
            const double reach = std::max(node.stroke.miterLimit, 1.5);
            grow += node.stroke.width * 0.5 * reach * ctm.maxScale();
        }
        const Point corners[4] = { ctm.apply({ b.x0, b.y0 }), ctm.apply({ b.x1, b.y0 }), ctm.apply({ b.x1, b.y1 }),
                                   ctm.apply({ b.x0, b.y1 }) };
        for (const Point& p : corners)
        {
            if (!std::isfinite(p.x) || !std::isfinite(p.y))
                continue;
            if (!any)
            {
                box = Rect{ p.x, p.y, p.x, p.y };
                any = true;
            }
            box.x0 = std::min(box.x0, p.x - grow);
            box.y0 = std::min(box.y0, p.y - grow);
            box.x1 = std::max(box.x1, p.x + grow);
            box.y1 = std::max(box.y1, p.y + grow);
        }
    }

public:
    /// Frees the large buffers after a big bitmap; the painter keeps the rest.
    /// Frees every buffer: after an exception they can hold anything, and the
    /// cell grid must be zero between uses.
    void freeAll()
    {
        m_rasterizer.trim(0);
        m_edges.trim(0);
        m_stroker.trim(0);
        m_contours.trim(0);
        m_dashes.trim(0);
        trimVector(m_row, 0);
        m_edges.clear();
    }

    void trim()
    {
        m_rasterizer.trim(kKeepBytes);
        // The other buffers hold at most a few points, edges or pixels for
        // each line piece; they can only be large after many pieces.
        if (m_budget.pieces <= kKeepBytes / sizeof(Edge) && m_row.capacity() * sizeof(Pixel) <= kKeepBytes)
            return;
        m_edges.trim(kKeepBytes);
        m_stroker.trim(kKeepBytes);
        m_contours.trim(kKeepBytes);
        m_dashes.trim(kKeepBytes);
        trimVector(m_row, kKeepBytes);
    }

private:
    /// The painter of a thread is reused for the next bitmap; each of its
    /// buffers is kept only while it is at most this large.
    static constexpr size_t kKeepBytes = 1024 * 1024;

    PaintBudget m_budget;
    EdgeList m_edges;
    Rasterizer m_rasterizer{ m_budget };
    Stroker m_stroker{ m_edges, m_budget };
    PaintSource m_paint;
    ContourList m_contours{ {}, 0, &m_budget };
    ContourList m_dashes{ {}, 0, &m_budget };
    std::vector<Pixel> m_row;
    std::vector<std::string> m_changed;
};

} // anonymous namespace

bool renderSvgDocument(const Document& doc,
                       uint32_t width,
                       uint32_t height,
                       std::vector<uint8_t>& rgba,
                       std::string& error,
                       std::vector<std::string>& changed)
{
    rgba.clear();
    rgba.resize(static_cast<size_t>(width) * height * 4); // all zero
    if (width == 0 || height == 0 || !(doc.width > 0.0) || !(doc.height > 0.0))
        return true;
    // Paint straight into the bitmap, premultiplied.
    Layer canvas(0, 0, static_cast<int>(width), static_cast<int>(height), rgba.data());
    const Transform toBitmap = Transform::scale(width / doc.width, height / doc.height);
    // Each thread keeps its painter, so that its buffers are not made again
    // for each icon. After an exception the buffers can be in any state, so
    // all of them are freed.
    thread_local Painter painter;
    painter.begin(static_cast<size_t>(width) * height);
    try
    {
        painter.drawNode(doc.root, toBitmap, canvas);
    }
    catch (const PaintLimitError& limit)
    {
        painter.freeAll();
        rgba.clear();
        error = limit.what();
        return false;
    }
    catch (...)
    {
        painter.freeAll();
        throw;
    }
    painter.trim();
    for (const std::string& what : painter.changed())
    {
        if (std::find(changed.begin(), changed.end(), what) == changed.end())
            changed.push_back(what);
    }

    // Premultiplied to straight alpha, rounded to the nearest value:
    // c * 255 / a, done as an exact multiplication by a table of 2^32 / a.
    // Only painted pixels that are neither empty nor opaque change.
    static const std::vector<uint64_t> kReciprocal = [] {
        std::vector<uint64_t> table(256, 0);
        for (uint64_t a = 1; a < 256; ++a)
            table[a] = (uint64_t(1) << 32) / a + 1; // floor(n / a) == (n * table[a]) >> 32 for n < 65536
        return table;
    }();
    auto unpremultiply = [](uint8_t* p) {
        const unsigned a = p[3];
        if (a - 1u >= 254u)
            return; // 0 or 255
        const uint64_t m = kReciprocal[a];
        const unsigned half = a / 2;
        p[0] = static_cast<uint8_t>(std::min<uint64_t>(255, ((p[0] * 255u + half) * m) >> 32));
        p[1] = static_cast<uint8_t>(std::min<uint64_t>(255, ((p[1] * 255u + half) * m) >> 32));
        p[2] = static_cast<uint8_t>(std::min<uint64_t>(255, ((p[2] * 255u + half) * m) >> 32));
    };
    const int x0 = std::max(0, canvas.paintedX0), x1 = std::min(canvas.width, canvas.paintedX1);
    const int y0 = std::max(0, canvas.paintedY0), y1 = std::min(canvas.height, canvas.paintedY1);
    for (int y = y0; y < y1; ++y)
    {
        uint8_t* p = canvas.at(y, x0);
        int x = x0;
        // Four pixels at a time: alpha + 1 is 1 or 256 for alpha 0 and 255,
        // so no bit of 0xFE is set unless a pixel needs a change.
        for (; x + 4 <= x1; x += 4, p += 16)
        {
            if ((((p[3] + 1u) | (p[7] + 1u) | (p[11] + 1u) | (p[15] + 1u)) & 0xFEu) == 0)
                continue;
            unpremultiply(p);
            unpremultiply(p + 4);
            unpremultiply(p + 8);
            unpremultiply(p + 12);
        }
        for (; x < x1; ++x, p += 4)
            unpremultiply(p);
    }
    return true;
}

} // namespace svg
} // namespace standalone
} // namespace ui
} // namespace omni
