import os
import sys

if getattr(sys, "frozen", False):
    # a frozen build bundles its own copy of the (headless-only) Chromium
    # build Playwright needs - see FloraFetch.spec - rather than relying on
    # %LOCALAPPDATA%\ms-playwright, which won't exist on a machine that
    # never separately ran "playwright install". setdefault so an
    # explicitly-set PLAYWRIGHT_BROWSERS_PATH (e.g. for testing) still wins.
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        os.path.join(sys._MEIPASS, "ms-playwright")
    )

import json
import re
from urllib.parse import quote_plus
from urllib.request import urlopen

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# Both sites run the same observation.org platform
SITES = {
    "Belgium (waarnemingen.be)": {
        "base_url": "https://waarnemingen.be",
        "map_type": "grid10k",
    },
    "World (observation.org)": {
        "base_url": "https://observation.org",
        "map_type": "grid25k",
    },
}


def lookup_species_id(name, base_url):
    # The /search/ page isn't behind the Anubis anti-bot check (unlike the/maps/endpoint), so a plain urlopen works here
    query_url = f"{base_url}/search/?q=" + quote_plus(name.strip())
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


def _cell_polygon(coordinates):
    # GeoJSON rings are [lon, lat] pairs - tkintermapview's set_polygon
    # wants (lat, lon), the same convention set_marker already uses here.
    ring = coordinates[0]
    return [(pt[1], pt[0]) for pt in ring]


# only accepts these preset lookback windows (day/week/month/6mo/1y/5y/10y),
INTERVAL_CHOICES = [86400, 604800, 2592000,
                    15552000, 31536000, 157680000, 315360000]


def _interval_for(start_date, end_date):
    requested = (end_date - start_date).days * 86400
    for choice in INTERVAL_CHOICES:
        if choice >= requested:
            return choice
    # cap at the largest available window (10 years)
    return INTERVAL_CHOICES[-1]


def _new_browser_page(p):
    # Anubis's anti-bot check flags a default headless launch outright (navigator.webdriver reveals it as automated) - masking that flag lets its JS challenge pass normally, same as any real browser.
    browser = p.chromium.launch(
        headless=True, args=["--disable-blink-features=AutomationControlled"]
    )
    context = browser.new_context(user_agent=USER_AGENT)
    page = context.new_page()
    page.add_init_script(
        "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
    )
    return browser, page


def build_species_map_url(base_url, species_id, start_date, end_date, map_type):
    # the page a human would land on for this species/date-range/grid as a
    # whole - use build_gridcell_url instead for a link to one specific cell
    interval = _interval_for(start_date, end_date)
    return (
        f"{base_url}/species/{species_id}/maps/"
        f"?start_date={start_date}&interval={interval}&end_date={end_date}&map_type={map_type}"
    )


def build_gridcell_url(base_url, cell_id, species_id, start_date, end_date):
    # a page dedicated to one grid cell's observations - not reachable by
    # clicking the cell on the map itself (that's AJAX-only, see
    # occurrence-map.js), but this URL works directly.
    return (
        f"{base_url}/locations/gridcell/{cell_id}/observations/"
        f"?date_after={start_date}&date_before={end_date}&species={species_id}"
    )


def _fetch_grid_features(page, base_url, species_id, start_date, end_date, map_type):
    map_url = build_species_map_url(
        base_url, species_id, start_date, end_date, map_type)
    json_url = map_url + "&json="

    # Visit the normal map page first so Anubis's JS challenge runs and sets the auth cookie
    page.goto(map_url, wait_until="networkidle")
    response = page.goto(json_url, wait_until="networkidle")
    text = response.text()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Non-JSON response from {base_url} (first 500 chars):\n{text[:500]}")

    if "errors" in data:
        raise RuntimeError(
            f"{base_url} rejected the request: {data['errors']}")

    return data.get("features", [])


def fetch_grid_data(base_url, species_id, start_date, end_date, map_type):
    # Returns a list of dicts: cell_id, lat, lon, count, num_obs, polygon
    # (the cell's actual grid-square boundary, as [(lat, lon), ...]).
    with sync_playwright() as p:
        browser, page = _new_browser_page(p)
        features = _fetch_grid_features(
            page, base_url, species_id, start_date, end_date, map_type)
        browser.close()

    results = []
    for feat in features:
        props = feat["properties"]
        coordinates = feat["geometry"]["coordinates"]
        lat, lon = _cell_centroid(coordinates)
        results.append(
            {
                "cell_id": props["cell"],
                "lat": lat,
                "lon": lon,
                "count": props["count"],
                "num_obs": props["num_obs"],
                "polygon": _cell_polygon(coordinates),
            }
        )
    return results


def _lookup_observation_count(page, base_url, name, start_date, end_date, map_type):
    try:
        species_id = lookup_species_id(name, base_url)
        features = _fetch_grid_features(
            page, base_url, species_id, start_date, end_date, map_type)
        return sum(feat["properties"]["num_obs"] for feat in features)
    except Exception:
        return None


def fetch_observation_counts_batch(
    base_url, species_names, start_date, end_date, map_type, progress=None,
    get_synonyms=None
):
    """
    Returns (results, resolved_via):
    - results: {species_name: total_observations}, with None for any
      species that couldn't be resolved/fetched under its own name or any
      synonym (name not found, network error).
    - resolved_via: {species_name: synonym_name} for species that only
      matched under a synonym, not their own name - lets callers surface
      which counts came from a fallback name instead of the one asked for.

    Reuses a single browser/page across every species instead of relaunching
    one per species like fetch_grid_data does - browser startup + the Anubis
    pass is the dominant cost otherwise, and needs to happen only once per
    batch run instead of once per species.

    progress: optional callable(completed, total, species_name), called
    after each species (found or not).
    get_synonyms: optional callable(species_name) -> list of alternate
    names to retry under if the exact name doesn't match on the site (e.g.
    database.get_synonym_names bound to the shared database connection) -
    the same "try known synonyms before giving up" the database-side
    sequence lookup already does via count_sequences_by_marker.
    """
    results = {}
    resolved_via = {}
    total = len(species_names)

    with sync_playwright() as p:
        browser, page = _new_browser_page(p)

        for i, name in enumerate(species_names):
            count = _lookup_observation_count(
                page, base_url, name, start_date, end_date, map_type)

            if count is None and get_synonyms is not None:
                for synonym in get_synonyms(name):
                    count = _lookup_observation_count(
                        page, base_url, synonym, start_date, end_date, map_type)
                    if count is not None:
                        resolved_via[name] = synonym
                        break

            results[name] = count

            if progress:
                progress(i + 1, total, name)

        browser.close()

    return results, resolved_via
