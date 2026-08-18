import threading
import webbrowser

import customtkinter as ctk
import tkintermapview
from tkcalendar import DateEntry

import database
from geoloc_client import (
    SITES, build_gridcell_url, fetch_grid_data, lookup_species_id
)

DEFAULT_SITE = "Belgium (waarnemingen.be)"
DEFAULT_SPECIES_NAME = ""
DEFAULT_START_DATE = "2016-02-29"
DEFAULT_END_DATE = "2026-07-28"

# light -> dark density gradient (ColorBrewer YlOrRd-style) for shading
# grid cells by observation count, light-to-heavy
_HEATMAP_STOPS = [
    (0.0, (255, 255, 178)),
    (0.5, (253, 141, 60)),
    (1.0, (189, 0, 38)),
]


def _color_for_count(count, max_count):
    t = 0.0 if max_count <= 0 else max(0.0, min(1.0, count / max_count))

    for (t0, c0), (t1, c1) in zip(_HEATMAP_STOPS, _HEATMAP_STOPS[1:]):
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0)
            rgb = tuple(round(c0[i] + (c1[i] - c0[i]) * frac)
                        for i in range(3))
            return "#{:02x}{:02x}{:02x}".format(*rgb)

    return "#{:02x}{:02x}{:02x}".format(*_HEATMAP_STOPS[-1][1])


