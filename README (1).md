# Hospital Database Management and Analytics System

A desktop application for managing hospitals, departments, doctors, beds, equipment and patient admissions, with built-in analytics and charts. Built with **Python, Tkinter (ttk), SQLite, Pandas and Matplotlib** as a college-level project.

It is a native desktop program - no web server, no browser, no cloud database. Everything is stored in one local file, `hospital.db`.

---

## 1. Main Features

- **Dashboard** - 11 live summary cards (hospitals, departments, doctors, available doctors, beds, available/occupied beds, bed occupancy %, equipment items, available equipment quantity, current admissions), a recent-admissions table, three chart previews and a Refresh button.
- **Six management screens** (Hospitals, Departments, Doctors, Beds, Equipment, Admissions), each with Add / View / Edit / Delete, a search box, filter dropdowns, colour-coded rows and CSV export.
- **Analytics & Reports** - 9 charts embedded inside the window, a Pandas hospital-summary table, PNG export for any chart and CSV export for the data behind it.
- **Data integrity** - foreign keys enforced on every connection, dependent dropdowns (hospital -> department -> doctor), validation of every field, no silent deletes, and automatic bed status updates when patients are admitted, edited, discharged or deleted.
- **Automatic setup** - the database, tables and realistic sample data are created on first launch. Sample data is never inserted twice.

## 2. Technology Stack

| Technology | Used for |
|---|---|
| Python 3.9+ | Application logic |
| Tkinter + ttk | Desktop user interface |
| SQLite (`sqlite3`) | Local database |
| Pandas | Summaries, grouping admissions by day/week/month, CSV export |
| Matplotlib | Charts embedded with `FigureCanvasTkAgg` and exported as PNG |

## 3. Project Files

```
main.py            - the whole GUI: dashboard, forms, tables, analytics, charts, exports
database.py        - schema, sample data, validation, CRUD, relationships, SQL queries
requirements.txt   - external packages (pandas, matplotlib)
README.md          - this file
hospital.db        - created automatically on the first run
```

## 4. Installation and Launch

1. Install **Python 3.9 or newer** from python.org.
   **Tkinter is part of the Python installation, not a pip package.** It is included by default on Windows and macOS (python.org installers). On Linux you may need to install it separately, e.g. `sudo apt install python3-tk` on Ubuntu/Debian.
2. Open a terminal in the project folder and run:

```bash
pip install -r requirements.txt
python main.py
```

That's all - no separate database setup command. (On some systems use `python3` and `pip3`.)

## 5. How the Database Is Created Automatically

When `main.py` starts it calls `init_database()` from `database.py`, which:

1. Creates `hospital.db` if it doesn't exist.
2. Creates the six tables (`CREATE TABLE IF NOT EXISTS`) and two helper indexes.
3. Checks a small counter stored inside the database file (`PRAGMA user_version`). If it is `0` and the hospitals table is empty, it inserts the sample data (4 hospitals, 20 departments, 40 doctors, 100 beds, 40 equipment records, 95 admissions) and sets the counter to `1`.

On later launches the counter is `1`, so nothing is inserted and your saved data is kept. To start over with fresh sample data, close the app and delete `hospital.db`.

## 6. Database Design (six normalized tables)

```
hospitals 1 --- * departments 1 --- * doctors
    |                  |  \--- * beds
    |                  |  \--- * equipment
    \-- (every table also stores hospital_id)
admissions  ->  hospital, department, doctor, bed (optional until admitted)
```

| Table | Key columns | Notes |
|---|---|---|
| **hospitals** | hospital_id (PK), name, address, city, contact, email, type, total_capacity, established_date | Unique email; unique (name, city); capacity > 0 |
| **departments** | department_id (PK), hospital_id (FK), name, floor/location, contact, head | Unique (hospital, department name) |
| **doctors** | doctor_id (PK), hospital_id (FK), department_id (FK), name, specialization, contact, email, availability, fee, experience | Unique email; fee >= 0; experience >= 0 |
| **beds** | bed_id (PK), hospital_id (FK), department_id (FK), ward, bed_type, bed_status, daily_charge | Status: Available / Occupied / Maintenance; charge >= 0 |
| **equipment** | equipment_id (PK), hospital_id (FK), department_id (FK), name, category, quantity, available_quantity, status, last_maintenance_date | `available_quantity <= quantity`; unique per department |
| **admissions** | admission_id (PK), hospital_id, department_id, doctor_id (FKs), patient_ref, admission_date, discharge_date, type, status, bed_id (FK) | Discharged needs a discharge date; Admitted needs a bed |

Integrity rules enforced **inside SQLite itself**:

- `PRAGMA foreign_keys = ON` for every connection.
- **Composite foreign keys** such as `(department_id, hospital_id)` prove that a department really belongs to the chosen hospital, a doctor belongs to the chosen hospital *and* department, and a bed belongs to the chosen hospital.
- `ON DELETE RESTRICT` everywhere - parents cannot be deleted while children exist.
- `CHECK` constraints for statuses/types, non-negative numbers, date order and `available_quantity <= quantity`.
- Two partial unique indexes: **a bed can have only one active admission**, and **a patient can have only one active admission**.

