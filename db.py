"""Database layer for the Car Rental System (SQLite).

Holds the schema, demo seed data, and the reservation availability check
used by UI-03 (Reserve a Car) and functional requirement #10.
"""
import sqlite3
from datetime import date, datetime, time, timedelta

from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('customer', 'staff'))
);

CREATE TABLE IF NOT EXISTS vehicles (
    id           TEXT PRIMARY KEY,              -- e.g. V001
    name         TEXT NOT NULL,
    type         TEXT NOT NULL,                 -- Sedan, SUV, Hatchback, Truck
    category     TEXT NOT NULL,                 -- Economy, Standard, Premium, Luxury
    price_per_day INTEGER NOT NULL,
    seats        INTEGER NOT NULL,
    transmission TEXT NOT NULL,
    fuel_type    TEXT NOT NULL,
    mileage_km   INTEGER NOT NULL,
    status       TEXT NOT NULL DEFAULT 'Available'
                 CHECK (status IN ('Available', 'Maintenance')),
    last_service_km INTEGER NOT NULL DEFAULT 0     -- odometer at last service (REP-02)
);

CREATE TABLE IF NOT EXISTS reservations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    vehicle_id  TEXT NOT NULL REFERENCES vehicles(id),
    pickup_date TEXT NOT NULL,                  -- ISO yyyy-mm-dd
    return_date TEXT NOT NULL,
    total_price INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'Confirmed'
                CHECK (status IN ('Confirmed', 'Cancelled')),
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    km_driven   INTEGER                         -- logged by staff when the car is returned (REP-02)
);

