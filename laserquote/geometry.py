"""Read a DXF file and measure what a laser has to cut.

What it reports, all in millimetres:
- total cut length (lines, arcs and circles measured exactly; splines,
  ellipses and old-style polylines measured on a fine approximation)
- pierce count: one pierce per contour
- parts, holes, overall size, bounding-box ("blank") area and net area

Loose LINE/ARC entities that touch end to end are joined into contours,
so a rectangle drawn as four separate lines is one contour and one pierce.
Exact duplicate entities (a common export problem) are dropped once, so
their length is not counted twice.
"""
from __future__ import annotations

import io
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterable, Union

import ezdxf
from ezdxf import path as ezpath
from ezdxf import recover
from ezdxf.document import Drawing

Point = tuple[float, float]

# DXF $INSUNITS code -> (name, millimetres per drawing unit)
UNITS = {
    1: ("inch", 25.4),
    2: ("foot", 304.8),
    4: ("mm", 1.0),
    5: ("cm", 10.0),
    6: ("m", 1000.0),
    9: ("mil", 0.0254),
}

# Entities a laser cuts. Everything else (TEXT, DIMENSION, HATCH, POINT ...)
# is reported as skipped.
CUT_TYPES = {"LINE", "ARC", "CIRCLE", "LWPOLYLINE", "POLYLINE", "SPLINE", "ELLIPSE"}

# Layer names containing one of these words are left out by default.
# The user can change the selection in the app.
DEFAULT_IGNORE_WORDS = (
    "DIM", "TEXT", "NOTE", "BEND", "ETCH", "MARK", "ENGRAV", "TITLE",
    "BORDER", "FRAME", "DEFPOINTS", "CENTER", "HIDDEN",
)

FLATTEN_MM = 0.002  # max deviation (mm) when a curve has to be approximated


def is_ignored_by_default(layer: str) -> bool:
    upper = layer.upper()
    return any(word in upper for word in DEFAULT_IGNORE_WORDS)


@dataclass
class Piece:
    """One cut entity after block explosion, in millimetres."""

    kind: str
    layer: str
    length: float
    points: list[Point]  # flattened path, used for joining, area and preview
    closed: bool

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]


@dataclass
class Contour:
    """A closed loop (or an open chain) made of one or more pieces."""

    pieces: list[Piece]
    closed: bool
    points: list[Point]  # ordered outline for closed contours
    depth: int = 0  # how many closed contours this one sits inside

    @property
    def length(self) -> float:
        return sum(p.length for p in self.pieces)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def area(self) -> float:
        return abs(_shoelace(self.points)) if self.closed else 0.0

    @property
    def is_hole(self) -> bool:
        return self.closed and self.depth % 2 == 1


@dataclass
class Measurement:
    cut_length_mm: float
    pierces: int
    parts: int
    holes: int
    width_mm: float
    height_mm: float
    blank_area_mm2: float  # sum of each part's bounding box
    net_area_mm2: float  # outlines minus holes
    open_contours: int
    duplicates_removed: int
    units: str
    unit_assumed: bool
    layers_used: list[str]
    layers_ignored: list[str]
    skipped_entities: dict[str, int]
    contours: list[Contour] = field(repr=False)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- reading

DxfSource = Union[str, Path, bytes, BinaryIO, Drawing]


def load(source: DxfSource) -> Drawing:
    """Open a DXF from a path, raw bytes, a binary stream or a Drawing.

    ezdxf's recover mode is used so slightly broken exports still open.
    """
    if isinstance(source, Drawing):
        return source
    if isinstance(source, (str, Path)):
        doc, _ = recover.readfile(str(source))
        return doc
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    doc, _ = recover.read(source)
    return doc


def drawing_units(doc: Drawing) -> tuple[str, float, bool]:
    """Return (unit name, mm per unit, assumed?)."""
    code = doc.header.get("$INSUNITS", 0)
    if code in UNITS:
        name, factor = UNITS[code]
        return name, factor, False
    return "mm", 1.0, True


def cut_layers(doc: Drawing) -> list[str]:
    """Layers that hold at least one cuttable entity (blocks included)."""
    layers = {layer for e, layer in _walk(doc.modelspace()) if e.dxftype() in CUT_TYPES}
    return sorted(layers)


def _walk(entities: Iterable, parent_layer: str | None = None):
    """Yield (entity, effective layer) for cut entities, exploding blocks."""
    for e in entities:
        layer = e.dxf.get("layer", "0")
        if parent_layer is not None and layer == "0":
            layer = parent_layer  # block content on layer 0 takes the INSERT's layer
        kind = e.dxftype()
        if kind == "INSERT":
            try:
                yield from _walk(e.virtual_entities(), layer)
            except Exception:  # unsupported transform: report the block as skipped
                yield e, layer
        else:
            yield e, layer


