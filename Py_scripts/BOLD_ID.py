import customtkinter as ctk
from tkinter import filedialog
import requests
import json
import pandas as pd
import time
import threading


# BOLD API SETTINGS-----------------------------------------

BOLD_BASE = "https://portal.boldsystems.org/api"

df = None
output_df = None


# HTTP WITH RETRY / BACKOFF-----------------------------------

class BoldBlockedError(Exception):
    """Raised when BOLD keeps refusing requests (e.g. Cloudflare block)."""
    pass


def bold_request(url, params, max_retries=4, timeout=30):

    delay = 5

    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=timeout)
        except requests.RequestException as e:
            print("BOLD network error:", e)
            time.sleep(delay)
            delay *= 2
            continue

        if r.status_code == 200:
            return r

        if r.status_code in (403, 429) or r.status_code >= 500:
            print(
                f"BOLD returned {r.status_code}, "
                f"retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
            )
            time.sleep(delay)
            delay *= 2
            continue

        r.raise_for_status()

    raise BoldBlockedError(
        f"BOLD kept refusing requests after {max_retries} attempts "
        "(likely rate-limited/blocked). Stopping run."
    )


# COUNTRY GROUPING-----------------------------------------

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


# MARKER MATCHING---------------------------------------------

def marker_matches(record_marker, wanted_marker):
    if not record_marker or not wanted_marker:
        return False

    def norm(s):
        return sorted(p for p in s.strip().lower().replace(" ", "").split("-") if p)

    return norm(record_marker) == norm(wanted_marker)


# SCORING-----------------------------------------------

def score_record(record, w, bad_words):

    raw = 0

    title = " ".join(filter(None, [
        record.get("identification"),
        record.get("notes"),
        record.get("short_note")
    ])).lower()

    # 1.TITLE FILTER

    if any(b in title for b in bad_words):
        raw -= 100

    # 2.LENGTH

    length = record.get("nuc_basecount") or 0

    if 300 <= length <= 1200:
        length_score = 30
    elif 200 <= length < 300 or 1200 < length <= 2000:
        length_score = 15
    else:
        length_score = 0

    # 3.LOCATION

    location = (record.get("country/ocean") or "").lower()

    group = detect_country_group(location)
    location_score = w.get(group, 0)

    # 4 NORMALISE score

    max_location = max(w.values()) if w else 40

    location_norm = (location_score / max_location) * 40
    length_norm = length_score
    penalty_norm = max(0, 30 - abs(raw) / 5)

    final_score = location_norm + length_norm + penalty_norm

    return round(final_score, 2)


# FETCHING FROM BOLD------------------------------------

def fetch_bold_records(species):

    try:
        pre = bold_request(
            f"{BOLD_BASE}/query/preprocessor",
            {"query": f"tax:{species}"}
        )

        terms = pre.json().get("successful_terms", [])
        matched = [
            t["matched"] for t in terms
            if t.get("matched", "").startswith("tax:")
        ]

        if not matched:
            return []

        q = bold_request(
            f"{BOLD_BASE}/query",
            {"query": ";".join(matched), "extent": "full"}
        )

        query_id = q.json().get("query_id")

        if not query_id:
            return []

        dl = bold_request(
            f"{BOLD_BASE}/documents/{query_id}/download",
            {"format": "json"}
        )

        records = []
        for line in dl.text.splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))

        return records

    except BoldBlockedError:
        raise

    except Exception as e:
        print("BOLD query error:", e)
        return []


def get_accession(species, marker, sleep_time, w, bad_words, cache):

    try:
        if species not in cache:
            cache[species] = fetch_bold_records(species)
            time.sleep(sleep_time)

        records = [
            r for r in cache[species]
            if marker_matches(r.get("marker_code"), marker)
        ]

        if not records:
            return (None,) * 9

        best = None
        best_score = -999

        for r in records:
            sc = score_record(r, w, bad_words)

            if sc > best_score:
                best_score = sc
                best = r

        if best is None:
            return (None,) * 9

        coord = best.get("coord")
        lat_lon = (
            f"{coord[0]},{coord[1]}"
            if isinstance(coord, list) and len(coord) == 2
            else None
        )

        voucher = best.get("museumid") or best.get("sampleid")

        return (
            best.get("processid"),
            best.get("identification"),
            best.get("nuc_basecount"),
            best.get("species"),
            best.get("country/ocean"),
            lat_lon,
            best.get("collection_date_start"),
            voucher,
            best_score
        )

    except BoldBlockedError:
        raise

    except Exception as e:
        print(e)
        return (None,) * 9


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("BOLD ID Scoring ")