-- Reservation IDs display as R-1001, R-1002, ...
INSERT OR IGNORE INTO sqlite_sequence (name, seq) VALUES ('reservations', 1000);
"""

TYPES = ["Sedan", "SUV", "Hatchback", "Truck"]
CATEGORIES = ["Economy", "Standard", "Premium", "Luxury"]

SEED_VEHICLES = [
    # id, name, type, category, price, seats, transmission, fuel, mileage, status
    ("V001", "Toyota Camry", "Sedan", "Economy", 45, 5, "Automatic", "Petrol", 28000, "Available"),
    ("V002", "Honda CR-V", "SUV", "Standard", 65, 5, "Automatic", "Petrol", 34500, "Available"),
    ("V003", "Ford Explorer", "SUV", "Premium", 85, 7, "Automatic", "Petrol", 41200, "Available"),
    ("V004", "BMW 3 Series", "Sedan", "Luxury", 120, 5, "Automatic", "Petrol", 18900, "Available"),
    ("V005", "Toyota RAV4", "SUV", "Standard", 70, 5, "Automatic", "Hybrid", 22300, "Available"),
    ("V006", "Volkswagen Golf", "Hatchback", "Economy", 38, 5, "Manual", "Petrol", 52700, "Maintenance"),
    ("V007", "Hyundai Elantra", "Sedan", "Economy", 42, 5, "Automatic", "Petrol", 15400, "Available"),
    ("V008", "Kia Sportage", "SUV", "Standard", 62, 5, "Automatic", "Petrol", 27800, "Available"),
    ("V009", "Mazda3 Sport", "Hatchback", "Standard", 48, 5, "Automatic", "Petrol", 19600, "Available"),
    ("V010", "Ford F-150", "Truck", "Premium", 95, 5, "Automatic", "Petrol", 38100, "Available"),
]

# Odometer reading at each car's last service. Service is due every 10,000 km,
# so the demo has a mix of OK, "Service soon" and "Service due" cars.
SEED_LAST_SERVICE_KM = {
    "V001": 19600, "V002": 31000, "V003": 30800, "V004": 15000, "V005": 20000,
    "V006": 42100, "V007": 10000, "V008": 24000, "V009": 18500, "V010": 29600,
}

SEED_USERS = [
    # name, email, password, role
    ("Jane Doe", "customer@example.com", "password123", "customer"),
    ("Michael Brown", "michael@example.com", "password123", "customer"),
    ("Sara Lee", "sara@example.com", "password123", "customer"),
    ("Chris Park", "chris@example.com", "password123", "customer"),
    ("J. Smith", "staff@example.com", "staff123", "staff"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# Columns added after Sprint 1. CREATE TABLE IF NOT EXISTS leaves an existing
# car_rental.db alone, so older database files get the new columns here.
MIGRATIONS = [
    ("vehicles", "last_service_km", "INTEGER NOT NULL DEFAULT 0"),
    ("reservations", "km_driven", "INTEGER"),
]


def migrate(db):
    for table, column, decl in MIGRATIONS:
        columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            if column == "last_service_km":  # no history yet: treat every car as just serviced
                db.execute("UPDATE vehicles SET last_service_km = mileage_km")


def init_db(seed=True):
    db = get_db()
    db.executescript(SCHEMA)
    migrate(db)
    if seed and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_db(db)
    db.commit()


def seed_db(db):
    for name, email, pw, role in SEED_USERS:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(pw), role),
        )
    db.executemany(
        "INSERT INTO vehicles (id, name, type, category, price_per_day, seats, transmission,"
        " fuel_type, mileage_km, status) VALUES (?,?,?,?,?,?,?,?,?,?)", SEED_VEHICLES)
    db.executemany("UPDATE vehicles SET last_service_km = ? WHERE id = ?",
                   [(km, vid) for vid, km in SEED_LAST_SERVICE_KM.items()])

    # Reservations relative to today so the staff dashboard always has data.
    t = date.today()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731
    seed_res = [
        # user_id, vehicle, pickup, return, status, km driven (None = not returned/logged yet)
        (2, "V008", d(-80), d(-75), "Confirmed", 640),   # older rentals for the REP-02 report
        (3, "V010", d(-62), d(-57), "Confirmed", 910),
        (2, "V002", d(-50), d(-44), "Confirmed", 720),
        (1, "V004", d(-40), d(-37), "Confirmed", 412),   # Jane's past rentals (UI-04 history)
        (4, "V009", d(-33), d(-29), "Confirmed", 350),
        (3, "V003", d(-28), d(-21), "Confirmed", 1150),
        (1, "V005", d(-25), d(-22), "Confirmed", 538),
        (2, "V010", d(-19), d(-14), "Confirmed", 780),
        (1, "V007", d(-15), d(-12), "Cancelled", None),
        (3, "V008", d(-12), d(-8), "Confirmed", 460),
        (4, "V002", d(-10), d(-6), "Confirmed", 520),
        (4, "V003", d(-6), d(-3), "Confirmed", None),    # returned, km still to log (REP-02)
        (3, "V002", d(-2), d(1), "Confirmed", None),     # active today
        (2, "V004", d(-1), d(2), "Confirmed", None),     # active today
        (1, "V001", d(0), d(3), "Confirmed", None),      # picks up today
        (3, "V005", d(2), d(5), "Confirmed", None),      # upcoming
        (1, "V002", d(5), d(9), "Confirmed", None),      # upcoming
    ]
    for uid, vid, p, r, status, km in seed_res:
        price = db.execute("SELECT price_per_day FROM vehicles WHERE id = ?", (vid,)).fetchone()[0]
        days = (date.fromisoformat(r) - date.fromisoformat(p)).days
        db.execute(
            "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, total_price,"
            " status, km_driven) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (uid, vid, p, r, price * days, status, km),
        )


# ---------------------------------------------------------------------------
# Availability (FR-10: prevent conflicting or duplicate bookings)
# ---------------------------------------------------------------------------
# Two rentals overlap when one starts before the other ends. Return day is the
# hand-back day, so a car returned on the 15th can be picked up again on the 15th.
OVERLAP_SQL = """
    SELECT 1 FROM reservations r
    WHERE r.vehicle_id = {vid}
      AND r.status = 'Confirmed'
      AND r.pickup_date < :return_date
      AND r.return_date > :pickup_date