# ---------------------------------------------------------- measuring one

def _exact_length(e) -> float | None:
    """Length in drawing units for entities with a closed-form answer."""
    kind = e.dxftype()
    if kind == "LINE":
        return (e.dxf.end - e.dxf.start).magnitude
    if kind == "CIRCLE":
        return 2 * math.pi * e.dxf.radius
    if kind == "ARC":
        span = (e.dxf.end_angle - e.dxf.start_angle) % 360.0
        if span == 0:
            span = 360.0
        return e.dxf.radius * math.radians(span)
    if kind == "LWPOLYLINE":
        pts = list(e.get_points("xyb"))
        if len(pts) < 2:
            return 0.0
        segments = list(zip(pts, pts[1:]))
        if e.closed:
            segments.append((pts[-1], pts[0]))
        total = 0.0
        for (x1, y1, bulge), (x2, y2, _) in segments:
            chord = math.hypot(x2 - x1, y2 - y1)
            if bulge == 0 or chord == 0:
                total += chord
            else:
                theta = 4 * math.atan(abs(bulge))  # included angle of the arc
                total += chord * theta / (2 * math.sin(theta / 2))
        return total
    return None  # SPLINE, ELLIPSE, POLYLINE: measured on the flattened path


def _to_piece(e, layer: str, scale: float) -> Piece | None:
    try:
        p = ezpath.make_path(e)
    except (TypeError, ValueError):
        return None
    if len(p) == 0 and e.dxftype() != "LINE":
        return None
    pts3 = list(p.flattening(FLATTEN_MM / scale))
    pts = [(v.x * scale, v.y * scale) for v in pts3]
    if len(pts) < 2:
        return None
    exact = _exact_length(e)
    if exact is not None:
        length = exact * scale
    else:
        length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    closed = e.dxftype() == "CIRCLE" or bool(getattr(e, "closed", False))
    if e.dxftype() == "POLYLINE":
        closed = e.is_closed
    if e.dxftype() == "ELLIPSE":
        closed = math.isclose(abs(e.dxf.end_param - e.dxf.start_param), math.tau, abs_tol=1e-9)
    if not closed and math.dist(pts[0], pts[-1]) <= 1e-6:
        closed = True
    return Piece(e.dxftype(), layer, length, pts, closed)


# ------------------------------------------------------- joining contours

class _Nodes:
    """Snap endpoints that are within `tol` of each other to one node."""

    def __init__(self, tol: float):
        self.tol = tol
        self.grid: dict[tuple[int, int], list[int]] = defaultdict(list)
        self.coords: list[Point] = []

    def get(self, pt: Point) -> int:
        cx, cy = round(pt[0] / self.tol), round(pt[1] / self.tol)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for idx in self.grid[(cx + dx, cy + dy)]:
                    if math.dist(self.coords[idx], pt) <= self.tol:
                        return idx
        self.coords.append(pt)
        idx = len(self.coords) - 1
        self.grid[(cx, cy)].append(idx)
        return idx