# LEFT PANEL--------------------------------------------------------

left_container = ctk.CTkFrame(app)
left_container.pack(side="left", fill="both", expand=True, padx=10, pady=10)

scroll = ctk.CTkScrollableFrame(left_container)
scroll.pack(fill="both", expand=True)


# RIGHT PANEL (scoring)----------------------------------------------

right = ctk.CTkFrame(app, width=320)
right.pack(side="right", fill="y", padx=10, pady=10)


# FILE SECTION----------------------------------------------------------

ctk.CTkLabel(scroll, text="📁 FILE INPUT", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(5, 2))

file_path = ctk.StringVar()
output_path = ctk.StringVar()


def load():
    global df
    path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
    file_path.set(path)
    df = pd.read_csv(path)


def choose_output():
    path = filedialog.asksaveasfilename(
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv")]
    )
    output_path.set(path)


ctk.CTkButton(scroll, text="Select CSV File",
              command=load).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=file_path).pack(anchor="w", pady=(0, 10))

ctk.CTkButton(scroll, text="Select Output File",
              command=choose_output).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=output_path).pack(anchor="w", pady=(0, 10))


# MARKERS + BAD WORDS-----------------------------------------------------------------

input_frame = ctk.CTkFrame(scroll)
input_frame.pack(fill="x", pady=10)

markers_frame = ctk.CTkFrame(input_frame)
markers_frame.pack(side="left", fill="both", expand=True, padx=5, pady=5)

bad_frame = ctk.CTkFrame(input_frame)
bad_frame.pack(side="right", fill="both", expand=True, padx=5, pady=5)


# MARKERS
ctk.CTkLabel(markers_frame, text="Markers", font=(
    "Arial", 14, "bold")).pack(anchor="w")

marker_vars = {}
for m in ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]:
    v = ctk.BooleanVar()
    marker_vars[m] = v
    ctk.CTkCheckBox(markers_frame, text=m, variable=v).pack(anchor="w")

ctk.CTkLabel(markers_frame, text="Extra markers (comma separated)").pack(
    anchor="w", pady=(10, 0))
extra_markers = ctk.CTkEntry(markers_frame)
extra_markers.pack(fill="x", pady=5)


# BAD WORDS
ctk.CTkLabel(bad_frame, text="Filters", font=(
    "Arial", 14, "bold")).pack(anchor="w")

bad_words_default = {
    "whole genome": ctk.BooleanVar(value=True),
    "chromosome": ctk.BooleanVar(value=True),
    "scaffold": ctk.BooleanVar(value=True),
    "contig": ctk.BooleanVar(value=True),
    "assembly": ctk.BooleanVar(value=True),
}

for w, v in bad_words_default.items():
    ctk.CTkCheckBox(bad_frame, text=w, variable=v).pack(anchor="w")

ctk.CTkLabel(bad_frame, text="Extra bad words").pack(anchor="w", pady=(10, 0))
extra_bad = ctk.CTkEntry(bad_frame)
extra_bad.pack(fill="x", pady=5)


# SETTINGS-----------------------------------------------------------------------------

ctk.CTkLabel(scroll, text="⚙ SETTINGS", font=(
    "Arial", 16, "bold")).pack(anchor="w", pady=(10, 5))

ctk.CTkLabel(
    scroll,
    text="Min. interval between BOLD requests per species (s)"
).pack(anchor="w")
sleep_entry = ctk.CTkEntry(scroll)
sleep_entry.insert(0, "1.0")
sleep_entry.pack(fill="x", pady=5)


# SCORING SLIDERS----------------------------------------------------------------------------

ctk.CTkLabel(right, text="📊 SCORING", font=("Arial", 18, "bold")).pack(pady=10)


def slider(label, default):
    frame = ctk.CTkFrame(right)
    frame.pack(fill="x", pady=8, padx=10)

    ctk.CTkLabel(frame, text=label).pack(anchor="w")

    value = ctk.CTkLabel(frame, text=str(default))
    value.pack(anchor="w")

    s = ctk.CTkSlider(frame, from_=0, to=100)
    s.set(default)

    def update(v):
        value.configure(text=str(int(float(v))))

    s.configure(command=update)
    s.pack(fill="x")

    return s


belgium_s = slider("Belgium boost", 40)
neighbor_s = slider("Neighbor boost", 20)
europe_s = slider("Europe fallback", 5)
length_s = slider("Length bonus", 10)
bad_penalty_s = slider("Bad penalty", 100)


# PROGRESS BAR-------------------------------------------------------------------------------
status_label = ctk.CTkLabel(
    scroll,
    text="Idle"
)
status_label.pack(fill="x", pady=(15, 5))