"""


def is_vehicle_available(db, vehicle_id, pickup, ret):
    vehicle = db.execute("SELECT status FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
    if vehicle is None or vehicle["status"] != "Available":
        return False
    clash = db.execute(
        OVERLAP_SQL.format(vid=":vid"),
        {"vid": vehicle_id, "pickup_date": pickup, "return_date": ret},
    ).fetchone()
    return clash is None


def search_available(db, pickup, ret, vtype=None, category=None):
    """UI-01: vehicles matching type/category that are free for the whole period."""
    sql = f"""
        SELECT v.* FROM vehicles v
        WHERE v.status = 'Available'
          AND NOT EXISTS ({OVERLAP_SQL.format(vid="v.id")})
    """
    params = {"pickup_date": pickup, "return_date": ret}
    if vtype:
        sql += " AND v.type = :vtype"
        params["vtype"] = vtype
    if category:
        sql += " AND v.category = :category"
        params["category"] = category
    sql += " ORDER BY v.price_per_day"
    return db.execute(sql, params).fetchall()


class VehicleUnavailable(Exception):
    pass


def create_reservation(db, user_id, vehicle_id, pickup, ret):
    """UI-03: check availability and insert in one locked transaction, so two
    customers booking the same car at the same moment can't both succeed."""
    days = (date.fromisoformat(ret) - date.fromisoformat(pickup)).days
    db.execute("BEGIN IMMEDIATE")
    try:
        if not is_vehicle_available(db, vehicle_id, pickup, ret):
            raise VehicleUnavailable(vehicle_id)
        price = db.execute(
            "SELECT price_per_day FROM vehicles WHERE id = ?", (vehicle_id,)
        ).fetchone()[0]
        cur = db.execute(
            "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, total_price)"
            " VALUES (?, ?, ?, ?, ?)",
            (user_id, vehicle_id, pickup, ret, price * days),
        )
        db.commit()
        return cur.lastrowid
    except Exception:
        db.rollback()
        raise


# ---------------------------------------------------------------------------
# Rental history (UI-04)
# ---------------------------------------------------------------------------
HISTORY_STATUSES = ["Active", "Completed", "Cancelled"]


def rental_status(rental, today):
    """Where a reservation stands on `today`: Cancelled, Completed, Active or Upcoming."""
    if rental["status"] == "Cancelled":
        return "Cancelled"
    if rental["return_date"] < today:
        return "Completed"
    if rental["pickup_date"] <= today:
        return "Active"
    return "Upcoming"


def rental_history(db, user_id, today):
    """A customer's current and past rentals, newest first. Upcoming bookings
    belong to My Reservations (UI-05), so they're left out unless cancelled."""
    rows = db.execute(
        """
        SELECT r.*, v.name AS vehicle, v.type, v.category,
               CAST(julianday(r.return_date) - julianday(r.pickup_date) AS INTEGER) AS days
        FROM reservations r
        JOIN vehicles v ON v.id = r.vehicle_id
        WHERE r.user_id = :uid
          AND (r.status = 'Cancelled' OR r.pickup_date <= :today)
        ORDER BY r.pickup_date DESC, r.id DESC
        """,
        {"uid": user_id, "today": today},
    ).fetchall()
    return [dict(r, rental_status=rental_status(r, today)) for r in rows]


# ---------------------------------------------------------------------------
# Manage reservations (UI-05)
# ---------------------------------------------------------------------------
# Cars are collected at 10:00 on the pickup day. Free cancellation ends 24 hours
# before that, so a booking picked up on the 15th can be cancelled until 10:00 on the 14th.
PICKUP_TIME = time(10, 0)
CANCEL_NOTICE = timedelta(hours=24)

RESERVATION_SQL = """
    SELECT r.*, v.name AS vehicle, v.type, v.category, v.price_per_day,
           CAST(julianday(r.return_date) - julianday(r.pickup_date) AS INTEGER) AS days
    FROM reservations r
    JOIN vehicles v ON v.id = r.vehicle_id
"""


class CannotCancel(Exception):
    pass


def cancel_deadline(pickup_date):
    return datetime.combine(date.fromisoformat(pickup_date), PICKUP_TIME) - CANCEL_NOTICE


def cancel_block_reason(rental, now=None):
    """Why this booking can't be cancelled right now, or None if it can."""
    now = now or datetime.now()
    if rental["status"] == "Cancelled":
        return "This reservation is already cancelled."
    if now >= cancel_deadline(rental["pickup_date"]):
        return "Reservations can only be cancelled up to 24 hours before pickup."
    return None


def _with_status(row, now):
    return dict(row,
                rental_status=rental_status(row, now.date().isoformat()),
                can_cancel=cancel_block_reason(row, now) is None,
                cancel_deadline=cancel_deadline(row["pickup_date"]))


def get_reservation(db, reservation_id, user_id, now=None):
    """One of the customer's own reservations, or None if it's missing or someone else's."""
    row = db.execute(RESERVATION_SQL + " WHERE r.id = ? AND r.user_id = ?",
                     (reservation_id, user_id)).fetchone()
    return _with_status(row, now or datetime.now()) if row else None


