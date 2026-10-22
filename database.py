"""
database.py
===========
Everything that touches the SQLite database lives in this file:

  1. Connection handling (foreign keys are switched ON for every connection)
  2. The database schema (six normalized tables)
  3. One-time sample data
  4. Validation helpers (all form data is checked here before saving)
  5. CRUD functions (add / get / update / delete) for each table
  6. Search + filter queries used by the GUI tables
  7. Dashboard and analytics queries

main.py only calls the public functions of this file; it never writes SQL.
All SQL that contains user input uses "?" placeholders (parameterized queries).
"""

import math
import os
import random
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta

# The database file is created next to this script the first time the app runs.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hospital.db")

# ---------------------------------------------------------------------------
# Allowed values (used by the CHECK constraints, validation and GUI dropdowns)
# ---------------------------------------------------------------------------
HOSPITAL_TYPES = ["Government", "Private", "Teaching", "Specialty", "Community"]
BED_TYPES = ["General", "Semi-Private", "Private", "ICU", "Emergency"]
BED_STATUSES = ["Available", "Occupied", "Maintenance"]
DOCTOR_STATUSES = ["Available", "Unavailable"]
EQUIPMENT_CATEGORIES = ["Diagnostic", "Surgical", "Life Support", "Monitoring", "Therapeutic"]
EQUIPMENT_STATUSES = ["Operational", "Under Maintenance", "Out of Service"]
ADMISSION_TYPES = ["Emergency", "Planned", "Transfer", "Day Care"]
ADMISSION_STATUSES = ["Admitted", "Discharged"]

DATE_FORMAT = "%Y-%m-%d"


class DatabaseError(Exception):
    """Raised for any problem the user should be told about (bad input, broken rules, SQL errors)."""


# ---------------------------------------------------------------------------
# 1. Connection handling
# ---------------------------------------------------------------------------
def get_connection():
    """Open a new connection. Foreign-key enforcement is OFF by default in SQLite,
    so we must turn it on for every single connection."""
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _friendly_integrity_message(error):
    """Translate a raw SQLite constraint error into a sentence a user can understand."""
    text = str(error)
    if text.startswith("UNIQUE constraint failed"):
        columns = text.split(":", 1)[1].strip()
        if columns.startswith("index"):
            return "This bed or patient already has an active admission."
        names = ", ".join(part.strip().split(".")[-1].replace("_", " ") for part in columns.split(","))
        return f"A record with the same {names} already exists."
    if "FOREIGN KEY" in text:
        return ("This change breaks a relationship between tables (a linked hospital, department, "
                "doctor or bed is missing, does not match, or is still in use).")
    if "CHECK constraint failed" in text:
        return "A value is outside the allowed range or list of options."
    if "NOT NULL" in text:
        return "A required field is empty."
    return f"Database constraint error: {text}"


@contextmanager
def db_session(write=False):
    """Open a connection, run the caller's SQL, then commit (write=True) or roll back on error.
    Everything inside one 'with' block is ONE transaction, so related changes succeed or fail together."""
    connection = get_connection()
    try:
        yield connection
        if write:
            connection.commit()
    except sqlite3.IntegrityError as error:
        connection.rollback()
        raise DatabaseError(_friendly_integrity_message(error)) from error
    except sqlite3.Error as error:
        connection.rollback()
        raise DatabaseError(f"Database error: {error}") from error
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _in_list(values):
    """Build the text "('A', 'B')" for a CHECK constraint from a Python list of fixed constants."""
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


# ---------------------------------------------------------------------------
# 2. Schema
# ---------------------------------------------------------------------------
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS hospitals (
    hospital_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_name    TEXT    NOT NULL CHECK (length(trim(hospital_name)) > 0),
    address          TEXT    NOT NULL,
    city             TEXT    NOT NULL,
    contact_number   TEXT    NOT NULL,
    email            TEXT    NOT NULL UNIQUE,
    hospital_type    TEXT    NOT NULL CHECK (hospital_type IN {_in_list(HOSPITAL_TYPES)}),
    total_capacity   INTEGER NOT NULL CHECK (total_capacity > 0),
    established_date TEXT    NOT NULL,
    UNIQUE (hospital_name, city)
);

