"""Database layer for the Car Rental System (SQLite).

Holds the schema, demo seed data, and the reservation availability check
used by UI-03 (Reserve a Car) and functional requirement #10.
"""
import sqlite3
from datetime import date, timedelta

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
                 CHECK (status IN ('Available', 'Maintenance'))
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
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
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


def init_db(seed=True):
    db = get_db()
    db.executescript(SCHEMA)
    if seed and db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        seed_db(db)
    db.commit()


def seed_db(db):
    for name, email, pw, role in SEED_USERS:
        db.execute(
            "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (name, email, generate_password_hash(pw), role),
        )
    db.executemany("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?,?)", SEED_VEHICLES)

    # Reservations relative to today so the staff dashboard always has data.
    t = date.today()
    d = lambda n: (t + timedelta(days=n)).isoformat()  # noqa: E731
    seed_res = [
        # user_id, vehicle, pickup, return
        (4, "V003", d(-6), d(-3)),   # completed
        (3, "V002", d(-2), d(1)),    # active today
        (2, "V004", d(-1), d(2)),    # active today
        (1, "V001", d(0), d(3)),     # picks up today
        (3, "V005", d(2), d(5)),     # upcoming
        (1, "V002", d(5), d(9)),     # upcoming
    ]
    for uid, vid, p, r in seed_res:
        price = db.execute("SELECT price_per_day FROM vehicles WHERE id = ?", (vid,)).fetchone()[0]
        days = (date.fromisoformat(r) - date.fromisoformat(p)).days
        db.execute(
            "INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, total_price)"
            " VALUES (?, ?, ?, ?, ?)",
            (uid, vid, p, r, price * days),
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
