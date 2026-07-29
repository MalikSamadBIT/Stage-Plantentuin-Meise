import json
import re
import threading
from urllib.parse import quote_plus
from urllib.request import urlopen

import customtkinter
import tkintermapview
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from tkcalendar import DateEntry


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_URL = "https://observation.org/search/?q="

DEFAULT_SPECIES_NAME = "Huperzia selago"
START_DATE = "2016-07-30"
END_DATE = "2026-07-28"
MAP_TYPE = "grid25k"


def lookup_species_id(name):
    # The /search/ page isn't behind the Anubis anti-bot check (unlike the/maps/endpoint), so a plain urlopen works here

    query_url = SEARCH_URL + quote_plus(name.strip())
    with urlopen(query_url) as page:
        html = page.read().decode("utf-8")
    soup = BeautifulSoup(html, "html.parser")
    link = soup.find("a", {"href": re.compile(r"^/species/\d+/$")})
    if not link:
        raise ValueError(f"No species found for '{name}'")
    return int(re.search(r"/species/(\d+)/", link["href"]).group(1))


def _cell_centroid(coordinates):
    ring = coordinates[0]
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return sum(lats) / len(lats), sum(lons) / len(lons)


def fetch_grid_data(species_id, start_date, end_date, map_type=MAP_TYPE):
    # Returns a list of dicts: cell_id, lat, lon, count, num_obs.
    interval = (end_date - start_date).days * 86400
    base_url = (
        f"https://observation.org/species/{species_id}/maps/"
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
customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")


def main():
    tk = customtkinter.CTk()
    tk.title("geoloc")
    tk.geometry("900x560")

    controls = customtkinter.CTkFrame(tk)
    controls.pack(fill="x", padx=8, pady=8)

    customtkinter.CTkLabel(controls, text="Species:").pack(
        side="left", padx=(8, 4))
    species_entry = customtkinter.CTkEntry(controls, width=160)
    species_entry.pack(side="left", padx=(0, 12))
    species_entry.insert(0, DEFAULT_SPECIES_NAME)

    customtkinter.CTkLabel(controls, text="Start date:").pack(
        side="left", padx=(8, 4))
    start_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    start_date_entry.pack(side="left", padx=(0, 12))
    start_date_entry.set_date(START_DATE)

    customtkinter.CTkLabel(controls, text="End date:").pack(
        side="left", padx=(0, 4))
    end_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    end_date_entry.pack(side="left", padx=(0, 12))
    end_date_entry.set_date(END_DATE)

    load_button = customtkinter.CTkButton(controls, text="Load")
    load_button.pack(side="left")

    status_label = customtkinter.CTkLabel(controls, text="")
    status_label.pack(side="left", padx=12)

    map_widget = tkintermapview.TkinterMapView(
        tk, width=900, height=480, corner_radius=0)
    map_widget.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    map_widget.set_position(52.1326, 5.2913)
    map_widget.set_zoom(7)

    # fetch_grid_data() drives a headless browser and can take 10-20s (loading
    # the page, passing the anti-bot check), so it runs on a background thread.
    # Only the main thread touches Tk/map widgets - the thread just writes into
    # `result`, and the main thread polls it via tk.after.
    result = {}

    def load_data(species_name, start_date, end_date):
        try:
            species_id = lookup_species_id(species_name)
            result["cells"] = fetch_grid_data(species_id, start_date, end_date)
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
                    # text=f"Max. individuen: {cell['count']}\nWaarnemingen: {cell['num_obs']}")
                    text=f"{cell['num_obs']}")
            if cells:
                map_widget.fit_bounding_box(
                    (max(c["lat"] for c in cells), min(c["lon"]
                     for c in cells)),
                    (min(c["lat"] for c in cells), max(c["lon"] for c in cells)))
            return
        if "error" in result:
            error = result.pop("error")
            status_label.configure(text=f"Failed to load data: {error}")
            load_button.configure(state="normal", text="Load")
            return
        tk.after(200, poll)

    def on_load_clicked():
        species_name = species_entry.get().strip()
        start_date = start_date_entry.get_date()
        end_date = end_date_entry.get_date()
        if not species_name:
            status_label.configure(text="Enter a species name")
            return
        if start_date >= end_date:
            status_label.configure(text="Start date must be before end date")
            return
        load_button.configure(state="disabled", text="Loading...")
        status_label.configure(text=f"Looking up '{species_name}'...")
        threading.Thread(
            target=load_data, args=(
                species_name, start_date, end_date), daemon=True
        ).start()
        tk.after(200, poll)

    load_button.configure(command=on_load_clicked)

    on_load_clicked()

    tk.mainloop()


if __name__ == "__main__":
    main()
