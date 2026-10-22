"""
main.py
=======
Hospital Database Management and Analytics System - desktop GUI.

Run with:   python main.py

This file contains ALL the user-interface code:
  * Styling (colours, fonts, ttk styles)
  * ManagementPage  - ONE reusable class that builds the search/filter bar, table, form and buttons
                      for every table (hospitals, departments, doctors, beds, equipment, admissions)
  * DashboardPage   - summary cards, recent admissions and chart previews
  * AnalyticsPage   - Pandas summaries + Matplotlib charts embedded in the window, CSV/PNG export
  * HospitalApp     - the main window with the sidebar and the status bar

All database work is done by functions in database.py - this file never writes SQL.
"""

import os
import textwrap
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

import matplotlib

matplotlib.use("TkAgg")  # draw Matplotlib figures inside Tkinter windows
import pandas as pd
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import database as db

# ---------------------------------------------------------------------------
# Colours and fonts (kept in one place so the whole app looks consistent)
# ---------------------------------------------------------------------------
COLORS = {
    "sidebar": "#12263A", "sidebar_hover": "#1D3B57", "accent": "#1F7A8C", "accent_dark": "#175F6D",
    "bg": "#F4F7FA", "card": "#FFFFFF", "border": "#DCE3EA", "text": "#1B2733", "muted": "#6B7C8C",
    "danger": "#C0392B", "danger_dark": "#962D22", "success": "#2E8B57", "warning": "#E0A100",
}
STATUS_COLORS = {"Available": "#2E8B57", "Occupied": "#C0392B", "Maintenance": "#E0A100"}
SERIES_COLORS = ["#1F7A8C", "#E07A5F", "#81B29A", "#F2CC8F", "#3D405B", "#9B5DE5", "#2A9D8F", "#B56576"]
FONT = "Segoe UI"
FORM_COLUMNS = 4  # number of columns in the data-entry form


def setup_styles(root):
    """Configure ttk widgets once; every page then reuses these named styles."""
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", font=(FONT, 10), background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Page.TFrame", background=COLORS["bg"])
    style.configure("Card.TFrame", background=COLORS["card"])
    style.configure("Title.TLabel", font=(FONT, 18, "bold"), background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Sub.TLabel", font=(FONT, 9), background=COLORS["bg"], foreground=COLORS["muted"])
    style.configure("Field.TLabel", font=(FONT, 9, "bold"), background=COLORS["card"], foreground=COLORS["muted"])
    style.configure("Bar.TLabel", background=COLORS["bg"], foreground=COLORS["text"])
    style.configure("Card.TLabelframe", background=COLORS["card"], bordercolor=COLORS["border"])
    style.configure("Card.TLabelframe.Label", font=(FONT, 10, "bold"), background=COLORS["card"],
                    foreground=COLORS["accent"])
    for name, normal, hover in (("TButton", "#E8EDF2", "#D5DEE7"),
                                ("Accent.TButton", COLORS["accent"], COLORS["accent_dark"]),
                                ("Danger.TButton", COLORS["danger"], COLORS["danger_dark"])):
        light = name == "TButton"
        style.configure(name, font=(FONT, 10, "bold"), padding=(14, 6), borderwidth=0, background=normal,
                        foreground=COLORS["text"] if light else "white")
        style.map(name, background=[("active", hover)])
    style.configure("Nav.TButton", font=(FONT, 11), anchor="w", padding=(20, 11), background=COLORS["sidebar"],
                    foreground="#C9D6E2", borderwidth=0)
    style.map("Nav.TButton", background=[("active", COLORS["sidebar_hover"])], foreground=[("active", "white")])
    style.configure("NavActive.TButton", font=(FONT, 11, "bold"), anchor="w", padding=(20, 11),
                    background=COLORS["accent"], foreground="white", borderwidth=0)
    style.map("NavActive.TButton", background=[("active", COLORS["accent"])])
    style.configure("Treeview", rowheight=26, font=(FONT, 10), background="white", fieldbackground="white",
                    bordercolor=COLORS["border"])
    style.configure("Treeview.Heading", font=(FONT, 10, "bold"), background="#E3EAF1", foreground=COLORS["text"],
                    padding=(6, 5))
    style.map("Treeview", background=[("selected", COLORS["accent"])], foreground=[("selected", "white")])
    style.configure("TNotebook", background=COLORS["bg"])
    style.configure("TNotebook.Tab", font=(FONT, 10, "bold"), padding=(18, 7))


# ---------------------------------------------------------------------------
# Small reusable widgets
# ---------------------------------------------------------------------------
class ScrollableFrame(ttk.Frame):
    """A frame with a vertical scrollbar (used by the dashboard so it works on small screens)."""

    def __init__(self, parent):
        super().__init__(parent, style="Page.TFrame")
        self.canvas = tk.Canvas(self, highlightthickness=0, bg=COLORS["bg"])
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, style="Page.TFrame")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bind_all("<MouseWheel>", self._on_wheel, add="+")
        self.bind_all("<Button-4>", self._on_wheel, add="+")
        self.bind_all("<Button-5>", self._on_wheel, add="+")

    def _on_wheel(self, event):
        """Scroll only when the mouse pointer is over this frame."""
        widget = self.winfo_containing(event.x_root, event.y_root)
        if widget is None or not str(widget).startswith(str(self)):
            return
        if event.num == 4:
            step = -1
        elif event.num == 5:
            step = 1
        else:
            step = -1 if event.delta > 0 else 1
        self.canvas.yview_scroll(step, "units")


class Field:
    """Describes one input of a form.
    kind: 'text' (typed), 'combo' (fixed list in `values`) or 'choice' (list loaded from the database
    by `options(values, record_id)`, returning [(id, label), ...])."""

    def __init__(self, key, label, kind="text", values=None, options=None, required=True, default=""):
        self.key, self.label, self.kind = key, label, kind
        self.values, self.options, self.required, self.default = values or [], options, required, default


class FilterSpec:
    """Describes one filter control above a table.
    kind: 'choice' ([(id, label)] from `options(current_filters)`), 'values' (list of strings) or 'entry'."""

    def __init__(self, key, label, kind="choice", options=None):
        self.key, self.label, self.kind, self.options = key, label, kind, options


def format_cell(value):
    """Convert a database value to text for a table cell."""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


