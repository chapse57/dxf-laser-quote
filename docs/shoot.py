"""Screenshot the running app with a sample file loaded (for the README)."""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sample = ROOT / "samples" / (sys.argv[1] if len(sys.argv) > 1 else "bracket_120x80.dxf")
out = ROOT / "docs" / f"screenshot_{sample.stem}.png"

with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1100})
    page.goto("http://localhost:8501", wait_until="networkidle")
    page.wait_for_timeout(2500)
    inputs = page.locator("input[type=file]")
    inputs.nth(1).set_input_files(str(sample))  # 0 = rates uploader in sidebar, 1 = DXF
    page.wait_for_timeout(6000)
    # a realistic order for the picture: 3 mm, qty 25
    page.get_by_label("Thickness (mm)").click()
    page.keyboard.type("3")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2500)
    qty = page.get_by_label("Quantity")
    qty.click()
    qty.fill("25")
    qty.press("Enter")
    page.wait_for_timeout(4000)
    page.screenshot(path=str(out), full_page=True)
    b.close()
print(out)
