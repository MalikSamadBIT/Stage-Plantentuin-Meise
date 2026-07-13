import time
import threading


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