`database.py` adds friendlier checks before saving (valid dates, email/phone format, required fields, duplicate detection, capacity limits) so users see plain-English messages instead of raw SQL errors.

## 7. How to Use the Application

Use the sidebar on the left to switch screens. The Dashboard opens by default.

### Add, edit and delete records
- **Add**: fill in the form at the bottom (fields marked `*` are required) and click **Add ...**.
- **Edit**: click a row in the table - its values load into the form. Change them and click **Update Selected**.
- **Delete**: click a row, then **Delete Selected**, and confirm. If other records depend on it (for example a hospital that still has departments, or a bed that has admissions) the delete is refused with an explanation. Nothing is deleted silently.
- **Clear Form** resets the form and un-selects the row.
- Dates use the format `YYYY-MM-DD`.

### Dependent dropdowns
Choose the **hospital** first - the **department** list then shows only that hospital's departments. In Admissions the **doctor** list shows doctors of the chosen hospital and department, and the **bed** list shows the free beds of the chosen hospital.

### Search and filters
Type in the search box to filter the table instantly (hospital name/city/type, department name, doctor name/specialization, bed ID/ward, equipment name, patient reference/admission ID). Use the dropdowns for filters (hospital, department, type, status, specialization, availability, category, date range for admissions). **Clear Filters** resets everything. The heading shows the record count and, for beds and admissions, the count per status.

### Beds and admissions (important rules)
- A bed becomes **Occupied** automatically when an admission with status *Admitted* uses it, and returns to **Available** when the patient is discharged, the admission is moved to another bed, or the admission is deleted. You cannot set Occupied by hand, and you cannot free a bed that has an active admission.
- A bed in **Maintenance** cannot be assigned to a patient.
- Use a *patient reference number* (e.g. `PAT-100123`), not a real name.

### Analytics & Reports
- **Charts** tab: pick one of nine charts - Bed Status, Hospital Bed Occupancy, Department Bed Occupancy, Doctor Specialization, Doctor Availability, Equipment by Category, Equipment Availability, Admissions Over Time (group by Daily / Weekly / Monthly) and Admissions by Hospital.
- **Hospital Summary Table** tab: one row per hospital with beds, occupancy %, equipment and admissions.
- **Refresh All** reloads everything from the database.

### Exports
- **Export Table to CSV** (on every management screen) saves the rows currently shown - clear the filters to export the whole table.
- **Save as PNG** saves the chart you are looking at (200 dpi).
- **Chart Data (CSV)** saves the data behind the current chart; **All Data (CSV)** saves every analytics dataset into a folder you choose; the summary tab has **Export Summary (CSV)**.

## 8. Common Errors and Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Tkinter comes with Python. Reinstall Python with Tcl/Tk enabled, or on Linux run `sudo apt install python3-tk`. |
| `ModuleNotFoundError: pandas` / `matplotlib` | Run `pip install -r requirements.txt` (use the same Python you run `main.py` with). |
| `python` not found | Try `python3 main.py` (macOS/Linux) or `py main.py` (Windows). |
| "database is locked" | Close any other program (e.g. a DB viewer) that has `hospital.db` open. |
| Messages like "Cannot delete ... linked" | Expected: remove or reassign the dependent records first. |
| Want fresh sample data | Close the app and delete `hospital.db`, then run `python main.py` again. |
| Charts look empty | They show "No data available" when the tables are empty - add records and click Refresh. |

## 9. How It Works (viva notes)

- **Two files, two jobs.** `database.py` knows SQL and business rules; `main.py` knows widgets and charts and only calls functions from `database.py`.
- **One reusable GUI class.** `ManagementPage` in `main.py` builds all six CRUD screens. Each screen is described by data: its columns, form `Field`s, `FilterSpec`s and the database functions to call. That keeps the code short and consistent.
- **Parameterized SQL.** Every user value is passed with `?` placeholders (never string-built), which prevents SQL injection. Column names only ever come from fixed lists in the code.
- **Transactions.** `db_session(write=True)` opens a connection, commits on success and rolls back on any error. Adding or editing an admission and updating the bed happen in one transaction, so they succeed or fail together.
- **Bed consistency.** After every admission change, `_refresh_bed_status()` re-checks the old and new bed: Occupied if an admitted patient uses it, otherwise Available.
- **Validation in layers.** (1) Python validators give friendly messages; (2) `CHECK`, `UNIQUE`, `NOT NULL` and (composite) foreign keys guarantee the data stays valid even if a bug slips through.
- **Analytics.** SQL queries produce small tables, Pandas turns them into DataFrames (and does the daily/weekly/monthly grouping and occupancy %), and Matplotlib `Figure` objects are embedded with `FigureCanvasTkAgg`. The same drawing functions feed the dashboard previews, the analytics page and the PNG export, so exported images match what is on screen.
- **Seeding once.** `PRAGMA user_version` remembers that the sample data was inserted, so restarts never duplicate it.
