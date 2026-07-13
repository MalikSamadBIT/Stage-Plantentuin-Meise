import matplotlib.pyplot as plt
import pandas as pd


df_plot = pd.read_csv(r"B:\Stage\test\summary.csv")

fix, ax = plt.subplots()

markers = ["ITS1_count",  "ITS2_count",  "rbcL_count",
           "matK_count",  "trnL_count",  "psbA-trnH_count"]

counts = []

for marker in markers:
    m = df_plot[marker].sum()
    counts.append(m)

bar_colors = ['red', 'blue', 'green',
              'orange', 'yellow', 'cyan']

ax.bar(markers, counts, color=bar_colors)

ax.set_ylabel("Nr of FASTA sequences")
ax.set_title("FASTA Retrieval Rate")

for index, value in enumerate(counts):
    ax.text(index, value, str(value), ha="center", va="bottom")

plt.show()
