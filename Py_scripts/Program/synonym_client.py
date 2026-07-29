import re

import requests
from bs4 import BeautifulSoup

# WAARNEMINGEN.BE SETTINGS-----------------------------------------

BASE_URL = "https://waarnemingen.be"
SEARCH_URL = f"{BASE_URL}/search/?q="

SPECIES_LINK_RE = re.compile(r"^/species/\d+/$")
NAME_CELL_RE = re.compile(r"col-sm-2 col-xs-5")
LANGUAGE_CELL_RE = re.compile(r"col-sm-3 col-xs-7")


# FETCHING + PARSING ONE SPECIES----------------------------------------

def fetch_synonyms(species, rate_limiter, log=print, timeout=15):
    """
    Looks up a species on waarnemingen.be and returns a dict of
    {language: synonym name}. Returns an empty dict if no species page
    (or no "other names" table) is found.
    """

    name_parts = species.split()
    if len(name_parts) < 2:
        log(f"Skipping {species!r}: not a binomial name")
        return {}

    genus, epithet = name_parts[0], name_parts[1]

    rate_limiter.wait()

    try:
        r = requests.get(SEARCH_URL + f"{genus}+{epithet}", timeout=timeout)
        r.raise_for_status()
    except requests.RequestException as e:
        log(f"waarnemingen.be search failed for {species!r}: {e}")
        return {}

    soup = BeautifulSoup(r.text, "html.parser")
    species_link = soup.find("a", {"href": SPECIES_LINK_RE})

    if not species_link:
        log(f"No waarnemingen.be species page found for {species!r}")
        return {}

    names_url = BASE_URL + species_link["href"] + "names/"

    rate_limiter.wait()

    try:
        r2 = requests.get(names_url, timeout=timeout)
        r2.raise_for_status()
    except requests.RequestException as e:
        log(f"waarnemingen.be names page failed for {species!r}: {e}")
        return {}

    soup2 = BeautifulSoup(r2.text, "html.parser")

    names = []
    for cell in soup2.find_all("div", class_=NAME_CELL_RE):
        strong = cell.find("strong")
        if strong:
            names.append(strong.get_text(strip=True))

    languages = [
        cell.get_text(strip=True)
        for cell in soup2.find_all("div", class_=LANGUAGE_CELL_RE)
    ]

    return dict(zip(languages, names))


# BATCH LOOKUP--------------------------------------------------------

def search_synonyms(species_list, rate_limiter, log=print, progress=None):
    """
    species_list: iterable of species names.
    progress: optional callback(completed, total, species) after each lookup.
    Returns {species: {language: synonym}}.
    """

    total = len(species_list)
    results = {}

    for i, species in enumerate(species_list, start=1):
        log(f"Looking up synonyms for {species}...")
        results[species] = fetch_synonyms(species, rate_limiter, log=log)

        if progress:
            progress(i, total, species)

    return results
