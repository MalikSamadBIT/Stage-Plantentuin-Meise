import json
import threading

import customtkinter
import tkintermapview
from playwright.sync_api import sync_playwright
from tkcalendar import DateEntry


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SPECIES_ID = 2566
START_DATE = "2016-07-30"
END_DATE = "2026-07-28"
MAP_TYPE = "grid10k"


def _cell_centroid(coordinates):
    ring = coordinates[0]
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def fetch_grid_data(start_date, end_date, species_id=SPECIES_ID, map_type=MAP_TYPE):
    # Returns a list of dicts: cell_id, lat, lon, count, num_obs.
    interval = (end_date - start_date).days * 86400
    base_url = (
        f"https://waarnemingen.be/species/{species_id}/maps/"
        f"?start_date={start_date}&interval={interval}&end_date={end_date}&map_type={map_type}"
    )
    json_url = base_url + "&json="

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Visit the normal map page first so Anubis's JS challenge runs and sets the auth cookie then the JSON URL request reuses that cookie.
        page.goto(base_url, wait_until="networkidle")
        response = page.goto(json_url, wait_until="networkidle")
        text = response.text()
        browser.close()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Non-JSON response from waarnemingen.be (first 500 chars):\n{text[:500]}")

    results = []
    for feat in data.get("features", []):
        props = feat["properties"]
        lat, lon = _cell_centroid(feat["geometry"]["coordinates"])
        results.append(
            {
                "cell_id": props["cell"],
                "lat": lat,
                "lon": lon,
                "count": props["count"],
                "num_obs": props["num_obs"],
            }
        )
    return results


# --- map GUI ----------------------------------------------------------------

def main():
    tk = customtkinter.CTk()
    tk.title("geoloc")
    tk.geometry("760x560")

    controls = customtkinter.CTkFrame(tk)
    controls.pack(fill="x", padx=8, pady=8)

    customtkinter.CTkLabel(controls, text="Start date:").pack(side="left", padx=(8, 4))
    start_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    start_date_entry.pack(side="left", padx=(0, 12))
    start_date_entry.set_date(START_DATE)

    customtkinter.CTkLabel(controls, text="End date:").pack(side="left", padx=(0, 4))
    end_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    end_date_entry.pack(side="left", padx=(0, 12))
    end_date_entry.set_date(END_DATE)

    load_button = customtkinter.CTkButton(controls, text="Load")
    load_button.pack(side="left")

    status_label = customtkinter.CTkLabel(controls, text="")
    status_label.pack(side="left", padx=12)

    map_widget = tkintermapview.TkinterMapView(
        tk, width=760, height=480, corner_radius=0)
    map_widget.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    map_widget.set_position(52.1326, 5.2913)
    map_widget.set_zoom(7)

    # fetch_grid_data() drives a headless browser and can take 10-20s (loading
    # the page, passing the anti-bot check), so it runs on a background thread.
    # Only the main thread touches Tk/map widgets - the thread just writes into
    # `result`, and the main thread polls it via tk.after.
    result = {}

    def load_data(start_date, end_date):
        try:
            result["cells"] = fetch_grid_data(start_date, end_date)
        except Exception as e:
            import traceback
            traceback.print_exc()
            result["error"] = str(e)

    def poll():
        if "cells" in result:
            cells = result.pop("cells")
            status_label.configure(text=f"Loaded {len(cells)} grid cells")
            load_button.configure(state="normal", text="Load")
            map_widget.delete_all_marker()
            for cell in cells:
                map_widget.set_marker(
                    cell["lat"], cell["lon"],
                    text=f"Max. individuen: {cell['count']}\nWaarnemingen: {cell['num_obs']}")
            if cells:
                map_widget.fit_bounding_box(
                    (max(c["lat"] for c in cells), min(c["lon"] for c in cells)),
                    (min(c["lat"] for c in cells), max(c["lon"] for c in cells)))
            return
        if "error" in result:
            error = result.pop("error")
            status_label.configure(text=f"Failed to load data: {error}")
            load_button.configure(state="normal", text="Load")
            return
        tk.after(200, poll)

    def on_load_clicked():
        start_date = start_date_entry.get_date()
        end_date = end_date_entry.get_date()
        if start_date >= end_date:
            status_label.configure(text="Start date must be before end date")
            return
        load_button.configure(state="disabled", text="Loading...")
        status_label.configure(text="Loading observation data...")
        threading.Thread(target=load_data, args=(start_date, end_date), daemon=True).start()
        tk.after(200, poll)

    load_button.configure(command=on_load_clicked)

    on_load_clicked()

    tk.mainloop()


if __name__ == "__main__":
    main()
