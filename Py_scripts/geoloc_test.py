import customtkinter
import tkintermapview

tk = customtkinter.CTk()

tk.title("geoloc")
tk.geometry("760x520")

map_widget = tkintermapview.TkinterMapView(tk, width=760, height=480, corner_radius=0)
map_widget.pack(fill="both", expand=True)

# Netherlands (waarneming.nl data covers Dutch grid cells) - replace with real coords
map_widget.set_position(52.1326, 5.2913)
map_widget.set_zoom(7)

marker = map_widget.set_marker(52.1326, 5.2913, text="Max. individuen: 19\nWaarnemingen: 262")

tk.mainloop()