# ---------------------------------------------------------------------------
# Generic management page (used for all six tables)
# ---------------------------------------------------------------------------
class ManagementPage(ttk.Frame):
    """One class builds every CRUD screen. Each screen is described by data:
    its table columns, form fields, filters and the database functions to call."""

    def __init__(self, parent, app, title, record_name, id_key, columns, fields, filters, list_func, get_func,
                 add_func, update_func, delete_func, export_name, search_hint, tag_key=None, tag_colors=None):
        super().__init__(parent, style="Page.TFrame")
        self.app, self.title, self.record_name, self.id_key = app, title, record_name, id_key
        self.columns, self.fields, self.filters = columns, fields, filters
        self.list_func, self.get_func, self.add_func = list_func, get_func, add_func
        self.update_func, self.delete_func, self.export_name = update_func, delete_func, export_name
        self.tag_key, self.tag_colors = tag_key, tag_colors or {}
        self.rows = []
        self.selected_id = None
        self.form_vars, self.form_widgets, self.form_options = {}, {}, {}
        self.filter_vars, self.filter_widgets, self.filter_choices = {}, {}, {}

        # ----- header -----
        header = ttk.Frame(self, style="Page.TFrame")
        header.pack(side="top", fill="x", padx=16, pady=(12, 2))
        ttk.Label(header, text=title, style="Title.TLabel").pack(side="left")
        self.count_label = ttk.Label(header, text="", style="Sub.TLabel")
        self.count_label.pack(side="left", padx=14, pady=(8, 0))

        # ----- search + filter bar -----
        bar = ttk.Frame(self, style="Page.TFrame")
        bar.pack(side="top", fill="x", padx=16, pady=6)
        # Controls are laid out in a grid that wraps after 5 items, so long filter lists never run off-screen.
        per_row = 5
        ttk.Label(bar, text=search_hint, style="Bar.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self.search_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.search_var, width=24).grid(row=1, column=0, sticky="w", padx=(0, 10))
        for position, spec in enumerate(filters, start=1):
            grid_row, grid_col = (position // per_row) * 2, position % per_row
            ttk.Label(bar, text=spec.label, style="Bar.TLabel").grid(
                row=grid_row, column=grid_col, sticky="w", padx=(0, 4), pady=(4 if grid_row else 0, 0))
            var = tk.StringVar(value="" if spec.kind == "entry" else "All")
            self.filter_vars[spec.key] = var
            if spec.kind == "entry":
                widget = ttk.Entry(bar, textvariable=var, width=14)
                widget.bind("<KeyRelease>", lambda event: self.reload_table())
            else:
                widget = ttk.Combobox(bar, textvariable=var, state="readonly", width=19)
                widget.bind("<<ComboboxSelected>>", lambda event: self.on_filter_changed())
            widget.grid(row=grid_row + 1, column=grid_col, sticky="w", padx=(0, 10))
            self.filter_widgets[spec.key] = widget
        last = len(filters) + 1  # position of the "Clear Filters" button
        ttk.Button(bar, text="Clear Filters", command=self.clear_filters).grid(
            row=(last // per_row) * 2 + 1, column=last % per_row, sticky="w")
        self.search_var.trace_add("write", lambda *args: self.reload_table())

        # ----- buttons (packed first so they stay at the very bottom) -----
        buttons = ttk.Frame(self, style="Page.TFrame")
        buttons.pack(side="bottom", fill="x", padx=16, pady=(0, 10))
        ttk.Button(buttons, text=f"Add {record_name}", style="Accent.TButton", command=self.add_record).pack(side="left")
        ttk.Button(buttons, text="Update Selected", style="Accent.TButton", command=self.update_record).pack(
            side="left", padx=6)
        ttk.Button(buttons, text="Delete Selected", style="Danger.TButton", command=self.delete_record).pack(side="left")
        ttk.Button(buttons, text="Clear Form", command=self.clear_form).pack(side="left", padx=6)
        ttk.Button(buttons, text="Export Table to CSV", command=self.export_csv).pack(side="right")

        # ----- data-entry form -----
        form = ttk.LabelFrame(self, text=f"{record_name} details  (select a row in the table to edit it)",
                              style="Card.TLabelframe", padding=8)
        form.pack(side="bottom", fill="x", padx=16, pady=(4, 8))
        for index, field in enumerate(fields):
            row, column = divmod(index, FORM_COLUMNS)
            cell = ttk.Frame(form, style="Card.TFrame")
            cell.grid(row=row, column=column, sticky="ew", padx=6, pady=3)
            ttk.Label(cell, text=field.label + (" *" if field.required else ""), style="Field.TLabel").pack(anchor="w")
            var = tk.StringVar()
            if field.kind in ("combo", "choice"):
                widget = ttk.Combobox(cell, textvariable=var, state="readonly", width=26)
                if field.kind == "combo":
                    widget["values"] = field.values
                widget.bind("<<ComboboxSelected>>", lambda event, key=field.key: self.on_choice_selected(key))
            else:
                widget = ttk.Entry(cell, textvariable=var, width=28)
            widget.pack(fill="x")
            self.form_vars[field.key], self.form_widgets[field.key] = var, widget
        for column in range(FORM_COLUMNS):
            form.columnconfigure(column, weight=1, uniform="formcol")

        # ----- table with scrollbars (fills the remaining space) -----
        table_frame = ttk.Frame(self)
        table_frame.pack(side="top", fill="both", expand=True, padx=16, pady=4)
        self.tree = ttk.Treeview(table_frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for key, heading, width, anchor in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor=anchor, stretch=True)
        vbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        hbar = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_row_selected)
        for tag_value, color in self.tag_colors.items():
            self.tree.tag_configure(tag_value, background=color)

        self.clear_form()

    # ----- filters -----------------------------------------------------------
    def get_filter_value(self, key):
        """Return the value to give the database query (None means 'no filter')."""
        spec = next(f for f in self.filters if f.key == key)
        text = self.filter_vars[key].get().strip()
        if spec.kind == "entry":
            return text or None
        if text in ("", "All"):
            return None
        if spec.kind == "choice":
            return self.filter_choices.get(key, {}).get(text)
        return text

    def reload_filter_options(self):
        """Refill the filter dropdowns from the database (keeps the current selection if still valid)."""
        current = {f.key: self.get_filter_value(f.key) for f in self.filters}
        for spec in self.filters:
            if spec.kind == "entry":
                continue
            try:
                raw = spec.options(current)
            except db.DatabaseError as error:
                messagebox.showerror("Database error", str(error), parent=self)
                raw = []
            if spec.kind == "choice":
                self.filter_choices[spec.key] = {label: ident for ident, label in raw}
                labels = [label for _, label in raw]
            else:
                labels = list(raw)
            self.filter_widgets[spec.key]["values"] = ["All"] + labels
            if self.filter_vars[spec.key].get() not in ["All"] + labels:
                self.filter_vars[spec.key].set("All")
            current[spec.key] = self.get_filter_value(spec.key)

    def on_filter_changed(self):
        self.reload_filter_options()  # e.g. the department list depends on the chosen hospital
        self.reload_table()

    def clear_filters(self):
        self.search_var.set("")
        for spec in self.filters:
            self.filter_vars[spec.key].set("" if spec.kind == "entry" else "All")
        self.reload_filter_options()
        self.reload_table()

    # ----- table -------------------------------------------------------------
    def reload_table(self):
        kwargs = {spec.key: self.get_filter_value(spec.key) for spec in self.filters}
        try:
            self.rows = self.list_func(search=self.search_var.get(), **kwargs)
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            self.rows = []
        self.tree.delete(*self.tree.get_children())
        for row in self.rows:
            tags = ()
            if self.tag_key and row.get(self.tag_key) in self.tag_colors:
                tags = (row[self.tag_key],)
            self.tree.insert("", "end", iid=str(row[self.id_key]),
                             values=[format_cell(row[c[0]]) for c in self.columns], tags=tags)
        text = f"{len(self.rows)} record(s)"
        if self.tag_key and self.rows:  # e.g. "Available: 5 | Occupied: 3 | Maintenance: 1"
            counts = {}
            for row in self.rows:
                counts[row[self.tag_key]] = counts.get(row[self.tag_key], 0) + 1
            text += "   -   " + " | ".join(f"{name}: {count}" for name, count in sorted(counts.items()))
        self.count_label.configure(text=text)

    def refresh(self):
        """Called whenever this page is shown: reload everything from the database."""
        self.reload_filter_options()
        self.reload_table()
        self.refresh_choice_fields(0)
        self.app.set_status(f"{self.title}: {len(self.rows)} record(s) loaded.")

    # ----- form --------------------------------------------------------------
    def default_for(self, field):
        return field.default() if callable(field.default) else field.default

    def get_form_values(self):
        """Collect the form as a dict. Dropdowns that load from the database give the numeric ID."""
        values = {}
        for field in self.fields:
            text = self.form_vars[field.key].get().strip()
            if field.kind == "choice":
                values[field.key] = dict((label, ident) for ident, label in self.form_options.get(field.key, [])).get(text)
            else:
                values[field.key] = text
        return values

    def load_choice_field(self, field, values):
        """Fill one database-driven dropdown, using the values chosen in the earlier fields."""
        try:
            options = list(field.options(values, self.selected_id))
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            options = []
        if not field.required:
            options.insert(0, (None, "(none)"))
        self.form_options[field.key] = options
        self.form_widgets[field.key]["values"] = [label for _, label in options]

    def set_choice_value(self, key, ident):
        label = next((lbl for i, lbl in self.form_options.get(key, []) if i == ident and ident is not None), "")
        self.form_vars[key].set(label)

    def refresh_choice_fields(self, start_index):
        """Reload the dropdowns from `start_index` onward. A later dropdown keeps its selection only if the
        choice is still valid (e.g. the department list changes when another hospital is picked)."""
        values = self.get_form_values()
        for index, field in enumerate(self.fields):
            if index < start_index or field.kind != "choice":
                continue
            previous = values.get(field.key)
            self.load_choice_field(field, values)
            valid_ids = [ident for ident, _ in self.form_options[field.key]]
            if previous in valid_ids and previous is not None:
                self.set_choice_value(field.key, previous)
            else:
                self.form_vars[field.key].set("")
            values = {**values, **{k: v for k, v in self.get_form_values().items() if k == field.key}}

    def on_choice_selected(self, key):
        index = next(i for i, f in enumerate(self.fields) if f.key == key)
        self.refresh_choice_fields(index + 1)

    def clear_form(self):
        self.selected_id = None
        self.tree.selection_remove(*self.tree.selection())
        for field in self.fields:
            self.form_vars[field.key].set(self.default_for(field) if field.kind != "choice" else "")
        self.refresh_choice_fields(0)

    def on_row_selected(self, event=None):
        selection = self.tree.selection()
        if not selection:
            return
        try:
            record = self.get_func(int(selection[0]))
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            return
        if record is None:
            messagebox.showwarning("Not found", "This record no longer exists. The table will be refreshed.",
                                   parent=self)
            self.refresh()
            return
        self.selected_id = int(selection[0])
        values = {field.key: record.get(field.key) for field in self.fields}
        for field in self.fields:  # fields are in order, so each dropdown can use the ones before it
            if field.kind == "choice":
                self.load_choice_field(field, values)
                self.set_choice_value(field.key, values[field.key])
            else:
                self.form_vars[field.key].set("" if values[field.key] is None else str(values[field.key]))

    # ----- actions -----------------------------------------------------------
    def after_change(self, message):
        self.clear_form()
        self.reload_filter_options()
        self.reload_table()
        self.app.set_status(message)
        messagebox.showinfo("Success", message, parent=self)

    def add_record(self):
        try:
            new_id = self.add_func(self.get_form_values())
        except db.DatabaseError as error:
            messagebox.showerror("Cannot save", str(error), parent=self)
            return
        self.after_change(f"{self.record_name} added successfully (ID {new_id}).")

    def update_record(self):
        if self.selected_id is None:
            messagebox.showwarning("Nothing selected", f"Click a row in the table first, then edit the form "
                                   f"and press 'Update Selected'.", parent=self)
            return
        try:
            self.update_func(self.selected_id, self.get_form_values())
        except db.DatabaseError as error:
            messagebox.showerror("Cannot update", str(error), parent=self)
            return
        self.after_change(f"{self.record_name} {self.selected_id} updated successfully.")

    def delete_record(self):
        if self.selected_id is None:
            messagebox.showwarning("Nothing selected", "Click the row you want to delete first.", parent=self)
            return
        if not messagebox.askyesno("Confirm delete", f"Delete {self.record_name.lower()} {self.selected_id}?\n"
                                   "This cannot be undone.", icon="warning", parent=self):
            return
        record_id = self.selected_id
        try:
            self.delete_func(record_id)
        except db.DatabaseError as error:
            messagebox.showerror("Cannot delete", str(error), parent=self)
            return
        self.after_change(f"{self.record_name} {record_id} deleted.")

    def export_csv(self):
        frame = pd.DataFrame([{heading: row[key] for key, heading, _, _ in self.columns} for row in self.rows])
        self.app.save_dataframe_csv(frame, self.export_name)


# ---------------------------------------------------------------------------
# Matplotlib charts (shared by the dashboard previews and the analytics page)
# ---------------------------------------------------------------------------
def load_dataframe(query_key):
    """Run an analytics query and return the result as a Pandas DataFrame."""
    columns, rows = db.run_analytics_query(query_key)
    return pd.DataFrame(rows, columns=columns)


def _fs(compact):
    return 8 if compact else 10


def _wrap(labels, width=13):
    return [textwrap.fill(str(label), width) for label in labels]


def _style_axes(ax, compact):
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(labelsize=_fs(compact) - 1)
    ax.set_axisbelow(True)


def draw_empty(fig, title, compact=False):
    """Shown whenever there is no data, so charts never crash on empty tables."""
    fig.clear()
    ax = fig.add_subplot(111)
    ax.text(0.5, 0.5, "No data available", ha="center", va="center", fontsize=_fs(compact) + 2, color="#7F8C9A")
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.set_axis_off()


def _grouped_bars(ax, categories, series, colors, compact):
    """Draw side-by-side bars. `series` is a list of (legend label, list of values)."""
    count = len(series)
    width = 0.8 / count
    positions = list(range(len(categories)))
    for number, (label, values) in enumerate(series):
        offsets = [p + (number - (count - 1) / 2) * width for p in positions]
        bars = ax.bar(offsets, values, width, label=label, color=colors[number])
        ax.bar_label(bars, fontsize=_fs(compact) - 1, padding=2)
    ax.set_xticks(positions)
    ax.set_xticklabels(_wrap(categories), fontsize=_fs(compact) - 1)
    ax.yaxis.grid(True, color="#E5EAF0")
    ax.legend(fontsize=_fs(compact) - 1, frameon=False)


def draw_bed_status(fig, df, compact=False, period=None):
    title = "Bed Status Distribution"
    if df.empty or df["count"].sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    data = df[df["count"] > 0]
    wedges, _, autotexts = ax.pie(
        data["count"], colors=[STATUS_COLORS.get(s, "#7F8C9A") for s in data["bed_status"]], startangle=90,
        counterclock=False, autopct=lambda pct: f"{pct:.0f}%", pctdistance=0.78,
        wedgeprops={"width": 0.45, "edgecolor": "white"}, textprops={"fontsize": _fs(compact) - 1})
    for text in autotexts:
        text.set_color("white")
    ax.text(0, 0, f"{int(data['count'].sum())}\nbeds", ha="center", va="center", fontsize=_fs(compact) + 2,
            fontweight="bold")
    ax.legend(wedges, [f"{s} ({c})" for s, c in zip(data["bed_status"], data["count"])], loc="upper center",
              bbox_to_anchor=(0.5, 0.02), ncol=3, frameon=False, fontsize=_fs(compact) - 1)
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.axis("equal")


def draw_hospital_beds(fig, df, compact=False, period=None):
    title = "Hospital Bed Occupancy"
    if df.empty or (df["occupied"] + df["available"] + df["maintenance"]).sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    _grouped_bars(ax, list(df["hospital"]), [("Occupied", list(df["occupied"])), ("Available", list(df["available"]))],
                  [STATUS_COLORS["Occupied"], STATUS_COLORS["Available"]], compact)
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.set_ylabel("Number of beds", fontsize=_fs(compact))
    ax.set_xlabel("Hospital", fontsize=_fs(compact))
    _style_axes(ax, compact)


def draw_department_beds(fig, df, compact=False, period=None):
    title = "Department Bed Occupancy"
    if df.empty or (df["occupied"] + df["available"] + df["maintenance"]).sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    positions = list(range(len(df)))
    left_available = list(df["occupied"])
    left_maintenance = [o + a for o, a in zip(df["occupied"], df["available"])]
    ax.barh(positions, df["occupied"], color=STATUS_COLORS["Occupied"], label="Occupied")
    ax.barh(positions, df["available"], left=left_available, color=STATUS_COLORS["Available"], label="Available")
    ax.barh(positions, df["maintenance"], left=left_maintenance, color=STATUS_COLORS["Maintenance"],
            label="Maintenance")
    for position, occupied, available, maintenance in zip(positions, df["occupied"], df["available"], df["maintenance"]):
        total = occupied + available + maintenance
        if total:
            ax.text(total + 0.4, position, f"{occupied / total:.0%} occupied", va="center", fontsize=_fs(compact) - 1)
    ax.set_yticks(positions)
    ax.set_yticklabels(df["department"], fontsize=_fs(compact) - 1)
    ax.invert_yaxis()
    ax.set_xlabel("Number of beds (all hospitals combined)", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.legend(fontsize=_fs(compact) - 1, frameon=False, loc="lower right")
    ax.margins(x=0.18)
    _style_axes(ax, compact)


def draw_specialization(fig, df, compact=False, period=None):
    title = "Doctor Specialization Distribution"
    if df.empty:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    bars = ax.barh(_wrap(df["specialization"], 18), df["doctors"], color=SERIES_COLORS[0])
    ax.bar_label(bars, fontsize=_fs(compact) - 1, padding=2)
    ax.invert_yaxis()
    ax.set_xlabel("Number of doctors", fontsize=_fs(compact))
    ax.set_ylabel("Specialization", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.margins(x=0.1)
    _style_axes(ax, compact)


def draw_doctor_availability(fig, df, compact=False, period=None):
    title = "Doctor Availability"
    if df.empty or df["count"].sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    counts = df.set_index("availability_status")["count"].reindex(["Available", "Unavailable"], fill_value=0)
    bars = ax.bar(counts.index, counts.values, color=[STATUS_COLORS["Available"], STATUS_COLORS["Occupied"]], width=0.5)
    ax.bar_label(bars, fontsize=_fs(compact), padding=2)
    ax.set_xlabel("Availability status", fontsize=_fs(compact))
    ax.set_ylabel("Number of doctors", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.yaxis.grid(True, color="#E5EAF0")
    ax.margins(y=0.12)
    _style_axes(ax, compact)


def draw_equipment_category(fig, df, compact=False, period=None):
    title = "Equipment by Category"
    if df.empty:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    bars = ax.bar(_wrap(df["category"]), df["total_quantity"], color=SERIES_COLORS[: len(df)])
    ax.bar_label(bars, fontsize=_fs(compact) - 1, padding=2)
    ax.set_xlabel("Equipment category", fontsize=_fs(compact))
    ax.set_ylabel("Total quantity (units)", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.yaxis.grid(True, color="#E5EAF0")
    ax.margins(y=0.12)
    _style_axes(ax, compact)


def draw_equipment_availability(fig, df, compact=False, period=None):
    title = "Equipment Availability (Total vs Available)"
    if df.empty or df["total_quantity"].sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    _grouped_bars(ax, list(df["hospital"]), [("Total quantity", list(df["total_quantity"])),
                                              ("Available quantity", list(df["available_quantity"]))],
                  [SERIES_COLORS[4], SERIES_COLORS[0]], compact)
    ax.set_xlabel("Hospital", fontsize=_fs(compact))
    ax.set_ylabel("Units", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    _style_axes(ax, compact)


PERIOD_CODES = {"Daily": "D", "Weekly": "W", "Monthly": "M"}


def admissions_by_period(df, period="Monthly"):
    """Pandas: count admissions per day/week/month, filling empty periods with 0 so the line is continuous."""
    if df.empty:
        return pd.DataFrame(columns=["period", "admissions"])
    code = PERIOD_CODES.get(period, "M")
    dates = pd.to_datetime(df["admission_date"])
    counts = dates.dt.to_period(code).value_counts().sort_index()
    counts = counts.reindex(pd.period_range(counts.index.min(), counts.index.max(), freq=code), fill_value=0)
    pattern = "%b %Y" if code == "M" else "%d %b %Y"
    return pd.DataFrame({"period": [p.start_time.strftime(pattern) for p in counts.index],
                         "admissions": counts.values})


def draw_admissions_time(fig, df, compact=False, period="Monthly"):
    title = f"Admissions Over Time ({period})"
    summary = admissions_by_period(df, period)
    if summary.empty:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    x = list(range(len(summary)))
    ax.plot(x, summary["admissions"], marker="o", color=SERIES_COLORS[0], linewidth=2, markersize=4)
    ax.fill_between(x, summary["admissions"], alpha=0.12, color=SERIES_COLORS[0])
    step = max(1, len(x) // (5 if compact else 10))
    ax.set_xticks(x[::step])
    ax.set_xticklabels(list(summary["period"])[::step], rotation=30, ha="right", fontsize=_fs(compact) - 1)
    ax.set_xlabel(f"{period.replace('ly', '')} period" if period != "Daily" else "Date", fontsize=_fs(compact))
    ax.set_ylabel("Number of admissions", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    ax.yaxis.grid(True, color="#E5EAF0")
    ax.set_ylim(bottom=0)
    _style_axes(ax, compact)


def draw_admissions_hospital(fig, df, compact=False, period=None):
    title = "Admissions by Hospital"
    if df.empty or df["total_admissions"].sum() == 0:
        return draw_empty(fig, title, compact)
    fig.clear()
    ax = fig.add_subplot(111)
    _grouped_bars(ax, list(df["hospital"]), [("All admissions", list(df["total_admissions"])),
                                              ("Currently admitted", list(df["current_admissions"]))],
                  [SERIES_COLORS[4], SERIES_COLORS[1]], compact)
    ax.set_xlabel("Hospital", fontsize=_fs(compact))
    ax.set_ylabel("Number of admissions", fontsize=_fs(compact))
    ax.set_title(title, fontsize=_fs(compact) + 2, fontweight="bold")
    _style_axes(ax, compact)


# key -> (menu title, SQL query key, drawing function)
CHART_DEFS = {
    "bed_status": ("1. Bed Status Distribution", "bed_status", draw_bed_status),
    "hospital_beds": ("2. Hospital Bed Occupancy", "hospital_beds", draw_hospital_beds),
    "department_beds": ("3. Department Bed Occupancy", "department_beds", draw_department_beds),
    "specialization": ("4. Doctor Specialization Distribution", "specialization", draw_specialization),
    "doctor_availability": ("5. Doctor Availability", "doctor_availability", draw_doctor_availability),
    "equipment_category": ("6. Equipment by Category", "equipment_category", draw_equipment_category),
    "equipment_availability": ("7. Equipment Availability", "equipment_by_hospital", draw_equipment_availability),
    "admissions_time": ("8. Admissions Over Time", "admission_dates", draw_admissions_time),
    "admissions_hospital": ("9. Admissions by Hospital", "admissions_by_hospital", draw_admissions_hospital),
}


class ChartView(ttk.Frame):
    """A Matplotlib figure embedded in Tkinter with FigureCanvasTkAgg."""

    def __init__(self, parent, chart_key, figsize=(8, 5), compact=False):
        super().__init__(parent)
        self.chart_key, self.compact = chart_key, compact
        self.figure = Figure(figsize=figsize, dpi=100, facecolor="white", layout="tight")
        self.canvas = FigureCanvasTkAgg(self.figure, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.dataframe = pd.DataFrame()

    def refresh(self, period="Monthly"):
        """Query the database again and redraw."""
        _, query_key, draw = CHART_DEFS[self.chart_key]
        try:
            self.dataframe = load_dataframe(query_key)
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            self.dataframe = pd.DataFrame()
        draw(self.figure, self.dataframe, self.compact, period)
        self.canvas.draw_idle()

    def export_dataframe(self, period="Monthly"):
        """The data behind the chart, as shown (admissions are grouped by the chosen period)."""
        if self.chart_key == "admissions_time":
            return admissions_by_period(self.dataframe, period)
        return self.dataframe

    def save_png(self, path):
        # Same figure that is on screen, saved at 200 dpi for a sharp image.
        self.figure.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")

    def close(self):
        self.figure.clear()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
class DashboardPage(ttk.Frame):
    CARDS = [  # (caption, key in get_dashboard_stats(), colour, suffix)
        ("Total Hospitals", "total_hospitals", "#1F7A8C", ""), ("Total Departments", "total_departments", "#3D405B", ""),
        ("Total Doctors", "total_doctors", "#2A9D8F", ""), ("Available Doctors", "available_doctors", "#2E8B57", ""),
        ("Total Beds", "total_beds", "#1F7A8C", ""), ("Available Beds", "available_beds", "#2E8B57", ""),
        ("Occupied Beds", "occupied_beds", "#C0392B", ""), ("Bed Occupancy", "occupancy_pct", "#E07A5F", "%"),
        ("Equipment Items", "total_equipment", "#3D405B", ""),
        ("Available Equipment Qty", "available_equipment_qty", "#2A9D8F", ""),
        ("Current Admissions", "current_admissions", "#9B5DE5", ""),
    ]
    RECENT_COLUMNS = [("admission_id", "ID", 50), ("patient_ref", "Patient Ref", 110), ("hospital_name", "Hospital", 220),
                      ("department_name", "Department", 130), ("doctor_name", "Doctor", 140),
                      ("admission_date", "Admitted", 95), ("admission_type", "Type", 90),
                      ("admission_status", "Status", 90)]

    def __init__(self, parent, app):
        super().__init__(parent, style="Page.TFrame")
        self.app = app
        header = ttk.Frame(self, style="Page.TFrame")
        header.pack(fill="x", padx=16, pady=(12, 4))
        ttk.Label(header, text="Dashboard", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Refresh", style="Accent.TButton", command=self.refresh).pack(side="right")
        ttk.Label(header, text="Live figures from the SQLite database", style="Sub.TLabel").pack(
            side="left", padx=14, pady=(8, 0))

        scroll = ScrollableFrame(self)
        scroll.pack(fill="both", expand=True)
        body = scroll.inner

        # summary cards (6 per row)
        cards = ttk.Frame(body, style="Page.TFrame")
        cards.pack(fill="x", padx=16, pady=6)
        self.value_labels = {}
        for index, (caption, key, color, suffix) in enumerate(self.CARDS):
            row, column = divmod(index, 6)
            card = tk.Frame(cards, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
            card.grid(row=row, column=column, sticky="nsew", padx=4, pady=4)
            tk.Frame(card, bg=color, height=4).pack(fill="x")
            value = tk.Label(card, text="0", font=(FONT, 22, "bold"), bg=COLORS["card"], fg=color)
            value.pack(pady=(8, 0))
            tk.Label(card, text=caption, font=(FONT, 9), bg=COLORS["card"], fg=COLORS["muted"]).pack(pady=(0, 10))
            self.value_labels[key] = (value, suffix)
        for column in range(6):
            cards.columnconfigure(column, weight=1, uniform="cards")

        # recent admissions table
        ttk.Label(body, text="Recent Admissions", font=(FONT, 12, "bold"), background=COLORS["bg"]).pack(
            anchor="w", padx=18, pady=(10, 2))
        table_frame = ttk.Frame(body)
        table_frame.pack(fill="x", padx=16)
        self.tree = ttk.Treeview(table_frame, columns=[c[0] for c in self.RECENT_COLUMNS], show="headings", height=6)
        for key, heading, width in self.RECENT_COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, stretch=True)
        self.tree.tag_configure("Admitted", background="#E3F1F4")
        bar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="x", expand=True)

        # chart previews (same drawing functions as the analytics page, just smaller)
        ttk.Label(body, text="Chart Previews  (see the Analytics & Reports page for all charts)",
                  font=(FONT, 12, "bold"), background=COLORS["bg"]).pack(anchor="w", padx=18, pady=(14, 2))
        charts = ttk.Frame(body, style="Page.TFrame")
        charts.pack(fill="x", padx=16, pady=(0, 16))
        self.previews = []
        for column, key in enumerate(("bed_status", "hospital_beds", "admissions_time")):
            view = ChartView(charts, key, figsize=(3.4, 2.8), compact=True)
            view.grid(row=0, column=column, sticky="nsew", padx=4)
            charts.columnconfigure(column, weight=1, uniform="previews")
            self.previews.append(view)

    def refresh(self):
        try:
            stats = db.get_dashboard_stats()
            recent = db.list_admissions(limit=10)
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            return
        for key, (label, suffix) in self.value_labels.items():
            value = stats[key]
            label.configure(text=f"{value:,}{suffix}" if isinstance(value, int) else f"{value}{suffix}")
        self.tree.delete(*self.tree.get_children())
        for row in recent:
            self.tree.insert("", "end", values=[format_cell(row[c[0]]) for c in self.RECENT_COLUMNS],
                             tags=(row["admission_status"],))
        for view in self.previews:
            view.refresh()
        self.app.set_status(f"Dashboard refreshed - {stats['total_hospitals']} hospitals, "
                            f"{stats['current_admissions']} current admissions.")

    def close(self):
        for view in self.previews:
            view.close()


# ---------------------------------------------------------------------------
# Analytics and reports
# ---------------------------------------------------------------------------
def build_summary_dataframe():
    """Pandas: hospital-wise summary table with a calculated bed-occupancy percentage."""
    frame = load_dataframe("hospital_summary")
    if not frame.empty:
        total = frame["total_beds"].where(frame["total_beds"] > 0)  # avoid dividing by zero
        frame["bed_occupancy_pct"] = (frame["occupied_beds"] / total * 100).fillna(0).round(1)
    return frame


class AnalyticsPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, style="Page.TFrame")
        self.app = app
        header = ttk.Frame(self, style="Page.TFrame")
        header.pack(fill="x", padx=16, pady=(12, 4))
        ttk.Label(header, text="Analytics & Reports", style="Title.TLabel").pack(side="left")
        ttk.Button(header, text="Refresh All", style="Accent.TButton", command=self.refresh).pack(side="right")

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=16, pady=(4, 12))
        charts_tab = ttk.Frame(notebook, style="Page.TFrame")
        summary_tab = ttk.Frame(notebook, style="Page.TFrame")
        notebook.add(charts_tab, text="Charts")
        notebook.add(summary_tab, text="Hospital Summary Table")

        # ----- charts tab -----
        controls = ttk.Frame(charts_tab, style="Page.TFrame")
        controls.pack(fill="x", pady=8, padx=4)
        ttk.Label(controls, text="Chart:", style="Bar.TLabel").pack(side="left")
        self.titles = {definition[0]: key for key, definition in CHART_DEFS.items()}
        self.chart_var = tk.StringVar(value=CHART_DEFS["bed_status"][0])
        chooser = ttk.Combobox(controls, textvariable=self.chart_var, state="readonly", width=34,
                               values=list(self.titles))
        chooser.pack(side="left", padx=6)
        chooser.bind("<<ComboboxSelected>>", lambda event: self.show_chart())
        self.period_label = ttk.Label(controls, text="Group by:", style="Bar.TLabel")
        self.period_var = tk.StringVar(value="Monthly")
        self.period_box = ttk.Combobox(controls, textvariable=self.period_var, state="readonly", width=10,
                                       values=list(PERIOD_CODES))
        self.period_box.bind("<<ComboboxSelected>>", lambda event: self.show_chart())
        ttk.Button(controls, text="All Data (CSV)", command=self.export_all).pack(side="right")
        ttk.Button(controls, text="Chart Data (CSV)", command=self.export_chart_data).pack(side="right", padx=6)
        ttk.Button(controls, text="Save as PNG", command=self.save_chart_png).pack(side="right")
        self.chart = ChartView(charts_tab, "bed_status", figsize=(9, 5.2))
        self.chart.pack(fill="both", expand=True, padx=4, pady=(0, 4))

        # ----- summary tab -----
        top = ttk.Frame(summary_tab, style="Page.TFrame")
        top.pack(fill="x", pady=8, padx=4)
        ttk.Label(top, text="One row per hospital (calculated with SQL + Pandas).", style="Sub.TLabel").pack(side="left")
        ttk.Button(top, text="Export Summary (CSV)", command=self.export_summary).pack(side="right")
        holder = ttk.Frame(summary_tab)
        holder.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.summary_tree = ttk.Treeview(holder, show="headings", selectmode="browse")
        vbar = ttk.Scrollbar(holder, orient="vertical", command=self.summary_tree.yview)
        hbar = ttk.Scrollbar(holder, orient="horizontal", command=self.summary_tree.xview)
        self.summary_tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.summary_tree.pack(side="left", fill="both", expand=True)
        self.summary = pd.DataFrame()

    def current_key(self):
        return self.titles[self.chart_var.get()]

    def show_chart(self):
        key = self.current_key()
        self.chart.chart_key = key
        if key == "admissions_time":
            self.period_label.pack(side="left", padx=(14, 4))
            self.period_box.pack(side="left")
        else:
            self.period_label.pack_forget()
            self.period_box.pack_forget()
        self.chart.refresh(self.period_var.get())

    def refresh(self):
        self.show_chart()
        try:
            self.summary = build_summary_dataframe()
        except db.DatabaseError as error:
            messagebox.showerror("Database error", str(error), parent=self)
            self.summary = pd.DataFrame()
        columns = list(self.summary.columns)
        self.summary_tree.delete(*self.summary_tree.get_children())
        self.summary_tree.configure(columns=columns)
        for column in columns:
            self.summary_tree.heading(column, text=column.replace("_", " ").title())
            self.summary_tree.column(column, width=190 if column == "hospital" else 110, anchor="w" if column in
                                     ("hospital", "city") else "center", stretch=True)
        for record in self.summary.itertuples(index=False):
            self.summary_tree.insert("", "end", values=[format_cell(v) for v in record])
        self.app.set_status("Analytics refreshed from the database.")

    def save_chart_png(self):
        path = filedialog.asksaveasfilename(parent=self, title="Save chart as PNG", defaultextension=".png",
                                            initialfile=f"{self.current_key()}.png",
                                            filetypes=[("PNG image", "*.png"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.chart.save_png(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Export failed", f"Could not save the chart:\n{error}", parent=self)
            return
        messagebox.showinfo("Chart saved", f"Chart saved to:\n{path}", parent=self)

    def export_chart_data(self):
        self.app.save_dataframe_csv(self.chart.export_dataframe(self.period_var.get()), f"{self.current_key()}_data")

    def export_summary(self):
        self.app.save_dataframe_csv(self.summary, "hospital_summary")

    def export_all(self):
        """Write every analytical dataset to its own CSV file in a folder the user picks."""
        folder = filedialog.askdirectory(parent=self, title="Choose a folder for the CSV files")
        if not folder:
            return
        try:
            saved = 0
            for key, (_, query_key, _) in CHART_DEFS.items():
                frame = load_dataframe(query_key)
                if key == "admissions_time":
                    frame = admissions_by_period(frame, self.period_var.get())
                frame.to_csv(os.path.join(folder, f"{key}.csv"), index=False)
                saved += 1
            build_summary_dataframe().to_csv(os.path.join(folder, "hospital_summary.csv"), index=False)
            saved += 1
        except (OSError, db.DatabaseError) as error:
            messagebox.showerror("Export failed", f"Could not export the data:\n{error}", parent=self)
            return
        messagebox.showinfo("Export complete", f"{saved} CSV files saved in:\n{folder}", parent=self)

    def close(self):
        self.chart.close()


# ---------------------------------------------------------------------------
# Page definitions: each function describes one management screen
# ---------------------------------------------------------------------------
def hospital_choice(values, record_id=None):
    return db.get_hospital_options()


def department_choice(values, record_id=None):
    return db.get_department_options(values.get("hospital_id")) if values.get("hospital_id") else []


def hospital_filter(values):
    return db.get_hospital_options()


def department_filter(values):
    return db.get_department_options(values.get("hospital_id"))


def today_text():
    return date.today().isoformat()


def build_hospitals_page(parent, app):
    return ManagementPage(
        parent, app, "Hospitals", "Hospital", "hospital_id",
        columns=[("hospital_id", "ID", 50, "center"), ("hospital_name", "Hospital Name", 200, "w"),
                 ("city", "City", 100, "w"), ("hospital_type", "Type", 100, "w"),
                 ("contact_number", "Contact", 120, "w"), ("email", "Email", 200, "w"),
                 ("total_capacity", "Capacity", 80, "e"), ("established_date", "Established", 95, "center"),
                 ("address", "Address", 220, "w")],
        fields=[Field("hospital_name", "Hospital name"), Field("city", "City"), Field("address", "Address"),
                Field("contact_number", "Contact number"), Field("email", "Email"),
                Field("hospital_type", "Hospital type", "combo", values=db.HOSPITAL_TYPES, default="Private"),
                Field("total_capacity", "Total capacity (beds)"),
                Field("established_date", "Established (YYYY-MM-DD)")],
        filters=[FilterSpec("hospital_type", "Type", "values", lambda v: db.get_distinct_values("hospitals", "hospital_type")),
                 FilterSpec("city", "City", "values", lambda v: db.get_distinct_values("hospitals", "city"))],
        list_func=db.list_hospitals, get_func=db.get_hospital, add_func=db.add_hospital,
        update_func=db.update_hospital, delete_func=db.delete_hospital, export_name="hospitals",
        search_hint="Search name / city / type")


def build_departments_page(parent, app):
    return ManagementPage(
        parent, app, "Departments", "Department", "department_id",
        columns=[("department_id", "ID", 50, "center"), ("hospital_name", "Hospital", 230, "w"),
                 ("department_name", "Department", 160, "w"), ("floor_location", "Floor / Location", 120, "w"),
                 ("contact_number", "Contact", 130, "w"), ("department_head", "Department Head", 170, "w")],
        fields=[Field("hospital_id", "Hospital", "choice", options=hospital_choice),
                Field("department_name", "Department name"), Field("floor_location", "Floor / location"),
                Field("contact_number", "Contact number"), Field("department_head", "Department head")],
        filters=[FilterSpec("hospital_id", "Hospital", "choice", hospital_filter)],
        list_func=db.list_departments, get_func=db.get_department, add_func=db.add_department,
        update_func=db.update_department, delete_func=db.delete_department, export_name="departments",
        search_hint="Search department name")


def build_doctors_page(parent, app):
    return ManagementPage(
        parent, app, "Doctors", "Doctor", "doctor_id",
        columns=[("doctor_id", "ID", 50, "center"), ("doctor_name", "Doctor", 150, "w"),
                 ("specialization", "Specialization", 140, "w"), ("hospital_name", "Hospital", 200, "w"),
                 ("department_name", "Department", 120, "w"), ("contact_number", "Contact", 120, "w"),
                 ("email", "Email", 220, "w"), ("availability_status", "Availability", 90, "center"),
                 ("consultation_fee", "Fee", 80, "e"), ("years_of_experience", "Exp (yrs)", 70, "center")],
        fields=[Field("hospital_id", "Hospital", "choice", options=hospital_choice),
                Field("department_id", "Department", "choice", options=department_choice),
                Field("doctor_name", "Doctor name"), Field("specialization", "Specialization"),
                Field("contact_number", "Contact number"), Field("email", "Email"),
                Field("availability_status", "Availability", "combo", values=db.DOCTOR_STATUSES, default="Available"),
                Field("consultation_fee", "Consultation fee"),
                Field("years_of_experience", "Years of experience")],
        filters=[FilterSpec("hospital_id", "Hospital", "choice", hospital_filter),
                 FilterSpec("department_id", "Department", "choice", department_filter),
                 FilterSpec("specialization", "Specialization", "values",
                            lambda v: db.get_distinct_values("doctors", "specialization")),
                 FilterSpec("availability_status", "Availability", "values", lambda v: db.DOCTOR_STATUSES)],
        list_func=db.list_doctors, get_func=db.get_doctor, add_func=db.add_doctor, update_func=db.update_doctor,
        delete_func=db.delete_doctor, export_name="doctors", search_hint="Search name / specialization",
        tag_key="availability_status", tag_colors={"Unavailable": "#FBE9E7"})


def build_beds_page(parent, app):
    return ManagementPage(
        parent, app, "Beds", "Bed", "bed_id",
        columns=[("bed_id", "Bed ID", 70, "center"), ("hospital_name", "Hospital", 230, "w"),
                 ("department_name", "Department", 150, "w"), ("ward_name", "Ward", 170, "w"),
                 ("bed_type", "Bed Type", 100, "w"), ("bed_status", "Status", 100, "center"),
                 ("daily_charge", "Daily Charge", 100, "e")],
        fields=[Field("hospital_id", "Hospital", "choice", options=hospital_choice),
                Field("department_id", "Department", "choice", options=department_choice),
                Field("ward_name", "Ward name"),
                Field("bed_type", "Bed type", "combo", values=db.BED_TYPES, default="General"),
                Field("bed_status", "Bed status", "combo", values=db.BED_STATUSES, default="Available"),
                Field("daily_charge", "Daily charge")],
        filters=[FilterSpec("hospital_id", "Hospital", "choice", hospital_filter),
                 FilterSpec("department_id", "Department", "choice", department_filter),
                 FilterSpec("bed_type", "Bed type", "values", lambda v: db.BED_TYPES),
                 FilterSpec("bed_status", "Status", "values", lambda v: db.BED_STATUSES)],
        list_func=db.list_beds, get_func=db.get_bed, add_func=db.add_bed, update_func=db.update_bed,
        delete_func=db.delete_bed, export_name="beds", search_hint="Search bed ID / ward",
        tag_key="bed_status", tag_colors={"Available": "#E4F4EA", "Occupied": "#FBE4E1", "Maintenance": "#FFF3D1"})


def build_equipment_page(parent, app):
    return ManagementPage(
        parent, app, "Equipment", "Equipment", "equipment_id",
        columns=[("equipment_id", "ID", 50, "center"), ("equipment_name", "Equipment", 190, "w"),
                 ("hospital_name", "Hospital", 220, "w"), ("department_name", "Department", 130, "w"),
                 ("equipment_category", "Category", 110, "w"), ("quantity", "Total Qty", 75, "center"),
                 ("available_quantity", "Available Qty", 95, "center"), ("equipment_status", "Status", 130, "center"),
                 ("last_maintenance_date", "Last Maintenance", 120, "center")],
        fields=[Field("hospital_id", "Hospital", "choice", options=hospital_choice),
                Field("department_id", "Department", "choice", options=department_choice),
                Field("equipment_name", "Equipment name"),
                Field("equipment_category", "Category", "combo", values=db.EQUIPMENT_CATEGORIES, default="Diagnostic"),
                Field("quantity", "Total quantity"), Field("available_quantity", "Available quantity"),
                Field("equipment_status", "Status", "combo", values=db.EQUIPMENT_STATUSES, default="Operational"),
                Field("last_maintenance_date", "Last maintenance (YYYY-MM-DD)", required=False)],
        filters=[FilterSpec("hospital_id", "Hospital", "choice", hospital_filter),
                 FilterSpec("department_id", "Department", "choice", department_filter),
                 FilterSpec("equipment_category", "Category", "values", lambda v: db.EQUIPMENT_CATEGORIES),
                 FilterSpec("equipment_status", "Status", "values", lambda v: db.EQUIPMENT_STATUSES)],
        list_func=db.list_equipment, get_func=db.get_equipment, add_func=db.add_equipment,
        update_func=db.update_equipment, delete_func=db.delete_equipment, export_name="equipment",
        search_hint="Search equipment name", tag_key="equipment_status",
        tag_colors={"Under Maintenance": "#FFF3D1", "Out of Service": "#FBE4E1"})


def build_admissions_page(parent, app):
    def doctor_choice(values, record_id=None):
        return db.get_doctor_options(values.get("hospital_id"), values.get("department_id"))

    def bed_choice(values, record_id=None):
        return db.get_bed_options(values.get("hospital_id"), record_id)

    return ManagementPage(
        parent, app, "Admissions", "Admission", "admission_id",
        columns=[("admission_id", "ID", 50, "center"), ("patient_ref", "Patient Ref", 100, "w"),
                 ("hospital_name", "Hospital", 200, "w"), ("department_name", "Department", 120, "w"),
                 ("doctor_name", "Doctor", 140, "w"), ("bed_id", "Bed", 55, "center"),
                 ("admission_date", "Admitted", 95, "center"), ("discharge_date", "Discharged", 95, "center"),
                 ("admission_type", "Type", 90, "center"), ("admission_status", "Status", 90, "center")],
        fields=[Field("hospital_id", "Hospital", "choice", options=hospital_choice),
                Field("department_id", "Department", "choice", options=department_choice),
                Field("doctor_id", "Doctor", "choice", options=doctor_choice),
                Field("bed_id", "Bed (required if Admitted)", "choice", options=bed_choice, required=False),
                Field("patient_ref", "Patient reference no."),
                Field("admission_date", "Admission date (YYYY-MM-DD)", default=today_text),
                Field("discharge_date", "Discharge date (YYYY-MM-DD)", required=False),
                Field("admission_type", "Admission type", "combo", values=db.ADMISSION_TYPES, default="Planned"),
                Field("admission_status", "Status", "combo", values=db.ADMISSION_STATUSES, default="Admitted")],
        filters=[FilterSpec("hospital_id", "Hospital", "choice", hospital_filter),
                 FilterSpec("department_id", "Department", "choice", department_filter),
                 FilterSpec("admission_status", "Status", "values", lambda v: db.ADMISSION_STATUSES),
                 FilterSpec("date_from", "From date (YYYY-MM-DD)", "entry"),
                 FilterSpec("date_to", "To date (YYYY-MM-DD)", "entry")],
        list_func=db.list_admissions, get_func=db.get_admission, add_func=db.add_admission,
        update_func=db.update_admission, delete_func=db.delete_admission, export_name="admissions",
        search_hint="Search patient ref / admission ID", tag_key="admission_status",
        tag_colors={"Admitted": "#E3F1F4"})


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------
class HospitalApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hospital Database Management and Analytics System")
        self.geometry("1340x840")
        self.minsize(1100, 700)
        self.configure(bg=COLORS["bg"])
        setup_styles(self)

        # sidebar
        sidebar = tk.Frame(self, bg=COLORS["sidebar"], width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="MediTrack HMS", font=(FONT, 17, "bold"), bg=COLORS["sidebar"], fg="white").pack(
            anchor="w", padx=20, pady=(22, 0))
        tk.Label(sidebar, text="Hospital Database &\nAnalytics System", font=(FONT, 9), justify="left",
                 bg=COLORS["sidebar"], fg="#8FA6BB").pack(anchor="w", padx=20, pady=(0, 22))

        # status bar (bottom) and content area
        status_bar = tk.Frame(self, bg="#E3EAF1")
        status_bar.pack(side="bottom", fill="x")
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(status_bar, textvariable=self.status_var, anchor="w", bg="#E3EAF1", fg=COLORS["text"],
                 font=(FONT, 9)).pack(side="left", padx=12, pady=3)
        tk.Label(status_bar, text=f"Database: {db.DB_PATH}", anchor="e", bg="#E3EAF1", fg=COLORS["muted"],
                 font=(FONT, 9)).pack(side="right", padx=12)
        container = ttk.Frame(self, style="Page.TFrame")
        container.pack(side="right", fill="both", expand=True)
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        # pages
        self.pages = {
            "Dashboard": DashboardPage(container, self),
            "Hospitals": build_hospitals_page(container, self),
            "Departments": build_departments_page(container, self),
            "Doctors": build_doctors_page(container, self),
            "Beds": build_beds_page(container, self),
            "Equipment": build_equipment_page(container, self),
            "Admissions": build_admissions_page(container, self),
            "Analytics & Reports": AnalyticsPage(container, self),
        }
        self.nav_buttons = {}
        for name, page in self.pages.items():
            page.grid(row=0, column=0, sticky="nsew")
            button = ttk.Button(sidebar, text=name, style="Nav.TButton", command=lambda n=name: self.show_page(n))
            button.pack(fill="x")
            self.nav_buttons[name] = button

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.show_page("Dashboard")

    def show_page(self, name):
        for page_name, button in self.nav_buttons.items():
            button.configure(style="NavActive.TButton" if page_name == name else "Nav.TButton")
        self.pages[name].tkraise()
        self.pages[name].refresh()

    def set_status(self, text):
        self.status_var.set(text)

    def save_dataframe_csv(self, frame, default_name):
        """Ask where to save, then write a DataFrame to CSV with Pandas."""
        if frame is None or frame.empty:
            messagebox.showwarning("Nothing to export", "There is no data to export right now.", parent=self)
            return
        path = filedialog.asksaveasfilename(parent=self, title="Export to CSV", defaultextension=".csv",
                                            initialfile=f"{default_name}.csv",
                                            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            frame.to_csv(path, index=False)
        except OSError as error:
            messagebox.showerror("Export failed", f"Could not save the file:\n{error}", parent=self)
            return
        self.set_status(f"Exported {len(frame)} row(s) to {path}")
        messagebox.showinfo("Export complete", f"{len(frame)} row(s) saved to:\n{path}", parent=self)

    def on_close(self):
        """Release Matplotlib figures before closing."""
        for page in self.pages.values():
            if hasattr(page, "close"):
                page.close()
        self.destroy()


def main():
    try:
        db.init_database()  # creates hospital.db + sample data on the first run only
    except db.DatabaseError as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Database error", str(error))
        root.destroy()
        return
    HospitalApp().mainloop()


if __name__ == "__main__":
    main()
