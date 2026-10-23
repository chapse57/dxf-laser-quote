"""Each test draws a part whose cut length and pierce count are known
by hand, then checks the measurement against that answer."""
import math

import ezdxf
import pytest

from laserquote.geometry import measure

TAU = 2 * math.pi


def new_mm():
    doc = ezdxf.new(units=4)  # $INSUNITS 4 = millimetres
    return doc, doc.modelspace()


def rect_lines(msp, x, y, w, h, layer="0"):
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def test_plate_with_two_holes_from_loose_lines():
    doc, msp = new_mm()
    rect_lines(msp, 0, 0, 100, 50)  # four separate LINEs = one contour
    msp.add_circle((25, 25), 5)
    msp.add_circle((75, 25), 5)
    m = measure(doc)
    assert m.cut_length_mm == pytest.approx(300 + 2 * TAU * 5, rel=1e-9)
    assert m.pierces == 3
    assert (m.parts, m.holes) == (1, 2)
    assert (m.width_mm, m.height_mm) == pytest.approx((100, 50))
    assert m.blank_area_mm2 == pytest.approx(5000)
    assert m.net_area_mm2 == pytest.approx(5000 - 2 * math.pi * 25, rel=1e-4)
    assert m.open_contours == 0


def test_rounded_rectangle_polyline_with_bulges():
    # 100 x 50 rectangle, corner radius 10, as one closed LWPOLYLINE
    doc, msp = new_mm()
    r, w, h = 10, 100, 50
    b = math.tan(math.radians(90) / 4)  # bulge of a 90 degree arc
    pts = [
        (r, 0, 0), (w - r, 0, b), (w, r, 0), (w, h - r, b),
        (w - r, h, 0), (r, h, b), (0, h - r, 0), (0, r, b),
    ]
    msp.add_lwpolyline(pts, format="xyb", close=True)
    m = measure(doc)
    expected = 2 * (w - 2 * r) + 2 * (h - 2 * r) + TAU * r
    assert m.cut_length_mm == pytest.approx(expected, rel=1e-9)
    assert m.pierces == 1
    assert m.net_area_mm2 == pytest.approx(w * h - (4 - math.pi) * r * r, rel=1e-4)


def test_slot_from_lines_and_arcs_is_one_closed_contour():
    doc, msp = new_mm()
    L, r = 40, 6
    msp.add_line((0, -r), (L, -r))
    msp.add_arc((L, 0), r, -90, 90)
    msp.add_line((L, r), (0, r))
    msp.add_arc((0, 0), r, 90, 270)
    m = measure(doc)
    assert m.cut_length_mm == pytest.approx(2 * L + TAU * r, rel=1e-9)
    assert m.pierces == 1
    assert m.open_contours == 0


def test_inch_drawing_is_converted_to_mm():
    doc = ezdxf.new(units=1)  # inches
    rect_lines(doc.modelspace(), 0, 0, 4, 2)
    m = measure(doc)
    assert m.units == "inch"
    assert m.cut_length_mm == pytest.approx(12 * 25.4)
    assert m.width_mm == pytest.approx(101.6)


def test_bend_and_text_layers_are_left_out_by_default():
    doc, msp = new_mm()
    rect_lines(msp, 0, 0, 100, 50)
    msp.add_line((50, 0), (50, 50), dxfattribs={"layer": "BEND"})
    msp.add_text("PART-01", dxfattribs={"layer": "TEXT"})
    m = measure(doc)
    assert m.cut_length_mm == pytest.approx(300)
    assert m.layers_ignored == ["BEND"]
    assert m.skipped_entities == {"TEXT": 1}


def test_ignore_list_can_be_overridden():
    doc, msp = new_mm()
    rect_lines(msp, 0, 0, 100, 50)
    msp.add_line((50, 0), (50, 50), dxfattribs={"layer": "BEND"})
    m = measure(doc, ignore_layers=[])
    assert m.cut_length_mm == pytest.approx(350)


def test_blocks_are_exploded_with_their_scale():
    doc, msp = new_mm()
    blk = doc.blocks.new("HOLE")
    blk.add_circle((0, 0), 5)
    rect_lines(msp, 0, 0, 100, 50)
    msp.add_blockref("HOLE", (20, 25))
    msp.add_blockref("HOLE", (60, 25), dxfattribs={"xscale": 2, "yscale": 2})
    m = measure(doc)
    assert m.cut_length_mm == pytest.approx(300 + TAU * 5 + TAU * 10, rel=1e-9)
    assert m.pierces == 3


def test_duplicate_entities_are_counted_once():
    doc, msp = new_mm()
    rect_lines(msp, 0, 0, 100, 50)
    msp.add_line((0, 0), (100, 0))  # same edge drawn twice
    msp.add_line((100, 50), (100, 0))  # and one drawn backwards
    m = measure(doc)
    assert m.cut_length_mm == pytest.approx(300)
    assert m.duplicates_removed == 2
    assert m.open_contours == 0


def test_gap_in_outline_is_reported_as_open():
    doc, msp = new_mm()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 50))
    msp.add_line((100, 50), (0, 50))
    msp.add_line((0, 50), (0, 0.5))  # 0.5 mm short of closing
    m = measure(doc)
    assert m.open_contours == 1
    assert m.pierces == 1
    assert any("open contour" in w for w in m.warnings)


def test_tiny_gap_within_tolerance_still_closes():
    doc, msp = new_mm()
    msp.add_line((0, 0), (100, 0))
    msp.add_line((100, 0), (100, 50))
    msp.add_line((100, 50), (0, 50))
    msp.add_line((0, 50), (0, 0.004))  # 0.004 mm: CAD rounding, not a real gap
    m = measure(doc)
    assert m.open_contours == 0


def test_full_ellipse_is_measured_on_the_approximation():
    # an ellipse with ratio 1 is a circle, so the exact answer is known
    doc, msp = new_mm()
    msp.add_ellipse((0, 0), major_axis=(20, 0), ratio=1.0)
    m = measure(doc)
    # ezdxf approximates an ellipse with curves, so allow 0.1% here
    assert m.cut_length_mm == pytest.approx(TAU * 20, rel=1e-3)
    assert m.pierces == 1


def test_two_separate_parts_in_one_file():
    doc, msp = new_mm()
    rect_lines(msp, 0, 0, 50, 50)
    rect_lines(msp, 80, 0, 30, 20)
    msp.add_circle((25, 25), 10)
    m = measure(doc)
    assert (m.parts, m.holes, m.pierces) == (2, 1, 3)
    assert m.blank_area_mm2 == pytest.approx(50 * 50 + 30 * 20)


def test_file_without_units_assumes_mm_and_says_so():
    doc = ezdxf.new(units=0)
    rect_lines(doc.modelspace(), 0, 0, 10, 10)
    m = measure(doc)
    assert m.unit_assumed
    assert m.cut_length_mm == pytest.approx(40)
    assert any("no units" in w for w in m.warnings)


def test_reads_from_bytes(tmp_path):
    doc, msp = new_mm()
    msp.add_circle((0, 0), 10)
    path = tmp_path / "part.dxf"
    doc.saveas(path)
    m = measure(path.read_bytes())
    assert m.cut_length_mm == pytest.approx(TAU * 10)