def build_maps_tab(parent, root=None, db_config=None):
    """
    parent: the tab frame to build the widgets into.
    root: the main app window (unused here, kept for consistency with the
        other build_*_tab functions).
    db_config: shared database.DatabaseConfig chosen in the Settings tab -
        used to look up how many sequences are already on file for the
        searched species. Falls back to a private (unconfigured) one if
        this tab is ever used standalone.
    """

    if db_config is None:
        db_config = database.DatabaseConfig()

    controls = ctk.CTkFrame(parent)
    controls.pack(fill="x", padx=10, pady=10)

    ctk.CTkLabel(controls, text="Map:").pack(side="left", padx=(8, 4))
    site_var = ctk.StringVar(value=DEFAULT_SITE)
    ctk.CTkSegmentedButton(
        controls, values=list(SITES.keys()), variable=site_var
    ).pack(side="left", padx=(0, 12))

    ctk.CTkLabel(controls, text="Species:").pack(side="left", padx=(8, 4))
    species_entry = ctk.CTkEntry(controls, width=160)
    species_entry.pack(side="left", padx=(0, 12))
    species_entry.insert(0, DEFAULT_SPECIES_NAME)

    ctk.CTkLabel(controls, text="Start date:").pack(side="left", padx=(8, 4))
    start_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    start_date_entry.pack(side="left", padx=(0, 12))
    start_date_entry.set_date(DEFAULT_START_DATE)

    ctk.CTkLabel(controls, text="End date:").pack(side="left", padx=(0, 4))
    end_date_entry = DateEntry(controls, date_pattern="yyyy-mm-dd")
    end_date_entry.pack(side="left", padx=(0, 12))
    end_date_entry.set_date(DEFAULT_END_DATE)

    load_button = ctk.CTkButton(controls, text="Load")
    load_button.pack(side="left")

    show_pins_var = ctk.BooleanVar(value=True)
    ctk.CTkSwitch(
        controls, text="Show pins", variable=show_pins_var,
        command=lambda: render_cells()
    ).pack(side="left", padx=(12, 0))

    status_label = ctk.CTkLabel(
        parent, text="Choose a species and date range, then click Load.")
    status_label.pack(anchor="w", padx=10, pady=(0, 5))

    db_status_label = ctk.CTkLabel(parent, text="", text_color="gray")
    db_status_label.pack(anchor="w", padx=10, pady=(0, 5))

    map_widget = tkintermapview.TkinterMapView(parent, corner_radius=0)
    map_widget.pack(fill="both", expand=True, padx=10, pady=(0, 10))
    map_widget.set_position(52.1326, 5.2913)
    map_widget.set_zoom(7)

    # fetch_grid_data() drives a headless browser and can take 10-20s (page load + anti-bot check)  runs on a background thread

    result = {}
    last_state = {"cells": [], "site_label": None}

    def check_database(species_name):
        if not db_config.is_configured():
            result["db_status"] = (
                "No database selected (choose one in the Settings tab) "
                "to see sequences already on file for this species."
            )
            return

        try:
            conn = database.connect(db_config)
            counts = database.count_sequences_by_marker(conn, species_name)
            conn.close()
        except Exception as e:
            result["db_status"] = f"Database check failed: {e}"
            return

        if counts:
            parts = ", ".join(f"{marker}: {count}" for marker, count in counts)
            result["db_status"] = f"Sequences in database - {parts}"
        else:
            result["db_status"] = "No sequences in database for this species yet."

    def load_data(site_key, species_name, start_date, end_date):
        check_database(species_name)

        try:
            site = SITES[site_key]
            species_id = lookup_species_id(species_name, site["base_url"])
            cells = fetch_grid_data(
                site["base_url"], species_id, start_date, end_date, site["map_type"]
            )
            for cell in cells:
                cell["link"] = build_gridcell_url(
                    site["base_url"], cell["cell_id"], species_id,
                    start_date, end_date
                )
            result["cells"] = cells
            result["site_label"] = site_key
        except Exception as e:
            import traceback
            traceback.print_exc()
            result["error"] = str(e)

    def _show_cell_popup(cell, site_label):
        win = ctk.CTkToplevel(root or parent)
        win.title("Grid cell details")
        win.geometry("340x240")
        win.transient(root or parent)
        win.grab_set()

        ctk.CTkLabel(
            win, text=f"{cell['num_obs']} observation(s)",
            font=("Arial", 16, "bold")
        ).pack(padx=20, pady=(20, 2), anchor="w")

        ctk.CTkLabel(
            win, text=f"{cell['count']} record(s) in this cell",
            text_color="gray"
        ).pack(padx=20, anchor="w")

        ctk.CTkLabel(
            win, text=f"Location: {cell['lat']:.5f}, {cell['lon']:.5f}",
            text_color="gray"
        ).pack(padx=20, pady=(8, 0), anchor="w")

        ctk.CTkLabel(
            win, text=f"Cell ID: {cell['cell_id']}", text_color="gray"
        ).pack(padx=20, anchor="w")

        if cell.get("link"):
            ctk.CTkButton(
                win, text=f"Open this cell on {site_label}",
                command=lambda: webbrowser.open(cell["link"])
            ).pack(padx=20, pady=(18, 5), fill="x")

        ctk.CTkButton(win, text="Close", command=win.destroy).pack(pady=(0, 15))

    def render_cells():
        cells = last_state["cells"]
        site_label = last_state.get("site_label") or "the source site"

        map_widget.delete_all_marker()
        map_widget.delete_all_polygon()

        max_count = max((cell["num_obs"] for cell in cells), default=0)

        for cell in cells:
            if cell.get("polygon"):
                map_widget.set_polygon(
                    cell["polygon"],
                    fill_color=_color_for_count(cell["num_obs"], max_count),
                    outline_color="#333333",
                    border_width=1,
                )
            if show_pins_var.get():
                map_widget.set_marker(
                    cell["lat"], cell["lon"],
                    text=f"{cell['num_obs']}",
                    command=lambda _m, c=cell, label=site_label:
                        _show_cell_popup(c, label)
                )

    def poll():
        if "cells" in result:
            cells = result.pop("cells")
            last_state["cells"] = cells
            last_state["site_label"] = result.pop("site_label", None)

            status_label.configure(
                text=f"Loaded {len(cells)} grid cells.", text_color="white")
            db_status_label.configure(text=result.pop("db_status", ""))
            load_button.configure(state="normal", text="Load")

            render_cells()

            if cells:
                map_widget.fit_bounding_box(
                    (max(c["lat"] for c in cells), min(c["lon"]
                     for c in cells)),
                    (min(c["lat"] for c in cells), max(c["lon"] for c in cells)))
            return
        if "error" in result:
            error = result.pop("error")
            status_label.configure(
                text=f"Failed to load data: {error}", text_color="red")
            db_status_label.configure(text=result.pop("db_status", ""))
            load_button.configure(state="normal", text="Load")
            return
        parent.after(200, poll)

    def on_load_clicked():
        site_key = site_var.get()
        species_name = species_entry.get().strip()
        start_date = start_date_entry.get_date()
        end_date = end_date_entry.get_date()

        if not species_name:
            status_label.configure(
                text="Enter a species name", text_color="red")
            return
        if start_date >= end_date:
            status_label.configure(
                text="Start date must be before end date", text_color="red")
            return

        load_button.configure(state="disabled", text="Loading...")
        status_label.configure(
            text=f"Looking up '{species_name}' on {site_key}...",
            text_color="white"
        )
        db_status_label.configure(text="Checking database...")
        threading.Thread(
            target=load_data,
            args=(site_key, species_name, start_date, end_date),
            daemon=True
        ).start()
        parent.after(200, poll)

    load_button.configure(command=on_load_clicked)
