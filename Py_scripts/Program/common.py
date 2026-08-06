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
# pandas.read_csv() without an explicit encoding falls back to the OS
# locale's default (cp1252 on most Windows setups), which silently
# mojibakes any non-ASCII character - accented names, the hybrid × marker,
# etc. - in a file that was actually saved as UTF-8, the standard/default
# export encoding from Excel, Google Sheets, and most database/GIS tools.
# Tries UTF-8 first and only falls back to cp1252 if the file genuinely
# isn't UTF-8, rather than guessing wrong by default.

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
# General-purpose: species lists sometimes carry characters GenBank/BOLD
# records don't consistently match on - botanical hybrid names use a "×"
# multiplication sign (U+00D7), e.g. "Equisetum ×litorale" or "×Schedolium
# loliaceum", but messy CSV data can have other stray symbols too.
# Stripping is opt-in and user-specified rather than hardcoded to "×",
# since whether (and what) to strip depends on the dataset.

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