progress_label = ctk.CTkLabel(
    scroll,
    text="Ready"
)
progress_label.pack(fill="x", pady=(15, 5))

time_label = ctk.CTkLabel(
    scroll,
    text="Estimated time per sample: --"
)
time_label.pack(fill="x")

progress = ctk.CTkProgressBar(scroll)
progress.pack(fill="x", pady=10)

progress.set(0)
# RUN AND SAVE----------------------------------------------------------------------------------


def run_search():

    app.after(
        0,
        lambda: run_button.configure(state="disabled")
    )

    app.after(
        0,
        lambda: status_label.configure(
            text="Searching..."
        )
    )

    global df, output_df

    if df is None or not output_path.get():
        app.after(
            0,
            lambda: status_label.configure(
                text="Select an input and output file first!"
            )
        )
        app.after(
            0,
            lambda: run_button.configure(state="normal")
        )
        return

    markers = [m for m, v in marker_vars.items() if v.get()]
    markers += [m.strip() for m in extra_markers.get().split(",") if m.strip()]
    markers = list(dict.fromkeys(markers))

    bad_words = [w for w, v in bad_words_default.items() if v.get()]
    bad_words += [w.strip() for w in extra_bad.get().split(",") if w.strip()]
    bad_words = [w.lower() for w in bad_words if w]

    w = {
        "belgium": belgium_s.get(),
        "neighbor": neighbor_s.get(),
        "europe": europe_s.get(),
        "unknown": 0,
        "length_bonus": length_s.get(),
        "bad_title_penalty": bad_penalty_s.get()
    }

    sleep_time = float(sleep_entry.get())

    test = df.copy()

    total_jobs = len(test) * len(markers)
    completed = 0

    start_time = time.time()

    cache = {}
    blocked = False

    for marker in markers:
        print("Processing", marker)

        rows = []

        for species in test["Name"]:

            try:
                rows.append(
                    get_accession(
                        species,
                        marker,
                        sleep_time,
                        w,
                        bad_words,
                        cache
                    )
                )
            except BoldBlockedError as e:
                print(e)
                blocked = True
                # pad the rest of this marker's rows so columns stay aligned
                rows += [(None,) * 9] * (len(test) - len(rows))
                break

            completed += 1

            elapsed = time.time() - start_time

            avg_time = elapsed / completed

            remaining = avg_time * (total_jobs - completed)

            mins = int(remaining // 60)
            secs = int(remaining % 60)

            app.after(
                0,
                lambda p=completed / total_jobs: progress.set(p)
            )

            app.after(
                0,
                lambda c=completed: progress_label.configure(
                    text=f"{c}/{total_jobs} completed"
                )
            )

            app.after(
                0,
                lambda m=mins, s=secs: time_label.configure(
                    text=f"Estimated time per sample: {m}m {s}s"
                )
            )

        results = pd.DataFrame(rows)

        results.columns = [
            f"{marker}_accession",
            f"{marker}_title",
            f"{marker}_length",
            f"{marker}_organism",
            f"{marker}_geo_loc",
            f"{marker}_lat_lon",
            f"{marker}_collection_date",
            f"{marker}_voucher",
            f"{marker}_score"
        ]

        test = pd.concat([test, results], axis=1)

        output_df = test

        time_label.configure(
            text="Estimated time per sample: 0s"
        )

        if blocked:
            break

    print(test)

    if output_df is not None:
        output_df.to_csv(output_path.get(), index=False)

    app.after(
        0,
        lambda: run_button.configure(state="normal")
    )

    if blocked:
        app.after(
            0,
            lambda: status_label.configure(
                text="BOLD blocked the requests - stopped early. "
                     "Partial results saved. Try again later with a "
                     "longer request interval."
            )
        )
    else:
        app.after(
            0,
            lambda: status_label.configure(text="Finished! Saved to output file.")
        )
        app.after(
            0,
            lambda: progress.set(1)
        )
        app.after(
            0,
            lambda: time_label.configure(
                text="Estimated time per sample: 0s"
            )
        )


def save():
    global output_df
    if output_df is not None:
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        output_df.to_csv(path, index=False)


def start_run():

    thread = threading.Thread(
        target=run_search,
        daemon=True
    )

    thread.start()


run_button = ctk.CTkButton(
    scroll,
    text="▶ RUN ANALYSIS",
    command=start_run
)

run_button.pack(fill="x", pady=10)
ctk.CTkButton(scroll, text="💾 SAVE CSV", command=save).pack(fill="x", pady=5)


app.mainloop()
