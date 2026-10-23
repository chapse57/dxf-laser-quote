"""Draw the measured contours so the operator can see what was counted."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .geometry import Measurement  # noqa: E402


def render(m: Measurement, max_px: int = 900):
    """Return a matplotlib Figure: outlines, holes, open chains, pierce points."""
    w = max(m.width_mm, 1)
    h = max(m.height_mm, 1)
    scale = min(max_px / w, max_px / h, 8)
    fig_w = max(w * scale / 100, 3.5)
    fig_h = max(h * scale / 100, 2.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)

    for c in m.contours:
        xs = [p[0] for p in c.points]
        ys = [p[1] for p in c.points]
        if not c.closed:
            ax.plot(xs, ys, color="#d62728", lw=1.6)
        elif c.is_hole:
            ax.plot(xs + xs[:1], ys + ys[:1], color="#1f77b4", lw=1.2)
        else:
            ax.plot(xs + xs[:1], ys + ys[:1], color="#111111", lw=1.6)
        px, py = c.points[0]
        ax.plot(px, py, marker="o", ms=4, color="#ff7f0e", mec="black", mew=0.4)

    ax.set_aspect("equal")
    ax.margins(0.04)
    ax.set_xlabel("mm")
    ax.set_ylabel("mm")
    ax.grid(True, lw=0.3, alpha=0.5)
    ax.set_title(
        f"{m.cut_length_mm / 1000:.3f} m cut · {m.pierces} pierces · "
        f"{m.parts} part(s), {m.holes} hole(s) · {m.width_mm:.1f} × {m.height_mm:.1f} mm",
        fontsize=10,
    )
    legend = [
        plt.Line2D([], [], color="#111111", lw=1.6, label="outline"),
        plt.Line2D([], [], color="#1f77b4", lw=1.2, label="hole"),
        plt.Line2D([], [], color="#ff7f0e", marker="o", ls="", mec="black", label="pierce"),
    ]
    if m.open_contours:
        legend.append(plt.Line2D([], [], color="#d62728", lw=1.6, label="open contour (check)"))
    ax.legend(handles=legend, loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    return fig