def my_reservations(db, user_id, now=None):
    """UI-05: upcoming and active bookings (soonest first), plus the 3 most recent past ones."""
    now = now or datetime.now()
    rows = [_with_status(r, now) for r in db.execute(
        RESERVATION_SQL + " WHERE r.user_id = ? ORDER BY r.pickup_date, r.id", (user_id,))]
    current = [r for r in rows if r["rental_status"] in ("Upcoming", "Active")]
    past = [r for r in reversed(rows) if r["rental_status"] in ("Completed", "Cancelled")][:3]
    return current, past


def cancel_reservation(db, reservation_id, user_id, now=None):
    """UI-05: cancel the customer's own booking. Once cancelled it no longer blocks
    the car (OVERLAP_SQL only counts confirmed bookings), so others can book it."""
    r = get_reservation(db, reservation_id, user_id, now)
    if r is None:
        raise CannotCancel("Reservation not found.")
    reason = cancel_block_reason(r, now)
    if reason:
        raise CannotCancel(reason)
    db.execute("UPDATE reservations SET status = 'Cancelled' WHERE id = ? AND user_id = ?",
               (reservation_id, user_id))
    db.commit()


# ---------------------------------------------------------------------------
# Manage vehicles (VEH-01, FR-6)
# ---------------------------------------------------------------------------
TRANSMISSIONS = ["Automatic", "Manual"]
FUEL_TYPES = ["Petrol", "Diesel", "Hybrid", "Electric"]
VEHICLE_STATUSES = ["Available", "Maintenance"]

# form field -> (label, min, max) for the whole-number fields
VEHICLE_NUMBERS = {
    "price_per_day": ("Price per day", 1, 2000),
    "seats": ("Seats", 1, 15),
    "mileage_km": ("Mileage", 0, 1_000_000),
}


def list_vehicles(db, q=None, vtype=None, category=None, status=None):
    """VEH-01: the whole fleet, optionally searched by name/ID/type and filtered."""
    sql = "SELECT * FROM vehicles WHERE 1 = 1"
    params = {}
    if q:
        sql += " AND (name LIKE :q OR id LIKE :q OR type LIKE :q)"
        params["q"] = f"%{q}%"
    for column, value in (("type", vtype), ("category", category), ("status", status)):
        if value:
            sql += f" AND {column} = :{column}"
            params[column] = value
    return db.execute(sql + " ORDER BY id", params).fetchall()


def get_vehicle(db, vehicle_id):
    return db.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()


def validate_vehicle(form, new=True):
    """Check an add/edit form. Returns (clean values, {field: error message}).
    Mileage is only set when a car is added; after that it grows as returns are logged (REP-02)."""
    data, errors = {}, {}
    name = (form.get("name") or "").strip()
    if not name:
        errors["name"] = "Enter the vehicle name."
    elif len(name) > 60:
        errors["name"] = "Keep the name under 60 characters."
    data["name"] = name
    for field, label, choices in (("type", "Type", TYPES), ("category", "Category", CATEGORIES),
                                  ("transmission", "Transmission", TRANSMISSIONS),
                                  ("fuel_type", "Fuel type", FUEL_TYPES),
                                  ("status", "Availability", VEHICLE_STATUSES)):
        data[field] = form.get(field) or ""
        if data[field] not in choices:
            article = "an" if label[0] in "AEIOU" else "a"
            errors[field] = f"Choose {article} {label.lower()}."
    for field, (label, low, high) in VEHICLE_NUMBERS.items():
        if field == "mileage_km" and not new:
            continue
        raw = (form.get(field) or "").strip()
        data[field] = raw
        try:
            value = int(raw)
        except ValueError:
            errors[field] = f"{label} must be a whole number."
            continue
        if not low <= value <= high:
            errors[field] = f"{label} must be between {low:,} and {high:,}."
        else:
            data[field] = value
    return data, errors


def next_vehicle_id(db):
    row = db.execute("SELECT MAX(CAST(SUBSTR(id, 2) AS INTEGER)) FROM vehicles WHERE id LIKE 'V%'").fetchone()
    return f"V{(row[0] or 0) + 1:03d}"


def add_vehicle(db, data):
    """Add a car to the fleet. A new car counts as just serviced."""
    vehicle_id = next_vehicle_id(db)
    db.execute(
        """INSERT INTO vehicles (id, name, type, category, price_per_day, seats, transmission,
                                 fuel_type, mileage_km, status, last_service_km)
           VALUES (:id, :name, :type, :category, :price_per_day, :seats, :transmission,
                   :fuel_type, :mileage_km, :status, :mileage_km)""",
        dict(data, id=vehicle_id),
    )
    db.commit()
    return vehicle_id


