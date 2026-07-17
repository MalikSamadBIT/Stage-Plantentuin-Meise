import time
import threading
import os
import json
import re


# RATE LIMITER-----------------------------------------------
# Enforces a global minimum gap between requests

class RateLimiter:

    def __init__(self, min_interval):
        self.min_interval = min_interval
        self.lock = threading.Lock()
        self.last_call = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            sleep_for = self.min_interval - (now - self.last_call)

            if sleep_for > 0:
                time.sleep(sleep_for)

            self.last_call = time.time()


# HYBRID MARKER STRIPPING-----------------------------------------
# Botanical hybrid names are marked with a "×" multiplication sign
# (U+00D7), e.g. "Equisetum ×litorale" or "×Schedolium loliaceum" -
# stripping it is opt-in since GenBank/BOLD records don't consistently
# include it either way, so whether it helps or hurts matching depends
# on the dataset.

def strip_hybrid_marker(name):
    return re.sub(r"\s+", " ", name.replace("×", "")).strip()


# FILENAME SANITIZING-----------------------------------------

INVALID_CHARS = '<>:"/\\|?*'


def sanitize(name):
    name = str(name).strip()
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    return name


# COUNTRY GROUPING-----------------------------------------
# Shared by both NCBI's and BOLD's scoring functions.

def detect_country_group(location: str):
    location = (location or "").lower()

    if any(x in location for x in ["belgium", "belgië", "belgique"]):
        return "belgium"

    if any(x in location for x in [
        "netherlands", "nederland",
        "germany", "deutschland",
        "france", "frankrijk",
        "luxembourg", "luxemburg"
    ]):
        return "neighbor"

    if location:
        return "europe"

    return "unknown"


# PERSISTED SETTINGS-----------------------------------------
# Stored under the user's profile (not next to the script) so settings
# survive moving/reinstalling the program folder. Plain text - fine for
# an NCBI API key (it only raises a rate limit, it isn't a login
# credential), but don't put anything more sensitive in here.

CONFIG_DIR = os.path.join(
    os.getenv("APPDATA") or os.path.expanduser("~"), "NCBI_BOLD_Pipeline"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_config(config):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
