import time
import threading
import os
import json
import re

import pandas as pd


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


# ENCODING-SAFE CSV READING-----------------------------------------

def read_csv_robust(path, **kwargs):
    try:
        return pd.read_csv(path, encoding="utf-8", **kwargs)
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp1252", **kwargs)


def fix_mojibake(text):
    """
    Reverses UTF-8 bytes that were already mis-decoded as cp1252/Latin-1
    before this app ever saw them (e.g. a name saved correctly as UTF-8 by
    one tool, then opened and re-saved by another tool that assumed
    cp1252) - the classic double-encoding signature, e.g. "×" (U+00D7)
    turning into "Ã—". read_csv_robust only fixes *this app's own* read of
    a file; this fixes names that were corrupted before the file was ever
    written.

    Round-trips through cp1252-encode / utf-8-decode and only applies the
    result if that succeeds - genuinely clean text (plain ASCII, or a
    correctly-decoded "×") fails the round trip immediately and is
    returned unchanged, since it won't coincidentally form valid UTF-8
    byte sequences.
    """
    if not isinstance(text, str) or not text:
        return text
    try:
        return text.encode("cp1252").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return text


# CHARACTER STRIPPING-----------------------------------------

def strip_characters(name, chars):
    """
    Removes every occurrence of any character in `chars` from name, then
    collapses whitespace left behind. `chars` is treated as a set of
    individual characters (like str.translate), not a literal substring -
    e.g. chars="×*?" strips each of those three characters independently
    wherever it appears, not the three-character sequence "×*?" as a whole.
    """
    if not chars:
        return name
    table = str.maketrans("", "", chars)
    return re.sub(r"\s+", " ", name.translate(table)).strip()


# FILENAME SANITIZING-----------------------------------------

INVALID_CHARS = '<>:"/\\|?*'


def sanitize(name):
    name = str(name).strip()
    for ch in INVALID_CHARS:
        name = name.replace(ch, "_")
    return name


# COUNTRY GROUPING-----------------------------------------
# Shared by both NCBI's and BOLD's scoring functions. Which locations count
# as the target country vs. a neighboring country is configurable in the
# Settings tab (saved with the scoring settings/presets, see gui.py's
# collect_current_settings/apply_settings) - the lists below are just the
# factory defaults, and set_country_groups() is how the Settings tab
# changes what's actually in effect.

DEFAULT_TARGET_COUNTRY_NAMES = ["belgium", "belgië", "belgique"]
DEFAULT_NEIGHBOR_COUNTRY_NAMES = [
    "netherlands", "nederland",
    "germany", "deutschland",
    "france", "frankrijk",
    "luxembourg", "luxemburg",
]

_target_country_names = list(DEFAULT_TARGET_COUNTRY_NAMES)
_neighbor_country_names = list(DEFAULT_NEIGHBOR_COUNTRY_NAMES)


def set_country_groups(target_names, neighbor_names):
    """
    Changes which location strings detect_country_group() below scores as
    "target"/"neighbor". Names are matched case-insensitively as substrings
    of a sequence's location field, so include every language/spelling
    variant that should count (e.g. a country's name in multiple
    languages).
    """
    global _target_country_names, _neighbor_country_names
    _target_country_names = [
        n.strip().lower() for n in target_names if n.strip()]
    _neighbor_country_names = [
        n.strip().lower() for n in neighbor_names if n.strip()]


def detect_country_group(location: str):
    location = (location or "").lower()

    if any(x in location for x in _target_country_names):
        return "target"

    if any(x in location for x in _neighbor_country_names):
        return "neighbor"

    if location:
        return "europe"

    return "unknown"


# PERSISTED SETTINGS-----------------------------------------


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


# SETTINGS PRESETS-----------------------------------------

PRESETS_PATH = os.path.join(CONFIG_DIR, "presets.json")


def load_presets():
    try:
        with open(PRESETS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_presets(presets):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(PRESETS_PATH, "w", encoding="utf-8") as f:
        json.dump(presets, f, indent=2)