def update_vehicle(db, vehicle_id, data):
    """Edit a car's details. Existing bookings keep the price they were booked at."""
    db.execute(
        """UPDATE vehicles SET name = :name, type = :type, category = :category,
                  price_per_day = :price_per_day, seats = :seats, transmission = :transmission,
                  fuel_type = :fuel_type, status = :status
           WHERE id = :id""",
        dict(data, id=vehicle_id),
    )
    db.commit()


def upcoming_bookings(db, vehicle_id, today):
    """Confirmed bookings for this car that haven't finished yet."""
    return db.execute(
        "SELECT COUNT(*) FROM reservations WHERE vehicle_id = ? AND status = 'Confirmed'"
        " AND return_date > ?", (vehicle_id, today)).fetchone()[0]


def set_vehicle_status(db, vehicle_id, status):
    """Available cars show in search; Maintenance cars are hidden and can't be booked."""
    if status not in VEHICLE_STATUSES:
        raise ValueError(status)
    cur = db.execute("UPDATE vehicles SET status = ? WHERE id = ?", (status, vehicle_id))
    db.commit()
    return cur.rowcount == 1


# ---------------------------------------------------------------------------
# Daily rental report (REP-01)
# ---------------------------------------------------------------------------
def day_status(rental, day):
    """What happens with this rental on `day`: picked up, returned, or out all day."""
    if rental["pickup_date"] == day:
        return "Pickup"
    if rental["return_date"] == day:
        return "Return"
    return "On rent"


def daily_rentals(db, day):
    """Every confirmed rental where the car is out (or being picked up) on `day`."""
    return db.execute(
        """
        SELECT r.*, u.name AS customer, v.name AS vehicle
        FROM reservations r
        JOIN users u ON u.id = r.user_id
        JOIN vehicles v ON v.id = r.vehicle_id
        WHERE r.status = 'Confirmed'
          AND r.pickup_date <= :day AND r.return_date >= :day
        ORDER BY r.pickup_date, r.id
        """,
        {"day": day},
    ).fetchall()


