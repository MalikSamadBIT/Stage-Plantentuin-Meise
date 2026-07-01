import customtkinter as ctk
from tkinter import filedialog
from Bio import Entrez, SeqIO
import pandas as pd
import time
import threading


# NCBI SETTINGS-------------------------------------------

Entrez.email = "samadmalikg@gmail.com"
Entrez.api_key = "a9543111711b0671e59f806f680529ff4607"

df = None
output_df = None


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


# SCORING-----------------------------------------------

def score_record(record, w, bad_words):
    score = 0
    title = record.description.lower()

    if any(b in title for b in bad_words):
        score -= w["bad_title_penalty"]

    if 300 <= len(record.seq) <= 1200:
        score += w["length_bonus"]

    source = None
    for f in record.features:
        if f.type == "source":
            source = f.qualifiers
            break

    if source:
        location = source.get("geo_loc_name", source.get("country", [""]))[0]
        group = detect_country_group(location)
        score += w.get(group, 0)

    return score


# FETCHIGN FROM NCBI------------------------------------

def get_accession(species, marker, sleep_time, w, bad_words):

    try:
        query = f'"{species}"[Organism] AND {marker}'
        print("Query:", query)

        handle = Entrez.esearch(db="nucleotide", term=query, retmax=10)
        rec = Entrez.read(handle)
        handle.close()

        if not rec["IdList"]:
            return (None,) * 9

        best = None
        best_score = -999

        for uid in rec["IdList"]:
            try:
                handle = Entrez.efetch(
                    db="nucleotide",
                    id=uid,
                    rettype="gb",
                    retmode="text"
                )

                gb = SeqIO.read(handle, "genbank")
                handle.close()

                sc = score_record(gb, w, bad_words)

                if sc > best_score:
                    best_score = sc
                    best = gb

            except Exception as e:
                print("efetch error:", e)
                continue

        if best is None:
            return (None,) * 9

        organism = best.annotations.get("organism")

        geo_loc = None
        lat_lon = None
        collection_date = None
        voucher = None

        for feature in best.features:
            if feature.type == "source":
                q = feature.qualifiers
                geo_loc = q.get("geo_loc_name", q.get("country", [None]))[0]
                lat_lon = q.get("lat_lon", [None])[0]
                collection_date = q.get("collection_date", [None])[0]
                voucher = q.get("specimen_voucher", [None])[0]
                break

        time.sleep(sleep_time)

        return (
            best.id,
            best.description,
            len(best.seq),
            organism,
            geo_loc,
            lat_lon,
            collection_date,
            voucher,
            best_score
        )

    except Exception as e:
        print(e)
        return (None,) * 9


# GUI SETUP---------------------------------------
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

app = ctk.CTk()
app.geometry("1250x820")
app.title("NCBI ID Scoring ")


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


def load():
    global df
    path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
    file_path.set(path)
    df = pd.read_csv(path)


ctk.CTkButton(scroll, text="Select CSV File",
              command=load).pack(fill="x", pady=5)
ctk.CTkLabel(scroll, textvariable=file_path).pack(anchor="w", pady=(0, 10))


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

sleep_entry = ctk.CTkEntry(scroll)
sleep_entry.insert(0, "0.35")
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
    text="Estimated remaining time: --"
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

    if df is None:
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

    for marker in markers:
        print("Processing", marker)

        rows = []

        for species in test["Name"]:

            rows.append(
                get_accession(
                    species,
                    marker,
                    sleep_time,
                    w,
                    bad_words
                )
            )

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
                    text=f"Estimated remaining: {m}m {s}s"
                )
            )

            # Update progress bar
            app.after(
                0,
                lambda p=completed/total_jobs: progress.set(p)
            )

            app.after(
                0,
                lambda c=completed:
                progress_label.configure(
                    text=f"{c}/{total_jobs} completed"
                )
            )

            app.after(
                0,
                lambda:
                    time_label.configure(
                        text=f"Estimated remaining: {mins}m {secs}s"
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

        progress.set(1)

        progress_label.configure(
            text="Finished!"
        )

        time_label.configure(
            text="Estimated remaining: 0s"
        )

    print(test)

    app.after(
        0,
        lambda: run_button.configure(state="normal")
    )

    app.after(
        0,
        lambda: status_label.configure(
            text="Finished!"
        )
    )

    app.after(
        0,
        lambda: progress.set(1)
    )

    app.after(
        0,
        lambda: time_label.configure(
            text="Estimated remaining: 0 s"
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
