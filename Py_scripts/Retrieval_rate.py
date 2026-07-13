import tkinter
import customtkinter
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import pandas as pd


df_plot = pd.read_csv(r"B:\Stage\test\summary.csv")


def Plots(selected_plot):
    plot_options.configure()

    if selected_plot == "Barplot":
        ax.clear()
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

        fig.tight_layout()
        canvas.draw()

# GUI--------------------------------------------------------------------


customtkinter.set_appearance_mode("dark")
customtkinter.set_default_color_theme("dark-blue")

tk = customtkinter.CTk()

tk.title("plot")
tk.geometry("700x450")

plots = ["Barplot", "piechart", "Table"]

plot_options = customtkinter.CTkOptionMenu(tk, values=plots)
plot_options.pack(pady=40)

display_button = customtkinter.CTkButton(
    tk, text="Display", command=lambda: Plots(plot_options.get()))
display_button.pack(pady=10)

fig, ax = plt.subplots(figsize=(7, 3.6), dpi=100)
canvas = FigureCanvasTkAgg(fig, master=tk)
canvas.get_tk_widget().pack(fill=tkinter.BOTH, expand=True)


def on_closing():
    plt.close(fig)
    tk.quit()
    tk.destroy()


tk.protocol("WM_DELETE_WINDOW", on_closing)

tk.mainloop()
