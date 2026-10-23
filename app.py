"""Laser cutting quote from a DXF. Run with:  streamlit run app.py"""
from __future__ import annotations

import io
from pathlib import Path

import streamlit as st

from laserquote.geometry import cut_layers, is_ignored_by_default, load, measure
from laserquote.preview import render
from laserquote.pricing import load_rates, quote, write_default_rates

ROOT = Path(__file__).parent
RATES_PATH = ROOT / "rates.xlsx"

st.set_page_config(page_title="Laser Quote", page_icon="✂️", layout="wide")
st.title("Laser cutting quote from DXF")
st.caption(
    "Drop in a DXF, pick material and thickness, get cut time and price. "
    "Rates live in rates.xlsx next to this app: edit that file, no code needed."
)

# ------------------------------------------------------------ rates
if not RATES_PATH.exists():
    write_default_rates(RATES_PATH)

with st.sidebar:
    st.header("Rates")
    up_rates = st.file_uploader("Use a different rates.xlsx (optional)", type=["xlsx"])
    try:
        rates = load_rates(up_rates.getvalue()) if up_rates else load_rates(RATES_PATH)
        st.success(f"{len(rates.materials)} material rows loaded")
    except ValueError as e:
        st.error(str(e))
        st.stop()
    st.download_button(
        "Download current rates.xlsx",
        data=RATES_PATH.read_bytes(),
        file_name="rates.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    with st.expander("Settings in use"):
        for k, v in rates.settings.items():
            st.write(f"**{k}**: {v}")

# ------------------------------------------------------------ input
col_file, col_opts = st.columns([2, 1])
with col_file:
    up = st.file_uploader("DXF file", type=["dxf"])
with col_opts:
    material = st.selectbox("Material", rates.material_names)
    thickness = st.selectbox("Thickness (mm)", rates.thicknesses(material), format_func=lambda t: f"{t:g}")
    qty = st.number_input("Quantity", min_value=1, value=1, step=1)

if not up:
    st.info("Upload a DXF to start. Sample files are in the `samples/` folder.")
    st.stop()

data = up.getvalue()
try:
    doc = load(data)
except Exception as e:  # ezdxf raises several types on broken files
    st.error(f"Could not read this DXF: {e}")
    st.stop()

layers = cut_layers(doc)
default_on = [l for l in layers if not is_ignored_by_default(l)]
with col_opts:
    chosen = st.multiselect("Layers to cut", layers, default=default_on,
                            help="Bend, text and dimension layers are off by default.")
ignore = [l for l in layers if l not in chosen]

m = measure(doc, ignore_layers=ignore)
for w in m.warnings:
    st.warning(w)
if m.pierces == 0:
    st.stop()

q = quote(m, rates, material, thickness, int(qty))

# ------------------------------------------------------------ output
c1, c2, c3, c4 = st.columns(4)
c1.metric("Cut length", f"{m.cut_length_mm / 1000:.3f} m")
c2.metric("Pierces", f"{m.pierces}")
c3.metric("Time per part", f"{q.time_per_part_min:.2f} min")
c4.metric(f"Total ({q.currency})", f"{q.total:,.2f}", help=f"{q.unit_price:,.2f} per part")

left, right = st.columns([3, 2])
with left:
    st.pyplot(render(m), use_container_width=True)
with right:
    st.subheader("Price breakdown")
    st.table({"Item": [r[0] for r in q.rows()], "Value": [r[1] for r in q.rows()]})

    csv = io.StringIO()
    csv.write("item,value\n")
    csv.write(f"file,{up.name}\n")
    for k, v in q.rows():
        csv.write(f"{k},\"{v}\"\n")
    st.download_button("Download quote (CSV)", csv.getvalue(), file_name=f"quote_{Path(up.name).stem}.csv")

with st.expander("What was read from the file"):
    st.write(f"Units: {m.units} · Parts: {m.parts} · Holes: {m.holes} · "
             f"Size: {m.width_mm:.1f} × {m.height_mm:.1f} mm · "
             f"Blank area: {m.blank_area_mm2 / 1e6:.4f} m² · Net area: {m.net_area_mm2 / 1e6:.4f} m²")
    st.write(f"Layers cut: {', '.join(m.layers_used) or '-'} · Layers skipped: {', '.join(m.layers_ignored) or '-'}")
    if m.skipped_entities:
        st.write("Entities not cut: " + ", ".join(f"{k} ×{v}" for k, v in m.skipped_entities.items()))