CREATE TABLE IF NOT EXISTS departments (
    department_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id     INTEGER NOT NULL,
    department_name TEXT    NOT NULL CHECK (length(trim(department_name)) > 0),
    floor_location  TEXT    NOT NULL,
    contact_number  TEXT    NOT NULL,
    department_head TEXT    NOT NULL,
    UNIQUE (hospital_id, department_name),
    UNIQUE (department_id, hospital_id),   -- lets other tables prove "department belongs to hospital"
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS doctors (
    doctor_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id         INTEGER NOT NULL,
    department_id       INTEGER NOT NULL,
    doctor_name         TEXT    NOT NULL CHECK (length(trim(doctor_name)) > 0),
    specialization      TEXT    NOT NULL,
    contact_number      TEXT    NOT NULL,
    email               TEXT    NOT NULL UNIQUE,
    availability_status TEXT    NOT NULL CHECK (availability_status IN {_in_list(DOCTOR_STATUSES)}),
    consultation_fee    REAL    NOT NULL CHECK (consultation_fee >= 0),
    years_of_experience INTEGER NOT NULL CHECK (years_of_experience >= 0),
    UNIQUE (doctor_id, hospital_id),
    UNIQUE (doctor_id, department_id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (department_id, hospital_id) REFERENCES departments (department_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS beds (
    bed_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id   INTEGER NOT NULL,
    department_id INTEGER NOT NULL,
    ward_name     TEXT    NOT NULL CHECK (length(trim(ward_name)) > 0),
    bed_type      TEXT    NOT NULL CHECK (bed_type IN {_in_list(BED_TYPES)}),
    bed_status    TEXT    NOT NULL CHECK (bed_status IN {_in_list(BED_STATUSES)}),
    daily_charge  REAL    NOT NULL CHECK (daily_charge >= 0),
    UNIQUE (bed_id, hospital_id),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (department_id, hospital_id) REFERENCES departments (department_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS equipment (
    equipment_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id           INTEGER NOT NULL,
    department_id         INTEGER NOT NULL,
    equipment_name        TEXT    NOT NULL CHECK (length(trim(equipment_name)) > 0),
    equipment_category    TEXT    NOT NULL CHECK (equipment_category IN {_in_list(EQUIPMENT_CATEGORIES)}),
    quantity              INTEGER NOT NULL CHECK (quantity >= 0),
    available_quantity    INTEGER NOT NULL CHECK (available_quantity >= 0),
    equipment_status      TEXT    NOT NULL CHECK (equipment_status IN {_in_list(EQUIPMENT_STATUSES)}),
    last_maintenance_date TEXT,
    CHECK (available_quantity <= quantity),
    UNIQUE (hospital_id, department_id, equipment_name),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (department_id, hospital_id) REFERENCES departments (department_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS admissions (
    admission_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    hospital_id      INTEGER NOT NULL,
    department_id    INTEGER NOT NULL,
    doctor_id        INTEGER NOT NULL,
    patient_ref      TEXT    NOT NULL,
    admission_date   TEXT    NOT NULL,
    discharge_date   TEXT,
    admission_type   TEXT    NOT NULL CHECK (admission_type IN {_in_list(ADMISSION_TYPES)}),
    admission_status TEXT    NOT NULL CHECK (admission_status IN {_in_list(ADMISSION_STATUSES)}),
    bed_id           INTEGER,
    CHECK (discharge_date IS NULL OR discharge_date >= admission_date),
    CHECK (admission_status <> 'Discharged' OR discharge_date IS NOT NULL),
    CHECK (admission_status <> 'Admitted' OR bed_id IS NOT NULL),
    UNIQUE (patient_ref, admission_date),
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (department_id, hospital_id) REFERENCES departments (department_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (doctor_id, hospital_id) REFERENCES doctors (doctor_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (doctor_id, department_id) REFERENCES doctors (doctor_id, department_id)
        ON UPDATE CASCADE ON DELETE RESTRICT,
    FOREIGN KEY (bed_id, hospital_id) REFERENCES beds (bed_id, hospital_id)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- A bed can only be used by ONE active (Admitted) admission, and a patient can only
-- have ONE active admission at a time. Partial unique indexes enforce this inside SQLite.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_admission_per_bed
    ON admissions (bed_id) WHERE admission_status = 'Admitted' AND bed_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_admission_per_patient
    ON admissions (patient_ref) WHERE admission_status = 'Admitted';
"""


def init_database():
    """Create the tables if needed and insert sample data exactly once.

    'PRAGMA user_version' is a small number stored inside the database file.
    0 means "never seeded". After seeding we set it to 1, so sample data is never
    inserted again - even if the user later deletes every hospital."""
    connection = get_connection()
    try:
        connection.executescript(SCHEMA_SQL)
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        hospital_count = connection.execute("SELECT COUNT(*) FROM hospitals").fetchone()[0]
        if version == 0 and hospital_count == 0:
            seed_sample_data(connection)
        if version == 0:
            connection.execute("PRAGMA user_version = 1")
        connection.commit()
    except sqlite3.Error as error:
        connection.rollback()
        raise DatabaseError(f"Could not initialise the database: {error}") from error
    finally:
        connection.close()


# ---------------------------------------------------------------------------
# 3. Sample data
# ---------------------------------------------------------------------------
def seed_sample_data(connection):
    """Insert a realistic starter dataset (4 hospitals, 20 departments, 40 doctors, 100 beds,
    40 equipment records and 95 admissions). A fixed random seed keeps it reproducible."""
    rng = random.Random(2026)
    today = date.today()

    hospitals = [
        ("City General Hospital", "12 Station Road", "Mumbai", "+91 22 4000 1100",
         "info@citygeneral.example.org", "Government", 600, "1985-04-12",
         ["Cardiology", "Orthopedics", "Pediatrics", "Emergency", "General Medicine"]),
        ("Sunrise Multispecialty Hospital", "45 Lake View Avenue", "Pune", "+91 20 4100 2200",
         "contact@sunrisehospital.example.org", "Private", 350, "2003-09-01",
         ["Cardiology", "Neurology", "Oncology", "Radiology", "Emergency"]),
        ("LifeCare Teaching Hospital", "8 University Campus Road", "Bengaluru", "+91 80 4200 3300",
         "desk@lifecare.example.org", "Teaching", 500, "1996-01-20",
         ["Pediatrics", "Orthopedics", "Neurology", "General Medicine", "Radiology"]),
        ("Green Valley Community Hospital", "3 Market Street", "Nashik", "+91 253 400 4400",
         "hello@greenvalley.example.org", "Community", 150, "2011-06-15",
         ["General Medicine", "Emergency", "Pediatrics", "Orthopedics", "Oncology"]),
    ]
    specialization_for = {
        "Cardiology": "Cardiologist", "Orthopedics": "Orthopedic Surgeon", "Pediatrics": "Pediatrician",
        "Emergency": "Emergency Physician", "General Medicine": "General Physician",
        "Neurology": "Neurologist", "Oncology": "Oncologist", "Radiology": "Radiologist",
    }
    equipment_for = {
        "Cardiology": [("ECG Machine", "Diagnostic"), ("Defibrillator", "Life Support")],
        "Orthopedics": [("C-Arm X-Ray Unit", "Diagnostic"), ("Surgical Light", "Surgical")],
        "Pediatrics": [("Infant Incubator", "Life Support"), ("Nebulizer", "Therapeutic")],
        "Emergency": [("Ventilator", "Life Support"), ("Patient Monitor", "Monitoring")],
        "General Medicine": [("Infusion Pump", "Therapeutic"), ("Pulse Oximeter", "Monitoring")],
        "Neurology": [("EEG Machine", "Diagnostic"), ("Patient Monitor", "Monitoring")],
        "Oncology": [("Chemotherapy Infusion Pump", "Therapeutic"), ("Linear Accelerator", "Therapeutic")],
        "Radiology": [("CT Scanner", "Diagnostic"), ("Ultrasound Machine", "Diagnostic")],
    }
    doctor_names = [
        "Anita Deshmukh", "Rohan Mehta", "Priya Nair", "Vikram Singh", "Sneha Kulkarni", "Arjun Reddy",
        "Kavita Joshi", "Manish Gupta", "Neha Verma", "Sanjay Patil", "Divya Iyer", "Rahul Sharma",
        "Meera Pillai", "Amit Choudhary", "Pooja Bhatt", "Karan Malhotra", "Lakshmi Menon", "Suresh Rao",
        "Ritu Agarwal", "Nikhil Jain", "Shruti Kapoor", "Deepak Shah", "Aditi Banerjee", "Faisal Khan",
        "Swati Pawar", "Harish Naidu", "Tanvi Gokhale", "Ramesh Yadav", "Isha Saxena", "Gaurav Tiwari",
        "Nandini Rao", "Pranav Kulkarni", "Jyoti Mishra", "Abhishek Das", "Rekha Thomas", "Varun Bhatia",
        "Shalini Ghosh", "Omkar Jadhav", "Farah Sheikh", "Tarun Arora",
    ]
    rng.shuffle(doctor_names)
    name_iter = iter(doctor_names)
    bed_charge = {"General": 800, "Semi-Private": 1500, "Private": 2500, "ICU": 5000, "Emergency": 1200}

    department_index = 0
    departments = []  # (hospital_id, department_id)
    for (name, address, city, phone, email, h_type, capacity, established, dept_names) in hospitals:
        cursor = connection.execute(
            "INSERT INTO hospitals (hospital_name, address, city, contact_number, email, hospital_type,"
            " total_capacity, established_date) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, address, city, phone, email, h_type, capacity, established))
        hospital_id = cursor.lastrowid
        domain = email.split("@")[1]

        for floor_number, dept_name in enumerate(dept_names):
            pair = [next(name_iter), next(name_iter)]
            floor = "Ground Floor" if floor_number == 0 else f"Floor {floor_number}"
            cursor = connection.execute(
                "INSERT INTO departments (hospital_id, department_name, floor_location, contact_number,"
                " department_head) VALUES (?, ?, ?, ?, ?)",
                (hospital_id, dept_name, floor, f"+91 {rng.randint(20, 80)} 4{rng.randint(100, 999)} {rng.randint(1000, 9999)}",
                 pair[0]))
            department_id = cursor.lastrowid
            departments.append((hospital_id, department_id))

            # two doctors per department
            for doctor_name in pair:
                first, last = doctor_name.lower().split()
                connection.execute(
                    "INSERT INTO doctors (hospital_id, department_id, doctor_name, specialization,"
                    " contact_number, email, availability_status, consultation_fee, years_of_experience)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (hospital_id, department_id, doctor_name, specialization_for[dept_name],
                     f"+91 9{rng.randint(100000000, 999999999)}", f"{first}.{last}@{domain}",
                     "Available" if rng.random() < 0.8 else "Unavailable",
                     rng.choice([300, 500, 600, 800, 1000, 1200]), rng.randint(2, 30)))

            # five beds per department; the last bed of every 4th department is under maintenance
            for bed_number in range(5):
                bed_type = "Emergency" if dept_name == "Emergency" else \
                    ["General", "General", "Semi-Private", "Private", "ICU"][bed_number]
                status = "Maintenance" if (bed_number == 4 and department_index % 4 == 0) else "Available"
                connection.execute(
                    "INSERT INTO beds (hospital_id, department_id, ward_name, bed_type, bed_status, daily_charge)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (hospital_id, department_id, f"{dept_name} Ward {'A' if bed_number < 3 else 'B'}",
                     bed_type, status, bed_charge[bed_type]))

            # two equipment records per department
            for equipment_name, category in equipment_for[dept_name]:
                quantity = rng.randint(2, 12)
                roll = rng.random()
                if roll < 0.85:
                    status, available = "Operational", rng.randint(max(1, quantity // 3), quantity)
                elif roll < 0.95:
                    status, available = "Under Maintenance", rng.randint(0, max(0, quantity // 2))
                else:
                    status, available = "Out of Service", 0
                connection.execute(
                    "INSERT INTO equipment (hospital_id, department_id, equipment_name, equipment_category,"
                    " quantity, available_quantity, equipment_status, last_maintenance_date)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (hospital_id, department_id, equipment_name, category, quantity, available, status,
                     (today - timedelta(days=rng.randint(10, 300))).isoformat()))
            department_index += 1

    # Admissions: 55 historical (discharged) first, then up to 40 current ones that occupy beds.
    for number in range(95):
        hospital_id, department_id = rng.choice(departments)
        doctor_id = rng.choice(connection.execute(
            "SELECT doctor_id FROM doctors WHERE department_id = ?", (department_id,)).fetchall())[0]
        admission_type = rng.choices(ADMISSION_TYPES, weights=[4, 4, 1, 2])[0]
        patient_ref = f"PAT-{100001 + number}"
        current = number >= 55
        bed_id = None
        if current:
            free_beds = connection.execute(
                "SELECT bed_id FROM beds WHERE hospital_id = ? AND bed_status = 'Available'", (hospital_id,)
            ).fetchall()
            if free_beds:
                bed_id = rng.choice(free_beds)[0]
            else:
                current = False  # no free bed left in this hospital: record it as a past admission

        if current:
            admitted_on = today - timedelta(days=rng.randint(0, 9))
            connection.execute(
                "INSERT INTO admissions (hospital_id, department_id, doctor_id, patient_ref, admission_date,"
                " discharge_date, admission_type, admission_status, bed_id) VALUES (?, ?, ?, ?, ?, NULL, ?, 'Admitted', ?)",
                (hospital_id, department_id, doctor_id, patient_ref, admitted_on.isoformat(), admission_type, bed_id))
            connection.execute("UPDATE beds SET bed_status = 'Occupied' WHERE bed_id = ?", (bed_id,))
        else:
            admitted_on = today - timedelta(days=rng.randint(12, 180))
            discharged_on = admitted_on + timedelta(days=rng.randint(1, 10))
            past_bed = rng.choice(connection.execute(
                "SELECT bed_id FROM beds WHERE hospital_id = ?", (hospital_id,)).fetchall())[0]
            connection.execute(
                "INSERT INTO admissions (hospital_id, department_id, doctor_id, patient_ref, admission_date,"
                " discharge_date, admission_type, admission_status, bed_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'Discharged', ?)",
                (hospital_id, department_id, doctor_id, patient_ref, admitted_on.isoformat(),
                 discharged_on.isoformat(), admission_type, past_bed))


# ---------------------------------------------------------------------------
# 4. Validation helpers
# ---------------------------------------------------------------------------
def _text_value(data, key):
    value = data.get(key)
    return "" if value is None else str(value).strip()


def _clean_text(data, key, label, required=True, max_len=150):
    value = _text_value(data, key)
    if not value:
        if required:
            raise DatabaseError(f"{label} is required.")
        return None
    if len(value) > max_len:
        raise DatabaseError(f"{label} must be at most {max_len} characters.")
    return value


def _clean_int(data, key, label, minimum=0, maximum=None):
    value = _text_value(data, key)
    if not value:
        raise DatabaseError(f"{label} is required.")
    try:
        number = int(value)
    except ValueError:
        raise DatabaseError(f"{label} must be a whole number.") from None
    if number < minimum:
        raise DatabaseError(f"{label} cannot be less than {minimum}.")
    if maximum is not None and number > maximum:
        raise DatabaseError(f"{label} cannot be more than {maximum}.")
    return number


def _clean_float(data, key, label, minimum=0.0, maximum=1_000_000.0):
    value = _text_value(data, key)
    if not value:
        raise DatabaseError(f"{label} is required.")
    try:
        number = float(value)
    except ValueError:
        raise DatabaseError(f"{label} must be a number.") from None
    if not math.isfinite(number):
        raise DatabaseError(f"{label} must be a valid number.")
    if number < minimum:
        raise DatabaseError(f"{label} cannot be less than {minimum:g}.")
    if number > maximum:
        raise DatabaseError(f"{label} cannot be more than {maximum:g}.")
    return round(number, 2)


def _clean_date(data, key, label, required=True, allow_future=True):
    """Accept YYYY-MM-DD and return it in exactly that format (so text comparison = date comparison)."""
    value = _text_value(data, key)
    if not value:
        if required:
            raise DatabaseError(f"{label} is required (format YYYY-MM-DD).")
        return None
    try:
        parsed = datetime.strptime(value, DATE_FORMAT).date()
    except ValueError:
        raise DatabaseError(f"{label} must be a real date in the format YYYY-MM-DD.") from None
    if parsed.year < 1900:
        raise DatabaseError(f"{label} is too far in the past.")
    if not allow_future and parsed > date.today():
        raise DatabaseError(f"{label} cannot be in the future.")
    return parsed.isoformat()


def _clean_id(data, key, label, required=True):
    value = data.get(key)
    if value is None or str(value).strip() == "":
        if required:
            raise DatabaseError(f"Please select a {label.lower()}.")
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise DatabaseError(f"Invalid {label.lower()} selection.") from None


def _clean_choice(data, key, label, allowed):
    value = _text_value(data, key)
    if value not in allowed:
        raise DatabaseError(f"{label} must be one of: {', '.join(allowed)}.")
    return value


def _clean_phone(data, key="contact_number", label="Contact number"):
    value = _clean_text(data, key, label, max_len=25)
    digits = re.sub(r"\D", "", value)
    if not re.fullmatch(r"\+?[0-9][0-9\s\-]*", value) or not 7 <= len(digits) <= 15:
        raise DatabaseError(f"{label} must contain 7-15 digits (spaces, '-' and a leading '+' are allowed).")
    return value


def _clean_email(data, key="email", label="Email"):
    value = _clean_text(data, key, label, max_len=100).lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
        raise DatabaseError(f"{label} is not a valid email address.")
    return value


# ---------------------------------------------------------------------------
# Small generic helpers shared by all CRUD functions
# ---------------------------------------------------------------------------
def _fetch_one(connection, table, pk_column, record_id):
    row = connection.execute(f"SELECT * FROM {table} WHERE {pk_column} = ?", (record_id,)).fetchone()
    return dict(row) if row else None


def _count(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()[0]


def _insert(connection, table, clean):
    """Insert a validated dict. Column names come from our own validators (never from the user);
    the VALUES are always passed as parameters."""
    columns = ", ".join(clean)
    marks = ", ".join("?" for _ in clean)
    cursor = connection.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})", tuple(clean.values()))
    return cursor.lastrowid


def _update(connection, table, pk_column, record_id, clean):
    assignments = ", ".join(f"{column} = ?" for column in clean)
    cursor = connection.execute(
        f"UPDATE {table} SET {assignments} WHERE {pk_column} = ?", tuple(clean.values()) + (record_id,))
    if cursor.rowcount == 0:
        raise DatabaseError("This record no longer exists. Please refresh the table.")


def _delete_if_unused(table, pk_column, record_id, record_name, dependents):
    """Delete a row only if no other table points at it. 'dependents' is a list of
    (friendly name, table, column). Nothing is ever deleted silently."""
    with db_session(write=True) as connection:
        if _fetch_one(connection, table, pk_column, record_id) is None:
            raise DatabaseError(f"This {record_name} no longer exists. Please refresh the table.")
        for friendly_name, dep_table, dep_column in dependents:
            total = _count(connection, f"SELECT COUNT(*) FROM {dep_table} WHERE {dep_column} = ?", (record_id,))
            if total:
                raise DatabaseError(
                    f"Cannot delete this {record_name}: {total} {friendly_name} record(s) are linked to it.\n"
                    f"Remove or reassign them first.")
        connection.execute(f"DELETE FROM {table} WHERE {pk_column} = ?", (record_id,))


def _check_department_in_hospital(connection, department_id, hospital_id):
    """Make sure both exist and the department really belongs to the hospital."""
    if _fetch_one(connection, "hospitals", "hospital_id", hospital_id) is None:
        raise DatabaseError("The selected hospital does not exist.")
    department = _fetch_one(connection, "departments", "department_id", department_id)
    if department is None:
        raise DatabaseError("The selected department does not exist.")
    if department["hospital_id"] != hospital_id:
        raise DatabaseError("The selected department does not belong to the selected hospital.")


def _department_usage(connection, department_id):
    return sum(_count(connection, f"SELECT COUNT(*) FROM {table} WHERE department_id = ?", (department_id,))
               for table in ("doctors", "beds", "equipment", "admissions"))


def _run_select(sql, params=()):
    with db_session() as connection:
        return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _like(text):
    return f"%{text.strip()}%"


def _where(conditions):
    return (" WHERE " + " AND ".join(conditions)) if conditions else ""


# ---------------------------------------------------------------------------
# 5A. Hospitals
# ---------------------------------------------------------------------------
def validate_hospital(data):
    return {
        "hospital_name": _clean_text(data, "hospital_name", "Hospital name"),
        "address": _clean_text(data, "address", "Address", max_len=250),
        "city": _clean_text(data, "city", "City", max_len=80),
        "contact_number": _clean_phone(data),
        "email": _clean_email(data),
        "hospital_type": _clean_choice(data, "hospital_type", "Hospital type", HOSPITAL_TYPES),
        "total_capacity": _clean_int(data, "total_capacity", "Total capacity", minimum=1, maximum=100000),
        "established_date": _clean_date(data, "established_date", "Established date", allow_future=False),
    }


def add_hospital(data):
    clean = validate_hospital(data)
    with db_session(write=True) as connection:
        return _insert(connection, "hospitals", clean)


def get_hospital(hospital_id):
    with db_session() as connection:
        return _fetch_one(connection, "hospitals", "hospital_id", hospital_id)


def update_hospital(hospital_id, data):
    clean = validate_hospital(data)
    with db_session(write=True) as connection:
        bed_total = _count(connection, "SELECT COUNT(*) FROM beds WHERE hospital_id = ?", (hospital_id,))
        if clean["total_capacity"] < bed_total:
            raise DatabaseError(f"Total capacity cannot be lower than the {bed_total} beds already registered.")
        _update(connection, "hospitals", "hospital_id", hospital_id, clean)


def delete_hospital(hospital_id):
    _delete_if_unused("hospitals", "hospital_id", hospital_id, "hospital", [
        ("department", "departments", "hospital_id"), ("doctor", "doctors", "hospital_id"),
        ("bed", "beds", "hospital_id"), ("equipment", "equipment", "hospital_id"),
        ("admission", "admissions", "hospital_id")])


def list_hospitals(search="", hospital_type=None, city=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("(hospital_name LIKE ? OR city LIKE ? OR hospital_type LIKE ?)")
        params += [_like(search)] * 3
    if hospital_type:
        conditions.append("hospital_type = ?")
        params.append(hospital_type)
    if city:
        conditions.append("city = ?")
        params.append(city)
    sql = ("SELECT hospital_id, hospital_name, address, city, contact_number, email, hospital_type,"
           " total_capacity, established_date FROM hospitals" + _where(conditions) + " ORDER BY hospital_name")
    return _run_select(sql, params)


# ---------------------------------------------------------------------------
# 5B. Departments
# ---------------------------------------------------------------------------
def validate_department(data):
    return {
        "hospital_id": _clean_id(data, "hospital_id", "Hospital"),
        "department_name": _clean_text(data, "department_name", "Department name", max_len=100),
        "floor_location": _clean_text(data, "floor_location", "Floor / location", max_len=100),
        "contact_number": _clean_phone(data),
        "department_head": _clean_text(data, "department_head", "Department head", max_len=100),
    }


def add_department(data):
    clean = validate_department(data)
    with db_session(write=True) as connection:
        if _fetch_one(connection, "hospitals", "hospital_id", clean["hospital_id"]) is None:
            raise DatabaseError("The selected hospital does not exist.")
        return _insert(connection, "departments", clean)


def get_department(department_id):
    with db_session() as connection:
        return _fetch_one(connection, "departments", "department_id", department_id)


def update_department(department_id, data):
    clean = validate_department(data)
    with db_session(write=True) as connection:
        old = _fetch_one(connection, "departments", "department_id", department_id)
        if old is None:
            raise DatabaseError("This department no longer exists. Please refresh the table.")
        if _fetch_one(connection, "hospitals", "hospital_id", clean["hospital_id"]) is None:
            raise DatabaseError("The selected hospital does not exist.")
        if old["hospital_id"] != clean["hospital_id"] and _department_usage(connection, department_id):
            raise DatabaseError("This department already has doctors, beds, equipment or admissions, "
                                "so it cannot be moved to another hospital.")
        _update(connection, "departments", "department_id", department_id, clean)


def delete_department(department_id):
    _delete_if_unused("departments", "department_id", department_id, "department", [
        ("doctor", "doctors", "department_id"), ("bed", "beds", "department_id"),
        ("equipment", "equipment", "department_id"), ("admission", "admissions", "department_id")])


def list_departments(search="", hospital_id=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("(d.department_name LIKE ? OR d.department_head LIKE ?)")
        params += [_like(search)] * 2
    if hospital_id:
        conditions.append("d.hospital_id = ?")
        params.append(hospital_id)
    sql = ("SELECT d.department_id, h.hospital_name, d.department_name, d.floor_location, d.contact_number,"
           " d.department_head FROM departments d JOIN hospitals h ON h.hospital_id = d.hospital_id"
           + _where(conditions) + " ORDER BY h.hospital_name, d.department_name")
    return _run_select(sql, params)


# ---------------------------------------------------------------------------
# 5C. Doctors
# ---------------------------------------------------------------------------
def validate_doctor(data):
    return {
        "hospital_id": _clean_id(data, "hospital_id", "Hospital"),
        "department_id": _clean_id(data, "department_id", "Department"),
        "doctor_name": _clean_text(data, "doctor_name", "Doctor name", max_len=100),
        "specialization": _clean_text(data, "specialization", "Specialization", max_len=100),
        "contact_number": _clean_phone(data),
        "email": _clean_email(data),
        "availability_status": _clean_choice(data, "availability_status", "Availability", DOCTOR_STATUSES),
        "consultation_fee": _clean_float(data, "consultation_fee", "Consultation fee"),
        "years_of_experience": _clean_int(data, "years_of_experience", "Years of experience", maximum=70),
    }


def add_doctor(data):
    clean = validate_doctor(data)
    with db_session(write=True) as connection:
        _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])
        return _insert(connection, "doctors", clean)


def get_doctor(doctor_id):
    with db_session() as connection:
        return _fetch_one(connection, "doctors", "doctor_id", doctor_id)


def update_doctor(doctor_id, data):
    clean = validate_doctor(data)
    with db_session(write=True) as connection:
        old = _fetch_one(connection, "doctors", "doctor_id", doctor_id)
        if old is None:
            raise DatabaseError("This doctor no longer exists. Please refresh the table.")
        _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])
        moved = (old["hospital_id"], old["department_id"]) != (clean["hospital_id"], clean["department_id"])
        if moved and _count(connection, "SELECT COUNT(*) FROM admissions WHERE doctor_id = ?", (doctor_id,)):
            raise DatabaseError("This doctor has admissions on record, so the hospital/department cannot change.")
        _update(connection, "doctors", "doctor_id", doctor_id, clean)


def delete_doctor(doctor_id):
    _delete_if_unused("doctors", "doctor_id", doctor_id, "doctor", [("admission", "admissions", "doctor_id")])


def list_doctors(search="", hospital_id=None, department_id=None, specialization=None, availability_status=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("(d.doctor_name LIKE ? OR d.specialization LIKE ?)")
        params += [_like(search)] * 2
    if hospital_id:
        conditions.append("d.hospital_id = ?")
        params.append(hospital_id)
    if department_id:
        conditions.append("d.department_id = ?")
        params.append(department_id)
    if specialization:
        conditions.append("d.specialization = ?")
        params.append(specialization)
    if availability_status:
        conditions.append("d.availability_status = ?")
        params.append(availability_status)
    sql = ("SELECT d.doctor_id, d.doctor_name, d.specialization, h.hospital_name, dep.department_name,"
           " d.contact_number, d.email, d.availability_status, d.consultation_fee, d.years_of_experience"
           " FROM doctors d JOIN hospitals h ON h.hospital_id = d.hospital_id"
           " JOIN departments dep ON dep.department_id = d.department_id"
           + _where(conditions) + " ORDER BY d.doctor_name")
    return _run_select(sql, params)


# ---------------------------------------------------------------------------
# 5D. Beds
# ---------------------------------------------------------------------------
def _validate_bed(connection, data, bed_id=None):
    clean = {
        "hospital_id": _clean_id(data, "hospital_id", "Hospital"),
        "department_id": _clean_id(data, "department_id", "Department"),
        "ward_name": _clean_text(data, "ward_name", "Ward name", max_len=100),
        "bed_type": _clean_choice(data, "bed_type", "Bed type", BED_TYPES),
        "bed_status": _clean_choice(data, "bed_status", "Bed status", BED_STATUSES),
        "daily_charge": _clean_float(data, "daily_charge", "Daily charge"),
    }
    _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])

    linked = active = 0
    if bed_id is not None:
        old = _fetch_one(connection, "beds", "bed_id", bed_id)
        if old is None:
            raise DatabaseError("This bed no longer exists. Please refresh the table.")
        linked = _count(connection, "SELECT COUNT(*) FROM admissions WHERE bed_id = ?", (bed_id,))
        active = _count(connection, "SELECT COUNT(*) FROM admissions WHERE bed_id = ? AND admission_status = 'Admitted'",
                        (bed_id,))
        if linked and old["hospital_id"] != clean["hospital_id"]:
            raise DatabaseError("This bed has admissions on record, so it cannot be moved to another hospital.")

    # Occupied/Available is controlled by admissions, so the two must never disagree.
    if active and clean["bed_status"] != "Occupied":
        raise DatabaseError("This bed has an active admission, so it must stay 'Occupied'. Discharge the patient first.")
    if not active and clean["bed_status"] == "Occupied":
        raise DatabaseError("A bed becomes 'Occupied' automatically when an admitted patient is assigned to it. "
                            "Choose 'Available' or 'Maintenance' here.")

    capacity = _fetch_one(connection, "hospitals", "hospital_id", clean["hospital_id"])["total_capacity"]
    others = _count(connection, "SELECT COUNT(*) FROM beds WHERE hospital_id = ? AND bed_id <> ?",
                    (clean["hospital_id"], bed_id if bed_id is not None else -1))
    if others >= capacity:
        raise DatabaseError(f"This hospital's total capacity ({capacity}) is already used up by registered beds.")
    return clean


def add_bed(data):
    with db_session(write=True) as connection:
        clean = _validate_bed(connection, data)
        return _insert(connection, "beds", clean)


def get_bed(bed_id):
    with db_session() as connection:
        return _fetch_one(connection, "beds", "bed_id", bed_id)


def update_bed(bed_id, data):
    with db_session(write=True) as connection:
        clean = _validate_bed(connection, data, bed_id)
        _update(connection, "beds", "bed_id", bed_id, clean)


def delete_bed(bed_id):
    _delete_if_unused("beds", "bed_id", bed_id, "bed", [("admission", "admissions", "bed_id")])


def list_beds(search="", hospital_id=None, department_id=None, bed_type=None, bed_status=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("(CAST(b.bed_id AS TEXT) LIKE ? OR b.ward_name LIKE ?)")
        params += [_like(search)] * 2
    if hospital_id:
        conditions.append("b.hospital_id = ?")
        params.append(hospital_id)
    if department_id:
        conditions.append("b.department_id = ?")
        params.append(department_id)
    if bed_type:
        conditions.append("b.bed_type = ?")
        params.append(bed_type)
    if bed_status:
        conditions.append("b.bed_status = ?")
        params.append(bed_status)
    sql = ("SELECT b.bed_id, h.hospital_name, dep.department_name, b.ward_name, b.bed_type, b.bed_status,"
           " b.daily_charge FROM beds b JOIN hospitals h ON h.hospital_id = b.hospital_id"
           " JOIN departments dep ON dep.department_id = b.department_id"
           + _where(conditions) + " ORDER BY b.bed_id")
    return _run_select(sql, params)


def _refresh_bed_status(connection, bed_id):
    """Keep a bed's status consistent with admissions: Occupied while an admitted patient uses it,
    back to Available afterwards. Beds in Maintenance are never changed here."""
    if bed_id is None:
        return
    bed = _fetch_one(connection, "beds", "bed_id", bed_id)
    if bed is None:
        return
    active = _count(connection, "SELECT COUNT(*) FROM admissions WHERE bed_id = ? AND admission_status = 'Admitted'",
                    (bed_id,))
    if active and bed["bed_status"] != "Occupied":
        connection.execute("UPDATE beds SET bed_status = 'Occupied' WHERE bed_id = ?", (bed_id,))
    elif not active and bed["bed_status"] == "Occupied":
        connection.execute("UPDATE beds SET bed_status = 'Available' WHERE bed_id = ?", (bed_id,))


# ---------------------------------------------------------------------------
# 5E. Equipment
# ---------------------------------------------------------------------------
def validate_equipment(data):
    clean = {
        "hospital_id": _clean_id(data, "hospital_id", "Hospital"),
        "department_id": _clean_id(data, "department_id", "Department"),
        "equipment_name": _clean_text(data, "equipment_name", "Equipment name", max_len=100),
        "equipment_category": _clean_choice(data, "equipment_category", "Category", EQUIPMENT_CATEGORIES),
        "quantity": _clean_int(data, "quantity", "Total quantity", maximum=100000),
        "available_quantity": _clean_int(data, "available_quantity", "Available quantity", maximum=100000),
        "equipment_status": _clean_choice(data, "equipment_status", "Equipment status", EQUIPMENT_STATUSES),
        "last_maintenance_date": _clean_date(data, "last_maintenance_date", "Last maintenance date",
                                             required=False, allow_future=False),
    }
    if clean["available_quantity"] > clean["quantity"]:
        raise DatabaseError("Available quantity cannot be greater than the total quantity.")
    return clean


def add_equipment(data):
    clean = validate_equipment(data)
    with db_session(write=True) as connection:
        _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])
        return _insert(connection, "equipment", clean)


def get_equipment(equipment_id):
    with db_session() as connection:
        return _fetch_one(connection, "equipment", "equipment_id", equipment_id)


def update_equipment(equipment_id, data):
    clean = validate_equipment(data)
    with db_session(write=True) as connection:
        _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])
        _update(connection, "equipment", "equipment_id", equipment_id, clean)


def delete_equipment(equipment_id):
    _delete_if_unused("equipment", "equipment_id", equipment_id, "equipment record", [])


def list_equipment(search="", hospital_id=None, department_id=None, equipment_category=None, equipment_status=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("e.equipment_name LIKE ?")
        params.append(_like(search))
    if hospital_id:
        conditions.append("e.hospital_id = ?")
        params.append(hospital_id)
    if department_id:
        conditions.append("e.department_id = ?")
        params.append(department_id)
    if equipment_category:
        conditions.append("e.equipment_category = ?")
        params.append(equipment_category)
    if equipment_status:
        conditions.append("e.equipment_status = ?")
        params.append(equipment_status)
    sql = ("SELECT e.equipment_id, h.hospital_name, dep.department_name, e.equipment_name, e.equipment_category,"
           " e.quantity, e.available_quantity, e.equipment_status, e.last_maintenance_date"
           " FROM equipment e JOIN hospitals h ON h.hospital_id = e.hospital_id"
           " JOIN departments dep ON dep.department_id = e.department_id"
           + _where(conditions) + " ORDER BY e.equipment_name, h.hospital_name")
    return _run_select(sql, params)


# ---------------------------------------------------------------------------
# 5F. Admissions
# ---------------------------------------------------------------------------
def _validate_admission(connection, data, admission_id=None):
    """Check every business rule for an admission before it is saved."""
    clean = {
        "hospital_id": _clean_id(data, "hospital_id", "Hospital"),
        "department_id": _clean_id(data, "department_id", "Department"),
        "doctor_id": _clean_id(data, "doctor_id", "Doctor"),
        "patient_ref": _clean_text(data, "patient_ref", "Patient reference number", max_len=30).upper(),
        "admission_date": _clean_date(data, "admission_date", "Admission date"),
        "discharge_date": _clean_date(data, "discharge_date", "Discharge date", required=False),
        "admission_type": _clean_choice(data, "admission_type", "Admission type", ADMISSION_TYPES),
        "admission_status": _clean_choice(data, "admission_status", "Admission status", ADMISSION_STATUSES),
        "bed_id": _clean_id(data, "bed_id", "Bed", required=False),
    }
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_/]{2,29}", clean["patient_ref"]):
        raise DatabaseError("Patient reference must be 3-30 characters (letters, numbers, - _ /). "
                            "Use a reference code, not the patient's real name.")

    _check_department_in_hospital(connection, clean["department_id"], clean["hospital_id"])
    doctor = _fetch_one(connection, "doctors", "doctor_id", clean["doctor_id"])
    if doctor is None:
        raise DatabaseError("The selected doctor does not exist.")
    if doctor["hospital_id"] != clean["hospital_id"]:
        raise DatabaseError("The selected doctor does not work in the selected hospital.")
    if doctor["department_id"] != clean["department_id"]:
        raise DatabaseError("The selected doctor does not belong to the selected department.")

    status = clean["admission_status"]
    if status == "Discharged" and clean["discharge_date"] is None:
        raise DatabaseError("A discharge date is required when the status is 'Discharged'.")
    if status == "Admitted" and clean["discharge_date"] is not None:
        raise DatabaseError("Leave the discharge date empty while the patient is still 'Admitted'.")
    if clean["discharge_date"] and clean["discharge_date"] < clean["admission_date"]:
        raise DatabaseError("The discharge date cannot be earlier than the admission date.")

    own_id = admission_id if admission_id is not None else -1
    if clean["bed_id"] is not None:
        bed = _fetch_one(connection, "beds", "bed_id", clean["bed_id"])
        if bed is None:
            raise DatabaseError("The selected bed does not exist.")
        if bed["hospital_id"] != clean["hospital_id"]:
            raise DatabaseError("The selected bed does not belong to the selected hospital.")
    elif status == "Admitted":
        raise DatabaseError("Please select a bed for an admitted patient.")

    if status == "Admitted":
        if bed["bed_status"] == "Maintenance":
            raise DatabaseError("The selected bed is under maintenance and cannot be assigned.")
        taken = _count(connection, "SELECT COUNT(*) FROM admissions WHERE bed_id = ? AND admission_status = 'Admitted'"
                       " AND admission_id <> ?", (clean["bed_id"], own_id))
        if taken:
            raise DatabaseError("This bed is already assigned to another active admission.")
        duplicate = _count(connection, "SELECT COUNT(*) FROM admissions WHERE patient_ref = ? AND"
                           " admission_status = 'Admitted' AND admission_id <> ?", (clean["patient_ref"], own_id))
        if duplicate:
            raise DatabaseError("This patient reference already has an active admission.")
    return clean


def add_admission(data):
    """Insert the admission AND update the bed status inside one transaction."""
    with db_session(write=True) as connection:
        clean = _validate_admission(connection, data)
        new_id = _insert(connection, "admissions", clean)
        _refresh_bed_status(connection, clean["bed_id"])
        return new_id


def get_admission(admission_id):
    with db_session() as connection:
        return _fetch_one(connection, "admissions", "admission_id", admission_id)


def update_admission(admission_id, data):
    """Update the admission, then re-check both the OLD and the NEW bed (the bed may have changed)."""
    with db_session(write=True) as connection:
        old = _fetch_one(connection, "admissions", "admission_id", admission_id)
        if old is None:
            raise DatabaseError("This admission no longer exists. Please refresh the table.")
        clean = _validate_admission(connection, data, admission_id)
        _update(connection, "admissions", "admission_id", admission_id, clean)
        _refresh_bed_status(connection, old["bed_id"])
        _refresh_bed_status(connection, clean["bed_id"])


def delete_admission(admission_id):
    """Delete an admission and free its bed (if it was the one keeping the bed occupied)."""
    with db_session(write=True) as connection:
        old = _fetch_one(connection, "admissions", "admission_id", admission_id)
        if old is None:
            raise DatabaseError("This admission no longer exists. Please refresh the table.")
        connection.execute("DELETE FROM admissions WHERE admission_id = ?", (admission_id,))
        _refresh_bed_status(connection, old["bed_id"])


def list_admissions(search="", hospital_id=None, department_id=None, admission_status=None,
                    date_from=None, date_to=None, limit=None):
    conditions, params = [], []
    if search and search.strip():
        conditions.append("(a.patient_ref LIKE ? OR CAST(a.admission_id AS TEXT) LIKE ?)")
        params += [_like(search)] * 2
    if hospital_id:
        conditions.append("a.hospital_id = ?")
        params.append(hospital_id)
    if department_id:
        conditions.append("a.department_id = ?")
        params.append(department_id)
    if admission_status:
        conditions.append("a.admission_status = ?")
        params.append(admission_status)
    if date_from and date_from.strip():
        conditions.append("a.admission_date >= ?")
        params.append(date_from.strip())
    if date_to and date_to.strip():
        conditions.append("a.admission_date <= ?")
        params.append(date_to.strip())
    sql = ("SELECT a.admission_id, a.patient_ref, h.hospital_name, dep.department_name, doc.doctor_name, a.bed_id,"
           " a.admission_date, a.discharge_date, a.admission_type, a.admission_status"
           " FROM admissions a JOIN hospitals h ON h.hospital_id = a.hospital_id"
           " JOIN departments dep ON dep.department_id = a.department_id"
           " JOIN doctors doc ON doc.doctor_id = a.doctor_id"
           + _where(conditions) + " ORDER BY a.admission_date DESC, a.admission_id DESC")
    if limit:
        sql += f" LIMIT {int(limit)}"
    return _run_select(sql, params)


# ---------------------------------------------------------------------------
# 6. Dropdown option helpers (used by forms and filters in main.py)
# ---------------------------------------------------------------------------
def get_hospital_options():
    """[(hospital_id, label), ...]"""
    rows = _run_select("SELECT hospital_id, hospital_name, city FROM hospitals ORDER BY hospital_name, city")
    return [(row["hospital_id"], f"{row['hospital_name']} ({row['city']})") for row in rows]


def get_department_options(hospital_id=None):
    """Departments of one hospital, or all departments (with the hospital name) when none is chosen."""
    if hospital_id:
        rows = _run_select("SELECT department_id, department_name FROM departments WHERE hospital_id = ?"
                           " ORDER BY department_name", (hospital_id,))
        return [(row["department_id"], row["department_name"]) for row in rows]
    rows = _run_select("SELECT d.department_id, d.department_name, h.hospital_name FROM departments d"
                       " JOIN hospitals h ON h.hospital_id = d.hospital_id ORDER BY d.department_name, h.hospital_name")
    return [(row["department_id"], f"{row['department_name']} - {row['hospital_name']}") for row in rows]


def get_doctor_options(hospital_id=None, department_id=None):
    """Doctors working in the chosen hospital and department (empty until both are chosen)."""
    if not hospital_id or not department_id:
        return []
    rows = _run_select("SELECT doctor_id, doctor_name, specialization FROM doctors WHERE hospital_id = ?"
                       " AND department_id = ? ORDER BY doctor_name", (hospital_id, department_id))
    return [(row["doctor_id"], f"Dr. {row['doctor_name']} ({row['specialization']}) [ID {row['doctor_id']}]")
            for row in rows]


def get_bed_options(hospital_id=None, admission_id=None):
    """Beds of the chosen hospital that can be assigned: all 'Available' beds, plus the bed already
    used by the admission being edited."""
    if not hospital_id:
        return []
    rows = _run_select(
        "SELECT b.bed_id, b.ward_name, b.bed_type, dep.department_name FROM beds b"
        " JOIN departments dep ON dep.department_id = b.department_id"
        " WHERE b.hospital_id = ? AND (b.bed_status = 'Available' OR b.bed_id = ("
        "   SELECT bed_id FROM admissions WHERE admission_id = ?)) ORDER BY b.bed_id",
        (hospital_id, admission_id if admission_id is not None else -1))
    return [(row["bed_id"], f"Bed #{row['bed_id']} - {row['ward_name']} ({row['bed_type']}, {row['department_name']})")
            for row in rows]


_DISTINCT_ALLOWED = {("hospitals", "city"), ("hospitals", "hospital_type"), ("doctors", "specialization"),
                     ("doctors", "availability_status"), ("equipment", "equipment_category"),
                     ("equipment", "equipment_status"), ("beds", "bed_type"), ("beds", "bed_status"),
                     ("admissions", "admission_status")}


def get_distinct_values(table, column):
    """Sorted unique values of a column (for filter dropdowns). Only whitelisted columns are allowed."""
    if (table, column) not in _DISTINCT_ALLOWED:
        raise DatabaseError("Unsupported filter column.")
    rows = _run_select(f"SELECT DISTINCT {column} AS value FROM {table} WHERE {column} IS NOT NULL ORDER BY {column}")
    return [row["value"] for row in rows]


# ---------------------------------------------------------------------------
# 7. Dashboard + analytics queries
# ---------------------------------------------------------------------------
def get_dashboard_stats():
    """All dashboard card values, calculated live from the tables."""
    with db_session() as connection:
        def one(sql):
            return connection.execute(sql).fetchone()[0]

        stats = {
            "total_hospitals": one("SELECT COUNT(*) FROM hospitals"),
            "total_departments": one("SELECT COUNT(*) FROM departments"),
            "total_doctors": one("SELECT COUNT(*) FROM doctors"),
            "available_doctors": one("SELECT COUNT(*) FROM doctors WHERE availability_status = 'Available'"),
            "total_beds": one("SELECT COUNT(*) FROM beds"),
            "available_beds": one("SELECT COUNT(*) FROM beds WHERE bed_status = 'Available'"),
            "occupied_beds": one("SELECT COUNT(*) FROM beds WHERE bed_status = 'Occupied'"),
            "total_equipment": one("SELECT COUNT(*) FROM equipment"),
            "available_equipment_qty": one("SELECT COALESCE(SUM(available_quantity), 0) FROM equipment"),
            "current_admissions": one("SELECT COUNT(*) FROM admissions WHERE admission_status = 'Admitted'"),
        }
    total = stats["total_beds"]
    stats["occupancy_pct"] = round(stats["occupied_beds"] * 100.0 / total, 1) if total else 0.0
    return stats


# Each query returns a small table that main.py turns into a Pandas DataFrame.
ANALYTICS_QUERIES = {
    "bed_status":
        "SELECT bed_status, COUNT(*) AS count FROM beds GROUP BY bed_status",
    "hospital_beds":
        "SELECT h.hospital_name AS hospital,"
        " COALESCE(SUM(b.bed_status = 'Occupied'), 0) AS occupied,"
        " COALESCE(SUM(b.bed_status = 'Available'), 0) AS available,"
        " COALESCE(SUM(b.bed_status = 'Maintenance'), 0) AS maintenance"
        " FROM hospitals h LEFT JOIN beds b ON b.hospital_id = h.hospital_id"
        " GROUP BY h.hospital_id ORDER BY h.hospital_name",
    "department_beds":
        "SELECT d.department_name AS department,"
        " COALESCE(SUM(b.bed_status = 'Occupied'), 0) AS occupied,"
        " COALESCE(SUM(b.bed_status = 'Available'), 0) AS available,"
        " COALESCE(SUM(b.bed_status = 'Maintenance'), 0) AS maintenance"
        " FROM departments d LEFT JOIN beds b ON b.department_id = d.department_id"
        " GROUP BY d.department_name ORDER BY d.department_name",
    "specialization":
        "SELECT specialization, COUNT(*) AS doctors FROM doctors GROUP BY specialization ORDER BY doctors DESC",
    "doctor_availability":
        "SELECT availability_status, COUNT(*) AS count FROM doctors GROUP BY availability_status",
    "equipment_category":
        "SELECT equipment_category AS category, SUM(quantity) AS total_quantity,"
        " SUM(available_quantity) AS available_quantity FROM equipment GROUP BY equipment_category"
        " ORDER BY total_quantity DESC",
    "equipment_by_hospital":
        "SELECT h.hospital_name AS hospital, COALESCE(SUM(e.quantity), 0) AS total_quantity,"
        " COALESCE(SUM(e.available_quantity), 0) AS available_quantity"
        " FROM hospitals h LEFT JOIN equipment e ON e.hospital_id = h.hospital_id"
        " GROUP BY h.hospital_id ORDER BY h.hospital_name",
    "admission_dates":
        "SELECT admission_date FROM admissions ORDER BY admission_date",
    "admissions_by_hospital":
        "SELECT h.hospital_name AS hospital, COUNT(a.admission_id) AS total_admissions,"
        " COALESCE(SUM(a.admission_status = 'Admitted'), 0) AS current_admissions"
        " FROM hospitals h LEFT JOIN admissions a ON a.hospital_id = h.hospital_id"
        " GROUP BY h.hospital_id ORDER BY h.hospital_name",
    "hospital_summary":
        "SELECT h.hospital_name AS hospital, h.city,"
        " (SELECT COUNT(*) FROM departments x WHERE x.hospital_id = h.hospital_id) AS departments,"
        " (SELECT COUNT(*) FROM doctors x WHERE x.hospital_id = h.hospital_id) AS doctors,"
        " (SELECT COUNT(*) FROM beds x WHERE x.hospital_id = h.hospital_id) AS total_beds,"
        " (SELECT COUNT(*) FROM beds x WHERE x.hospital_id = h.hospital_id AND x.bed_status = 'Occupied') AS occupied_beds,"
        " (SELECT COALESCE(SUM(x.quantity), 0) FROM equipment x WHERE x.hospital_id = h.hospital_id) AS equipment_units,"
        " (SELECT COUNT(*) FROM admissions x WHERE x.hospital_id = h.hospital_id) AS total_admissions,"
        " (SELECT COUNT(*) FROM admissions x WHERE x.hospital_id = h.hospital_id AND x.admission_status = 'Admitted')"
        " AS current_admissions FROM hospitals h ORDER BY h.hospital_name",
}


def run_analytics_query(key):
    """Run one of the fixed analytics queries. Returns (column_names, list_of_row_tuples)."""
    if key not in ANALYTICS_QUERIES:
        raise DatabaseError(f"Unknown analytics query: {key}")
    with db_session() as connection:
        cursor = connection.execute(ANALYTICS_QUERIES[key])
        columns = [description[0] for description in cursor.description]
        rows = [tuple(row) for row in cursor.fetchall()]
    return columns, rows
