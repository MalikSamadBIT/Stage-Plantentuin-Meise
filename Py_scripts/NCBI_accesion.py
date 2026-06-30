import customtkinter as ctk
from tkinter import filedialog
from Bio import Entrez, SeqIO
import pandas as pd
import time

Entrez.email = "your_email@example.com"
Entrez.api_key = "YOUR_API_KEY"

df = None
output_df = None


# -----------------------------
# COUNTRY GROUPING
# -----------------------------
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


# -----------------------------
# SCORING
# -----------------------------
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


# -----------------------------
# FETCH
# -----------------------------
def get_accession(species, marker, sleep_time, w, bad_words):

    try:
        query = f'"{species}"[Organism] AND {marker}'

        handle = Entrez.esearch(db="nucleotide", term=query, retmax=10)
        rec = Entrez.read(handle)
        handle.close()

        if not rec["IdList"]:
            return (None,) * 4

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

            except:
                continue

        return best.id, best.description, len(best.seq), best_score

    except Exception as e:
        print(e)
        return (None,) * 4


# -----------------------------
# GUI
# -----------------------------
ctk.set_appearance_mode("dark")
app = ctk.CTk()
app.geometry("1150x780")
app.title("NCBI Scoring Engine")


# PANELS
left = ctk.CTkFrame(app)
left.pack(side="left", fill="both", expand=True, padx=10, pady=10)

right = ctk.CTkFrame(app)
right.pack(side="right", fill="y", padx=10, pady=10)


# -----------------------------
# FILE
# -----------------------------
file_path = ctk.StringVar()


def load():
    global df
    path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
    file_path.set(path)
    df = pd.read_csv(path)


ctk.CTkButton(left, text="Select CSV", command=load).pack()
ctk.CTkLabel(left, textvariable=file_path).pack()


# -----------------------------
# INPUT AREA (SIDE-BY-SIDE)
# -----------------------------
input_frame = ctk.CTkFrame(left)
input_frame.pack(pady=10, fill="x")

markers_frame = ctk.CTkFrame(input_frame)
markers_frame.pack(side="left", fill="both", expand=True, padx=5)

bad_frame = ctk.CTkFrame(input_frame)
bad_frame.pack(side="right", fill="both", expand=True, padx=5)


# -----------------------------
# MARKERS
# -----------------------------
ctk.CTkLabel(markers_frame, text="Markers").pack()

marker_vars = {}
for m in ["ITS", "ITS1", "ITS2", "rbcL", "matK", "trnL", "psbA-trnH"]:
    v = ctk.BooleanVar()
    marker_vars[m] = v
    ctk.CTkCheckBox(markers_frame, text=m, variable=v).pack(anchor="w")

extra_markers = ctk.CTkEntry(markers_frame)
extra_markers.pack()
extra_markers.insert(0, "extra markers")


# -----------------------------
# BAD WORDS (NOW NEXT TO MARKERS)
# -----------------------------
ctk.CTkLabel(bad_frame, text="Bad words").pack()

bad_words_default = {
    "whole genome": ctk.BooleanVar(value=True),
    "chromosome": ctk.BooleanVar(value=True),
    "scaffold": ctk.BooleanVar(value=True),
    "contig": ctk.BooleanVar(value=True),
    "assembly": ctk.BooleanVar(value=True),
}

for w, v in bad_words_default.items():
    ctk.CTkCheckBox(bad_frame, text=w, variable=v).pack(anchor="w")

extra_bad = ctk.CTkEntry(bad_frame)
extra_bad.pack()
extra_bad.insert(0, "extra bad words")


# -----------------------------
# OTHER INPUTS
# -----------------------------
sleep_entry = ctk.CTkEntry(left)
sleep_entry.insert(0, "0.35")
sleep_entry.pack(pady=5)


# -----------------------------
# SLIDERS (RIGHT SIDE)
# -----------------------------
ctk.CTkLabel(right, text="SCORING", font=("Arial", 18)).pack(pady=10)


def slider(label, default):

    frame = ctk.CTkFrame(right)
    frame.pack(pady=8)

    ctk.CTkLabel(frame, text=label).pack()

    val = ctk.CTkLabel(frame, text=str(default))
    val.pack()

    s = ctk.CTkSlider(frame, from_=0, to=100)
    s.set(default)

    def update(v):
        val.configure(text=str(int(float(v))))

    s.configure(command=update)
    s.pack()

    return s


belgium_s = slider("Belgium boost", 40)
neighbor_s = slider("Neighbor boost", 20)
europe_s = slider("Europe fallback", 5)
length_s = slider("Length bonus", 10)
bad_penalty_s = slider("Bad penalty", 100)


# -----------------------------
# RUN
# -----------------------------
def run():

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

    test = df.head(3).copy()

    for marker in markers:

        print("Processing", marker)

        results = test["Name"].apply(
            lambda s: get_accession(s, marker, sleep_time, w, bad_words)
        ).apply(pd.Series)

        results.columns = [
            f"{marker}_accession",
            f"{marker}_title",
            f"{marker}_length",
            f"{marker}_score"
        ]

        test = pd.concat([test, results], axis=1)

    output_df = test
    print(test)


ctk.CTkButton(left, text="RUN", command=run).pack(pady=10)


def save():
    global output_df
    if output_df is not None:
        path = filedialog.asksaveasfilename(defaultextension=".csv")
        output_df.to_csv(path, index=False)


ctk.CTkButton(left, text="SAVE", command=save).pack()


app.mainloop()