def recent_reservations(db, limit=8):
    """Newest bookings first, so staff see a reservation as soon as it's made."""
    return db.execute(
        """
        SELECT r.*, u.name AS customer, v.name AS vehicle,
               CAST(julianday(r.return_date) - julianday(r.pickup_date) AS INTEGER) AS days,
               datetime(r.created_at, 'localtime') AS booked_at
        FROM reservations r
        JOIN users u ON u.id = r.user_id
        JOIN vehicles v ON v.id = r.vehicle_id
        WHERE r.status = 'Confirmed'
        ORDER BY r.id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()


# ---------------------------------------------------------------------------
# Vehicle utilization report (REP-02)
# ---------------------------------------------------------------------------
REPORT_PERIODS = [7, 30, 90]          # "last N days" options, including today
SERVICE_INTERVAL_KM = 10000           # service every 10,000 km
SERVICE_SOON_KM = 8000                # warn 2,000 km ahead
MAX_KM_PER_RENTAL = 20000


class InvalidReturn(Exception):
    pass


def maintenance_status(vehicle):
    if vehicle["status"] == "Maintenance":
        return "In maintenance"
    since = vehicle["mileage_km"] - vehicle["last_service_km"]
    if since >= SERVICE_INTERVAL_KM:
        return "Service due"
    if since >= SERVICE_SOON_KM:
        return "Service soon"
    return "OK"


def report_period(days, today):
    """(start, end) ISO dates for the last `days` days including today; end is exclusive."""
    return (today - timedelta(days=days - 1)).isoformat(), (today + timedelta(days=1)).isoformat()


def utilization_report(db, start, end):
    """REP-02: usage and maintenance for every vehicle between start and end (exclusive).

    Days rented counts only the part of each rental inside the period, so utilization
    is days rented / days in period. Km driven counts rentals returned in the period."""
    period_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    rows = db.execute(
        """
        SELECT v.*,
               COUNT(r.id) AS rentals,
               CAST(COALESCE(SUM(julianday(MIN(r.return_date, :end))
                                 - julianday(MAX(r.pickup_date, :start))), 0) AS INTEGER) AS days_rented,
               (SELECT COALESCE(SUM(k.km_driven), 0) FROM reservations k
                WHERE k.vehicle_id = v.id AND k.status = 'Confirmed'
                  AND k.return_date >= :start AND k.return_date < :end) AS km_driven
        FROM vehicles v
        LEFT JOIN reservations r
               ON r.vehicle_id = v.id AND r.status = 'Confirmed'
              AND r.pickup_date < :end AND r.return_date > :start
        GROUP BY v.id
        """,
        {"start": start, "end": end},
    ).fetchall()
    vehicles = [dict(v,
                     utilization=v["days_rented"] / period_days,
                     km_since_service=v["mileage_km"] - v["last_service_km"],
                     maintenance=maintenance_status(v)) for v in rows]
    vehicles.sort(key=lambda v: (-v["utilization"], -v["rentals"], v["id"]))

    by_type = []
    for t in TYPES:
        group = [v for v in vehicles if v["type"] == t]
        if group:
            days = sum(v["days_rented"] for v in group)
            by_type.append({"type": t, "vehicles": len(group),
                            "rentals": sum(v["rentals"] for v in group),
                            "days_rented": days,
                            "km_driven": sum(v["km_driven"] for v in group),
                            "utilization": days / (len(group) * period_days)})

    total_days = sum(v["days_rented"] for v in vehicles)
    summary = {
        "period_days": period_days,
        "utilization": total_days / (len(vehicles) * period_days) if vehicles else 0,
        "rentals": sum(v["rentals"] for v in vehicles),
        "km_driven": sum(v["km_driven"] for v in vehicles),
        "service_due": sum(v["maintenance"] == "Service due" for v in vehicles),
        "top": vehicles[0] if vehicles and vehicles[0]["days_rented"] else None,
    }
    return vehicles, by_type, summary


def returns_to_log(db, today):
    """Rentals that have ended but whose km driven hasn't been recorded yet."""
    return db.execute(
        """
        SELECT r.*, u.name AS customer, v.name AS vehicle, v.mileage_km
        FROM reservations r
        JOIN users u ON u.id = r.user_id
        JOIN vehicles v ON v.id = r.vehicle_id
        WHERE r.status = 'Confirmed' AND r.return_date <= ? AND r.km_driven IS NULL
        ORDER BY r.return_date, r.id
        """,
        (today,),
    ).fetchall()


def record_return(db, reservation_id, km, today):
    """Log the km driven on a finished rental and add it to the car's odometer."""
    if km is None or not 0 <= km <= MAX_KM_PER_RENTAL:
        raise InvalidReturn(f"Enter the km driven as a whole number from 0 to {MAX_KM_PER_RENTAL:,}.")
    db.execute("BEGIN IMMEDIATE")
    try:
        r = db.execute("SELECT * FROM reservations WHERE id = ?", (reservation_id,)).fetchone()
        if r is None or r["status"] != "Confirmed" or r["return_date"] > today:
            raise InvalidReturn("Only finished rentals can be logged.")
        if r["km_driven"] is not None:
            raise InvalidReturn("The km for this rental have already been logged.")
        db.execute("UPDATE reservations SET km_driven = ? WHERE id = ?", (km, reservation_id))
        db.execute("UPDATE vehicles SET mileage_km = mileage_km + ? WHERE id = ?",
                   (km, r["vehicle_id"]))
        db.commit()
    except Exception:
        db.rollback()
        raise


def mark_serviced(db, vehicle_id):
    """Reset the service counter: the car was serviced at its current odometer reading."""
    cur = db.execute("UPDATE vehicles SET last_service_km = mileage_km WHERE id = ?", (vehicle_id,))
    db.commit()
    return cur.rowcount == 1


def fleet_stats(db, day):
    total = db.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
    maintenance = db.execute(
        "SELECT COUNT(*) FROM vehicles WHERE status = 'Maintenance'"
    ).fetchone()[0]
    rented = db.execute(
        """SELECT COUNT(DISTINCT vehicle_id) FROM reservations
           WHERE status = 'Confirmed' AND pickup_date <= :d AND return_date > :d""",
        {"d": day},
    ).fetchone()[0]
    pickups = db.execute(
        "SELECT COUNT(*) FROM reservations WHERE status = 'Confirmed' AND pickup_date = ?",
        (day,),
    ).fetchone()[0]
    return {
        "total": total,
        "maintenance": maintenance,
        "rented": rented,
        "available": total - maintenance - rented,
        "pickups": pickups,
    }