def _join(pieces: list[Piece], tol: float) -> list[Contour]:
    contours = [Contour([p], True, list(p.points)) for p in pieces if p.closed]
    open_pieces = [p for p in pieces if not p.closed]
    if not open_pieces:
        return contours

    nodes = _Nodes(tol)
    ends = [(nodes.get(p.start), nodes.get(p.end)) for p in open_pieces]

    parent = list(range(len(nodes.coords)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a, b in ends:
        parent[find(a)] = find(b)

    groups: dict[int, list[int]] = defaultdict(list)
    for i, (a, _) in enumerate(ends):
        groups[find(a)].append(i)

    for members in groups.values():
        degree = Counter()
        for i in members:
            a, b = ends[i]
            degree[a] += 1
            degree[b] += 1
        closed = all(d == 2 for d in degree.values())
        group_pieces = [open_pieces[i] for i in members]
        if closed:
            points = _order_loop([ends[i] for i in members], group_pieces)
        else:
            points = [pt for p in group_pieces for pt in p.points]
        contours.append(Contour(group_pieces, closed, points))
    return contours


def _order_loop(ends: list[tuple[int, int]], pieces: list[Piece]) -> list[Point]:
    """Walk a loop where every node has exactly two pieces."""
    at_node: dict[int, list[int]] = defaultdict(list)
    for i, (a, b) in enumerate(ends):
        at_node[a].append(i)
        at_node[b].append(i)
    used = {0}
    points = list(pieces[0].points)
    node = ends[0][1]
    start_node = ends[0][0]
    while node != start_node or len(used) < len(pieces):
        nxt = next((i for i in at_node[node] if i not in used), None)
        if nxt is None:
            break
        used.add(nxt)
        a, b = ends[nxt]
        if a == node:
            points.extend(pieces[nxt].points[1:])
            node = b
        else:
            points.extend(reversed(pieces[nxt].points[:-1]))
            node = a
    return points


# ------------------------------------------------------------ geometry

def _shoelace(pts: list[Point]) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        s += x1 * y2 - x2 * y1
    return s / 2


def _inside(pt: Point, poly: list[Point]) -> bool:
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if (y1 > y) != (y2 > y):
            xc = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xc:
                inside = not inside
    return inside


def _bbox_within(inner, outer) -> bool:
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _set_depths(contours: list[Contour]) -> None:
    closed = [c for c in contours if c.closed]
    for c in contours:
        probe = c.points[len(c.points) // 2]
        c.depth = sum(
            1
            for other in closed
            if other is not c and _bbox_within(c.bbox, other.bbox) and _inside(probe, other.points)
        )


def _point_at_half_length(pts: list[Point]) -> Point:
    """Point halfway along the flattened path, independent of direction."""
    total = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    target = total / 2
    run = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = math.dist(a, b)
        if run + seg >= target and seg > 0:
            t = (target - run) / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        run += seg
    return pts[-1]


def _signature(p: Piece, tol: float):
    """Same geometry drawn twice (even reversed) gives the same signature."""
    r = lambda v: round(v / tol)  # noqa: E731
    ends = tuple(sorted(((r(p.start[0]), r(p.start[1])), (r(p.end[0]), r(p.end[1])))))
    mid = _point_at_half_length(p.points)
    return (round(p.length, 3), ends, (r(mid[0]), r(mid[1])))


# ---------------------------------------------------------------- main

def measure(
    source: DxfSource,
    ignore_layers: Iterable[str] | None = None,
    tol_mm: float = 0.01,
) -> Measurement:
    """Measure a DXF. `ignore_layers=None` uses the default name rules."""
    doc = load(source)
    unit_name, scale, assumed = drawing_units(doc)

    all_layers = cut_layers(doc)
    if ignore_layers is None:
        ignored = {l for l in all_layers if is_ignored_by_default(l)}
    else:
        ignored = set(ignore_layers)

    pieces: list[Piece] = []
    skipped: Counter = Counter()
    seen = set()
    duplicates = 0
    for e, layer in _walk(doc.modelspace()):
        kind = e.dxftype()
        if kind not in CUT_TYPES:
            skipped[kind] += 1
            continue
        if layer in ignored:
            continue
        piece = _to_piece(e, layer, scale)
        if piece is None or piece.length <= 0:
            skipped[kind] += 1
            continue
        sig = _signature(piece, tol_mm)
        if sig in seen:
            duplicates += 1
            continue
        seen.add(sig)
        pieces.append(piece)

    contours = _join(pieces, tol_mm)
    if contours:
        _set_depths(contours)

    closed = [c for c in contours if c.closed]
    parts = [c for c in closed if c.depth % 2 == 0]
    holes = [c for c in closed if c.depth % 2 == 1]
    open_count = sum(1 for c in contours if not c.closed)

    if contours:
        xs = [x for c in contours for x, _ in c.points]
        ys = [y for c in contours for _, y in c.points]
        width, height = max(xs) - min(xs), max(ys) - min(ys)
    else:
        width = height = 0.0

    blank = sum((c.bbox[2] - c.bbox[0]) * (c.bbox[3] - c.bbox[1]) for c in parts)
    net = sum(c.area for c in parts) - sum(c.area for c in holes)

    warnings = []
    if assumed:
        warnings.append("The file has no units set ($INSUNITS). Assumed millimetres.")
    if open_count:
        warnings.append(
            f"{open_count} open contour(s): the outline has a gap bigger than "
            f"{tol_mm} mm or lines that cross. Each is still counted as one pierce. "
            "Check the drawing (shown in red)."
        )
    if duplicates:
        warnings.append(f"{duplicates} duplicate entit{'y' if duplicates == 1 else 'ies'} removed (drawn twice on top of each other).")
    if not contours:
        warnings.append("No cut geometry found on the selected layers.")

    return Measurement(
        cut_length_mm=sum(c.length for c in contours),
        pierces=len(contours),
        parts=len(parts),
        holes=len(holes),
        width_mm=width,
        height_mm=height,
        blank_area_mm2=blank,
        net_area_mm2=net,
        open_contours=open_count,
        duplicates_removed=duplicates,
        units=f"{unit_name}" + (" (assumed)" if assumed else ""),
        unit_assumed=assumed,
        layers_used=[l for l in all_layers if l not in ignored],
        layers_ignored=[l for l in all_layers if l in ignored],
        skipped_entities=dict(skipped),
        contours=contours,
        warnings=warnings,
    )
