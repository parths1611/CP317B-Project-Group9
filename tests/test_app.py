"""Sprint 1 unit/integration tests. Run with:  python -m pytest -v

Each test is tagged with the backlog story whose acceptance criteria it checks.
"""
import os
import re
import sys
from datetime import date, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db as store  # noqa: E402
from app import create_app  # noqa: E402

D = lambda n: (date.today() + timedelta(days=n)).isoformat()  # noqa: E731


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return app.test_client()


def csrf(client):
    """Load the login page to get a session CSRF token."""
    html = client.get("/login").get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)


def daily_report(html):
    """Just the daily report part of the dashboard (above Recent bookings)."""
    return html.split("Recent bookings")[0]


def login(client, email="customer@example.com", password="password123", role="customer"):
    return client.post("/login", data={"email": email, "password": password, "role": role,
                                       "csrf_token": csrf(client)})


# ----------------------------------------------------------------- AUTH / security
def test_customer_login_success(client):
    r = login(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert client.get("/home").status_code == 200


def test_wrong_password_rejected(client):
    r = login(client, password="nope")
    assert r.status_code == 401
    assert b"Incorrect email or password" in r.data


def test_customer_cannot_log_in_as_staff(client):
    r = login(client, role="staff")
    assert r.status_code == 401
    assert b"can&#39;t sign in as an employee" in r.data


def test_staff_login_goes_to_dashboard(client):
    login(client, "staff@example.com", "staff123", "staff")
    r = client.get("/")
    assert r.headers["Location"].endswith("/staff/dashboard")


def test_signup_creates_customer(client, app):
    r = client.post("/signup", data={"name": "New Person", "email": "new@example.com",
                                     "password": "longenough", "csrf_token": csrf(client)})
    assert r.status_code == 302
    with app.app_context():
        u = store.get_db().execute("SELECT role FROM users WHERE email='new@example.com'").fetchone()
    assert u["role"] == "customer"


def test_signup_duplicate_email_and_short_password(client):
    t = csrf(client)
    r = client.post("/signup", data={"name": "X", "email": "customer@example.com",
                                     "password": "longenough", "csrf_token": t})
    assert b"already exists" in r.data
    r = client.post("/signup", data={"name": "X", "email": "x@example.com",
                                     "password": "short", "csrf_token": t})
    assert b"at least 8 characters" in r.data


def test_pages_require_login(client):
    for url in ["/home", "/vehicles/V001", "/staff/dashboard"]:
        assert client.get(url).status_code == 302


def test_role_based_access(client):
    login(client)  # customer
    assert client.get("/staff/dashboard").status_code == 403


def test_staff_cannot_use_customer_pages(client):
    login(client, "staff@example.com", "staff123", "staff")
    assert client.get("/home").status_code == 403


def test_post_without_csrf_token_rejected(client):
    r = client.post("/login", data={"email": "customer@example.com", "password": "password123"})
    assert r.status_code == 400


def test_passwords_are_hashed(app):
    with app.app_context():
        h = store.get_db().execute("SELECT password_hash FROM users LIMIT 1").fetchone()[0]
    assert "password123" not in h


# ----------------------------------------------------------------- UI-01 search
def test_search_by_type_and_category(client):
    login(client)
    html = client.get(f"/home?pickup={D(20)}&return={D(23)}&type=SUV&category=Standard").get_data(as_text=True)
    assert "Honda CR-V" in html and "Toyota RAV4" in html and "Kia Sportage" in html
    assert "Toyota Camry" not in html       # Sedan
    assert "Ford Explorer" not in html      # Premium


def test_search_hides_maintenance_vehicles(client):
    login(client)
    html = client.get(f"/home?pickup={D(20)}&return={D(23)}&type=Hatchback").get_data(as_text=True)
    assert "Volkswagen Golf" not in html    # in maintenance
    assert "Mazda3 Sport" in html


def test_search_hides_vehicles_booked_for_those_dates(client):
    login(client)
    # Seed data: V002 Honda CR-V is booked from day 5 to day 9.
    html = client.get(f"/home?pickup={D(6)}&return={D(8)}&type=SUV").get_data(as_text=True)
    assert "Honda CR-V" not in html
    html = client.get(f"/home?pickup={D(20)}&return={D(22)}&type=SUV").get_data(as_text=True)
    assert "Honda CR-V" in html


def test_search_rejects_bad_dates(client):
    login(client)
    assert b"must be after the pickup" in client.get(f"/home?pickup={D(5)}&return={D(3)}").data
    assert b"can&#39;t be in the past" in client.get(f"/home?pickup={D(-2)}&return={D(3)}").data


# ----------------------------------------------------------------- UI-02 details
def test_view_details_shows_specs_and_total(client):
    login(client)
    html = client.get(f"/vehicles/V001?pickup={D(20)}&return={D(23)}").get_data(as_text=True)
    for text in ["Toyota Camry", "Sedan", "Economy", "Automatic", "Petrol", "28,000 km", "$135"]:
        assert text in html
    assert "Reserve This Vehicle" in html


def test_details_asks_for_rental_days(client):
    login(client)
    html = client.get("/vehicles/V007").get_data(as_text=True)  # no dates chosen yet
    assert "When do you need it?" in html
    assert 'name="pickup"' in html and 'name="return"' in html
    assert f'value="{D(1)}"' in html and f'value="{D(4)}"' in html  # sensible defaults
    assert "Reserve This Vehicle" in html


def test_details_changing_days_updates_total(client):
    login(client)
    html = client.get(f"/vehicles/V001?pickup={D(20)}&return={D(25)}").get_data(as_text=True)
    assert "5 days" in html and "$225" in html  # 5 x $45
    assert f'name="pickup" value="{D(20)}"' in html  # reserve form books these exact days


def test_details_bad_days_show_error_and_no_reserve(client):
    login(client)
    html = client.get(f"/vehicles/V001?pickup={D(10)}&return={D(8)}").get_data(as_text=True)
    assert "must be after the pickup" in html
    assert "Reserve This Vehicle" not in html


def test_details_unknown_vehicle_404(client):
    login(client)
    assert client.get("/vehicles/V999").status_code == 404


# ----------------------------------------------------------------- UI-03 reserve + FR-10
def reserve(client, vid, p, r):
    return client.post(f"/vehicles/{vid}/reserve",
                       data={"pickup": p, "return": r, "csrf_token": csrf(client)})


def test_reserve_creates_booking_and_confirmation(client, app):
    login(client)
    r = reserve(client, "V004", D(30), D(33))
    assert r.status_code == 302 and "/reservations/" in r.headers["Location"]
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Reservation confirmed" in page and "$360" in page  # 3 days x $120


def test_double_booking_is_blocked(client, app):
    login(client)
    reserve(client, "V004", D(30), D(33))
    r = reserve(client, "V004", D(31), D(35))          # overlaps
    assert "/reservations/" not in r.headers["Location"]
    with app.app_context():
        n = store.get_db().execute("SELECT COUNT(*) FROM reservations WHERE vehicle_id='V004'"
                                   " AND pickup_date >= ?", (D(30),)).fetchone()[0]
    assert n == 1


def test_back_to_back_booking_allowed(client):
    login(client)
    reserve(client, "V004", D(30), D(33))
    r = reserve(client, "V004", D(33), D(35))          # pickup on previous return day
    assert "/reservations/" in r.headers["Location"]


def test_cannot_reserve_maintenance_vehicle(client):
    login(client)
    r = reserve(client, "V006", D(30), D(33))
    assert "/reservations/" not in r.headers["Location"]


def test_customer_cannot_view_someone_elses_reservation(client):
    login(client)  # Jane (user 1)
    # Reservation 1002 in seed data belongs to Sara Lee (user 3)
    assert client.get("/reservations/1002").status_code == 404


@pytest.mark.parametrize("pickup,ret,expected", [
    (5, 9, False),   # exact same dates as existing booking
    (4, 6, False),   # overlaps start
    (8, 12, False),  # overlaps end
    (6, 7, False),   # inside
    (3, 10, False),  # surrounds
    (1, 5, True),    # ends on existing pickup day
    (9, 12, True),   # starts on existing return day
])
def test_availability_overlap_rules(app, pickup, ret, expected):
    # Seed: V002 booked from day 5 to day 9
    with app.app_context():
        assert store.is_vehicle_available(store.get_db(), "V002", D(pickup), D(ret)) is expected


# ----------------------------------------------------------------- REP-01 daily report
def test_dashboard_shows_todays_rentals(client):
    login(client, "staff@example.com", "staff123", "staff")
    html = daily_report(client.get("/staff/dashboard").get_data(as_text=True))
    # Seed: rentals active today are Sara (CR-V), Michael (BMW), Jane (Camry pickup)
    for name in ["Sara Lee", "Michael Brown", "Jane Doe"]:
        assert name in html
    assert "Chris Park" not in html  # his rental ended 3 days ago


def test_dashboard_counts_are_accurate(app):
    with app.app_context():
        db = store.get_db()
        assert len(store.daily_rentals(db, D(0))) == 3
        s = store.fleet_stats(db, D(0))
        assert s == {"total": 10, "maintenance": 1, "rented": 3, "available": 6, "pickups": 1}


def test_new_booking_appears_on_staff_dashboard(app, client):
    login(client)
    r = reserve(client, "V010", D(40), D(43))  # Jane books the F-150
    rid = r.headers["Location"].rsplit("/", 1)[-1]

    staff = app.test_client()
    login(staff, "staff@example.com", "staff123", "staff")
    # Shows up straight away under Recent bookings, with the days she chose...
    html = staff.get("/staff/dashboard").get_data(as_text=True)
    assert f"R-{rid}" in html and "Ford F-150" in html and D(40) in html and "(3 days)" in html
    # ...and in the daily report for each day of the rental.
    for n in (40, 41, 43):
        html = daily_report(staff.get(f"/staff/dashboard?date={D(n)}").get_data(as_text=True))
        assert "Ford F-150" in html and "Jane Doe" in html


def test_recent_bookings_newest_first(app):
    with app.app_context():
        ids = [r["id"] for r in store.recent_reservations(store.get_db())]
    assert ids == sorted(ids, reverse=True) and len(ids) == 6


def test_dashboard_other_date(client):
    login(client, "staff@example.com", "staff123", "staff")
    html = daily_report(client.get(f"/staff/dashboard?date={D(-5)}").get_data(as_text=True))
    assert "Chris Park" in html and "Jane Doe" not in html
