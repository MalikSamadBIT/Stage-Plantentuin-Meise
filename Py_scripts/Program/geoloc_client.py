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

# Both sites run the same observation.org platform: species search + the
# grid-map JSON endpoint work identically, just against a different base URL
# and (Belgium being much smaller) a finer grid size.
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
    # The /search/ page isn't behind the Anubis anti-bot check (unlike the
    # /maps/ endpoint), so a plain urlopen works here - same approach as
    # synonym_client.py uses to resolve a species name to its numeric ID.
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


# The site's "interval" parameter isn't an arbitrary number of seconds - it
# only accepts these preset lookback windows (day/week/month/6mo/1y/5y/10y),
# same as the dropdown on the map page itself. Anything else is rejected
# with a validation error and an empty (but still 200 OK, valid-JSON) response.
INTERVAL_CHOICES = [86400, 604800, 2592000, 15552000, 31536000, 157680000, 315360000]


def _interval_for(start_date, end_date):
    requested = (end_date - start_date).days * 86400
    for choice in INTERVAL_CHOICES:
        if choice >= requested:
            return choice
    return INTERVAL_CHOICES[-1]  # cap at the largest available window (10 years)


def fetch_grid_data(base_url, species_id, start_date, end_date, map_type):
    # Returns a list of dicts: cell_id, lat, lon, count, num_obs.
    interval = _interval_for(start_date, end_date)
    map_url = (
        f"{base_url}/species/{species_id}/maps/"
        f"?start_date={start_date}&interval={interval}&end_date={end_date}&map_type={map_type}"
    )
    json_url = map_url + "&json="

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True, args=["--disable-blink-features=AutomationControlled"]
        )
        context = browser.new_context(user_agent=USER_AGENT)
        page = context.new_page()
        page.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        # Visit the normal map page first so Anubis's JS challenge runs and
        # sets the auth cookie; then the JSON URL request reuses that cookie.
        page.goto(map_url, wait_until="networkidle")
        response = page.goto(json_url, wait_until="networkidle")
        text = response.text()
        browser.close()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(
            f"Non-JSON response from {base_url} (first 500 chars):\n{text[:500]}")

    if "errors" in data:
        raise RuntimeError(f"{base_url} rejected the request: {data['errors']}")

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
