"""Write sample DXFs with hand-checkable answers (run: python samples/make_samples.py)."""
import math
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent


def rect(msp, x, y, w, h, layer="CUT"):
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        msp.add_line(a, b, dxfattribs={"layer": layer})


def bracket():
    """L-bracket 120 x 80, 4 mounting holes d8, one slot. Bend line on its own layer."""
    doc = ezdxf.new(units=4)
    for name in ("CUT", "BEND", "TEXT"):
        doc.layers.add(name)
    msp = doc.modelspace()
    # outline as one closed polyline with two rounded corners (r=10)
    r = 10
    b = math.tan(math.radians(90) / 4)
    pts = [(0, 0, 0), (120, 0, 0), (120, 30, 0), (50, 30, 0), (50, 80 - r, b),
           (50 - r, 80, 0), (r, 80, b), (0, 80 - r, 0)]
    msp.add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": "CUT"})
    for cx, cy in ((15, 15), (105, 15), (15, 65), (35, 65)):
        msp.add_circle((cx, cy), 4, dxfattribs={"layer": "CUT"})
    # slot 30 x 8 from lines + arcs
    sx, sy, L, sr = 65, 15, 30, 4
    msp.add_line((sx, sy - sr), (sx + L, sy - sr), dxfattribs={"layer": "CUT"})
    msp.add_arc((sx + L, sy), sr, -90, 90, dxfattribs={"layer": "CUT"})
    msp.add_line((sx + L, sy + sr), (sx, sy + sr), dxfattribs={"layer": "CUT"})
    msp.add_arc((sx, sy), sr, 90, 270, dxfattribs={"layer": "CUT"})
    msp.add_line((0, 30), (50, 30), dxfattribs={"layer": "BEND"})
    msp.add_text("BRACKET-01  t=3", dxfattribs={"layer": "TEXT", "height": 4}).set_placement((55, 40))
    doc.saveas(HERE / "bracket_120x80.dxf")
    # expected: outline 2*(120+80) - 2*(2r - pi*r/2) ... computed in tests instead


def flange():
    """Round flange d200 with d100 bore and 8 bolt holes d12 on PCD 160."""
    doc = ezdxf.new(units=4)
    msp = doc.modelspace()
    msp.add_circle((0, 0), 100)
    msp.add_circle((0, 0), 50)
    for i in range(8):
        a = math.radians(i * 45)
        msp.add_circle((80 * math.cos(a), 80 * math.sin(a)), 6)
    doc.saveas(HERE / "flange_d200.dxf")


def gusset_inch():
    """Triangular gusset drawn in inches (6 x 4 in), one 0.5 in hole."""
    doc = ezdxf.new(units=1)
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (6, 0), (0, 4)], close=True)
    msp.add_circle((1.5, 1.0), 0.25)
    doc.saveas(HERE / "gusset_6x4in.dxf")


def nest_of_four():
    """Four 60 x 40 tags with a d5 hole each, laid out on one sheet."""
    doc = ezdxf.new(units=4)
    msp = doc.modelspace()
    blk = doc.blocks.new("TAG")
    pts = [(0, 0), (60, 0), (60, 40), (0, 40)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        blk.add_line(a, b)
    blk.add_circle((8, 32), 2.5)
    for i in range(4):
        msp.add_blockref("TAG", (i * 70, 0))
    doc.saveas(HERE / "nest_4_tags.dxf")


def broken_outline():
    """Deliberately broken: 1 mm gap in the outline, so the app shows a warning."""
    doc = ezdxf.new(units=4)
    msp = doc.modelspace()
    msp.add_line((0, 0), (80, 0))
    msp.add_line((80, 0), (80, 50))
    msp.add_line((80, 50), (0, 50))
    msp.add_line((0, 50), (0, 1))  # gap
    msp.add_circle((40, 25), 10)
    doc.saveas(HERE / "broken_gap.dxf")


if __name__ == "__main__":
    bracket(); flange(); gusset_inch(); nest_of_four(); broken_outline()
    print("samples written to", HERE)
