"""Sprint 1 unit/integration tests. Run with:  python -m pytest -v

Each test is tagged with the backlog story whose acceptance criteria it checks.
"""
import os
import re
import sqlite3
import sys
from datetime import date, datetime, time, timedelta

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


def test_customer_cannot_view_someone_elses_reservation(client, app):
    with app.app_context():
        saras = store.get_db().execute(
            "SELECT id FROM reservations WHERE user_id = 3 LIMIT 1").fetchone()[0]
    login(client)  # Jane (user 1)
    assert client.get(f"/reservations/{saras}").status_code == 404


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


# ----------------------------------------------------------------- UI-04 rental history
def history_rows(html):
    """Just the table body of the history page."""
    return html.split("<tbody>")[1].split("</tbody>")[0] if "<tbody>" in html else ""


def test_history_shows_past_and_current_rentals(client):
    login(client)  # Jane
    html = client.get("/history").get_data(as_text=True)
    rows = history_rows(html)
    # Seed: BMW (completed), RAV4 (completed), Elantra (cancelled), Camry (active today)
    for text in ["BMW 3 Series", "Toyota RAV4", "Hyundai Elantra", "Toyota Camry",
                 D(-40), D(-37), "$360", "3 days"]:
        assert text in rows
    assert rows.count("Completed") == 2 and rows.count("Cancelled") == 1 and rows.count("Active") == 1
    assert "Showing 4 of 4 records" in html


def test_history_hides_upcoming_bookings(client):
    login(client)
    rows = history_rows(client.get("/history").get_data(as_text=True))
    assert "Honda CR-V" not in rows  # Jane's CR-V booking starts in 5 days


def test_history_cancelled_has_no_charge(client):
    login(client)
    rows = history_rows(client.get("/history?status=Cancelled").get_data(as_text=True))
    assert "Hyundai Elantra" in rows and "No charge" in rows and "$" not in rows


@pytest.mark.parametrize("status,shown,hidden", [
    ("Completed", ["BMW 3 Series", "Toyota RAV4"], ["Hyundai Elantra", "Toyota Camry"]),
    ("Cancelled", ["Hyundai Elantra"], ["BMW 3 Series", "Toyota Camry"]),
    ("Active", ["Toyota Camry"], ["BMW 3 Series", "Hyundai Elantra"]),
])
def test_history_status_filter(client, status, shown, hidden):
    login(client)
    rows = history_rows(client.get(f"/history?status={status}").get_data(as_text=True))
    assert all(v in rows for v in shown) and not any(v in rows for v in hidden)


def test_history_only_shows_own_rentals(client):
    login(client, "chris@example.com")
    rows = history_rows(client.get("/history").get_data(as_text=True))
    assert "Ford Explorer" in rows  # Chris's own rental
    assert "BMW 3 Series" not in rows and "Toyota Camry" not in rows  # Jane's


def test_history_empty_for_new_customer(client):
    client.post("/signup", data={"name": "New Person", "email": "new@example.com",
                                 "password": "longenough", "csrf_token": csrf(client)})
    assert b"You haven't rented a car yet" in client.get("/history").data


def test_new_booking_shows_in_history(client):
    login(client)
    reserve(client, "V010", D(0), D(2))  # picks up today, so it's a current rental
    rows = history_rows(client.get("/history?status=Active").get_data(as_text=True))
    assert "Ford F-150" in rows and "$190" in rows


def test_history_pagination(client, app):
    with app.app_context():
        db = store.get_db()
        for n in range(12):  # 12 extra completed rentals for Jane -> 16 total
            db.execute("INSERT INTO reservations (user_id, vehicle_id, pickup_date, return_date, total_price)"
                       " VALUES (1, 'V009', ?, ?, 96)", (D(-200 + 5 * n), D(-198 + 5 * n)))
        db.commit()
    login(client)
    html = client.get("/history").get_data(as_text=True)
    assert "Showing 10 of 16 records" in html and "Page 1 of 2" in html
    html = client.get("/history?page=2").get_data(as_text=True)
    assert "Showing 6 of 16 records" in html and "Page 2 of 2" in html
    assert "Page 2 of 2" in client.get("/history?page=99").get_data(as_text=True)


def test_history_requires_customer(client):
    assert client.get("/history").status_code == 302  # not logged in
    login(client, "staff@example.com", "staff123", "staff")
    assert client.get("/history").status_code == 403


@pytest.mark.parametrize("pickup,ret,status,expected", [
    (-6, -3, "Confirmed", "Completed"),
    (-1, 0, "Confirmed", "Active"),      # return day counts as current
    (0, 3, "Confirmed", "Active"),       # pickup day
    (2, 5, "Confirmed", "Upcoming"),
    (-6, -3, "Cancelled", "Cancelled"),
])
def test_rental_status_rules(pickup, ret, status, expected):
    r = {"pickup_date": D(pickup), "return_date": D(ret), "status": status}
    assert store.rental_status(r, D(0)) == expected


# ----------------------------------------------------------------- UI-05 manage reservations
def res_id_for(app, user_id, vehicle_id, pickup):
    with app.app_context():
        return store.get_db().execute(
            "SELECT id FROM reservations WHERE user_id = ? AND vehicle_id = ? AND pickup_date = ?",
            (user_id, vehicle_id, pickup)).fetchone()[0]


def res_status(app, rid):
    with app.app_context():
        return store.get_db().execute("SELECT status FROM reservations WHERE id = ?", (rid,)).fetchone()[0]


def cancel(client, rid):
    return client.post(f"/reservations/{rid}/cancel", data={"csrf_token": csrf(client)})


def current_section(html):
    return html.split("Past reservations")[0]


def test_my_reservations_lists_upcoming_and_active(client, app):
    login(client)  # Jane: Camry today (active), CR-V in 5 days (upcoming)
    html = client.get("/reservations").get_data(as_text=True)
    current = current_section(html)
    assert "Toyota Camry" in current and "Active" in current
    assert "Honda CR-V" in current and "Upcoming" in current
    assert "BMW 3 Series" not in current               # completed -> past section
    assert "Past reservations" in html and "BMW 3 Series" in html
    crv = res_id_for(app, 1, "V002", D(5))
    camry = res_id_for(app, 1, "V001", D(0))
    assert f"/reservations/{crv}/cancel" in html       # far enough ahead to cancel
    assert f"/reservations/{camry}/cancel" not in html  # already picked up
    assert "Rental in progress" in current


def test_cancel_asks_for_confirmation_first(client, app):
    login(client)
    crv = res_id_for(app, 1, "V002", D(5))
    html = client.get(f"/reservations/{crv}/cancel").get_data(as_text=True)
    assert f"Cancel reservation R-{crv}?" in html and "Yes, cancel reservation" in html
    assert res_status(app, crv) == "Confirmed"          # nothing changed yet


def test_cancel_reservation(client, app):
    login(client)
    crv = res_id_for(app, 1, "V002", D(5))
    r = cancel(client, crv)
    assert r.status_code == 302 and r.headers["Location"].endswith("/reservations")
    assert res_status(app, crv) == "Cancelled"
    html = client.get("/reservations").get_data(as_text=True)
    assert f"R-{crv} has been cancelled" in html
    assert "Honda CR-V" not in current_section(html)
    assert "Reservation cancelled" in client.get(f"/reservations/{crv}").get_data(as_text=True)


def test_cancelled_booking_frees_the_car_in_search(client, app):
    login(client)
    html = client.get(f"/home?pickup={D(6)}&return={D(8)}&type=SUV").get_data(as_text=True)
    assert "Honda CR-V" not in html
    cancel(client, res_id_for(app, 1, "V002", D(5)))
    html = client.get(f"/home?pickup={D(6)}&return={D(8)}&type=SUV").get_data(as_text=True)
    assert "Honda CR-V" in html
    assert reserve(client, "V002", D(6), D(8)).headers["Location"].startswith("/reservations/")


def test_cancelled_booking_shows_in_history(client, app):
    login(client)
    cancel(client, res_id_for(app, 1, "V002", D(5)))
    rows = history_rows(client.get("/history?status=Cancelled").get_data(as_text=True))
    assert "Honda CR-V" in rows


def test_cancelled_booking_leaves_staff_dashboard(client, app):
    crv = res_id_for(app, 1, "V002", D(5))
    staff = app.test_client()
    login(staff, "staff@example.com", "staff123", "staff")
    assert f"R-{crv}" in staff.get(f"/staff/dashboard?date={D(6)}").get_data(as_text=True)
    login(client)
    cancel(client, crv)
    html = staff.get(f"/staff/dashboard?date={D(6)}").get_data(as_text=True)
    assert f"R-{crv}" not in html                       # gone from daily report and recent bookings


def test_cannot_cancel_after_pickup_or_deadline(client, app):
    login(client)
    camry = res_id_for(app, 1, "V001", D(0))           # picked up today
    r = cancel(client, camry)
    assert res_status(app, camry) == "Confirmed"
    assert b"up to 24 hours before pickup" in client.get(r.headers["Location"]).data
    assert client.get(f"/reservations/{camry}/cancel").status_code == 302  # no confirm page


def test_cannot_cancel_twice(client, app):
    login(client)
    crv = res_id_for(app, 1, "V002", D(5))
    cancel(client, crv)
    r = cancel(client, crv)
    assert b"already cancelled" in client.get(r.headers["Location"]).data


def test_cannot_cancel_someone_elses_reservation(client, app):
    saras = res_id_for(app, 3, "V005", D(2))
    login(client)  # Jane
    assert client.get(f"/reservations/{saras}/cancel").status_code == 404
    assert cancel(client, saras).status_code == 404
    assert res_status(app, saras) == "Confirmed"


def test_cancel_requires_customer_and_csrf(client, app):
    crv = res_id_for(app, 1, "V002", D(5))
    assert client.get("/reservations").status_code == 302
    login(client, "staff@example.com", "staff123", "staff")
    assert client.get("/reservations").status_code == 403
    assert cancel(client, crv).status_code == 403
    login(client)
    assert client.post(f"/reservations/{crv}/cancel").status_code == 400  # no CSRF token
    assert res_status(app, crv) == "Confirmed"


def test_my_reservations_empty_state(client):
    client.post("/signup", data={"name": "New Person", "email": "new@example.com",
                                 "password": "longenough", "csrf_token": csrf(client)})
    assert b"You have no upcoming reservations" in client.get("/reservations").data


@pytest.mark.parametrize("now,allowed", [
    (datetime.combine(date.today() + timedelta(days=1), time(9, 59)), True),   # 24h + 1 min before
    (datetime.combine(date.today() + timedelta(days=1), time(10, 0)), False),  # exactly 24h before
    (datetime.combine(date.today() + timedelta(days=2), time(8, 0)), False),   # pickup morning
])
def test_cancel_deadline_rule(now, allowed):
    r = {"status": "Confirmed", "pickup_date": D(2)}   # collected at 10:00 on day 2
    assert (store.cancel_block_reason(r, now) is None) is allowed


# ----------------------------------------------------------------- REP-02 vehicle utilization
def staff_login(client):
    login(client, "staff@example.com", "staff123", "staff")


def report(app, days):
    with app.app_context():
        start, end = store.report_period(days, date.today())
        vehicles, by_type, summary = store.utilization_report(store.get_db(), start, end)
    return {v["id"]: v for v in vehicles}, by_type, summary


def log_km(client, rid, km):
    return client.post(f"/staff/reports/returns/{rid}", data={"km": km, "csrf_token": csrf(client)})


def vehicle(app, vid):
    with app.app_context():
        return store.get_db().execute("SELECT * FROM vehicles WHERE id = ?", (vid,)).fetchone()


def test_reports_require_staff(client):
    assert client.get("/staff/reports").status_code == 302
    login(client)
    assert client.get("/staff/reports").status_code == 403


def test_report_lists_every_vehicle_with_maintenance_status(client):
    staff_login(client)
    html = client.get("/staff/reports").get_data(as_text=True)
    for name, _type in [(v[1], v[2]) for v in store.SEED_VEHICLES]:
        assert name in html
    # Seed: Explorer 10,400 km since service, Camry 8,400, Golf in the workshop
    assert "Service due" in html and "Service soon" in html and "In maintenance" in html
    assert "Mark serviced" in html


def test_utilization_counts_days_inside_the_period(app):
    vehicles, _, summary = report(app, 30)
    # CR-V: Sara day -2..1 (3 days inside, period ends tonight) + Chris -10..-6 (4 days)
    assert vehicles["V002"]["rentals"] == 2 and vehicles["V002"]["days_rented"] == 7
    assert vehicles["V002"]["utilization"] == pytest.approx(7 / 30)
    # Explorer: Sara -28..-21 (7) + Chris -6..-3 (3)
    assert vehicles["V003"]["days_rented"] == 10
    assert summary["period_days"] == 30
    assert summary["utilization"] == pytest.approx(
        sum(v["days_rented"] for v in vehicles.values()) / (10 * 30))
    week, _, _ = report(app, 7)
    assert week["V003"]["days_rented"] == 3  # Sara's earlier rental is outside the week


def test_utilization_ignores_cancelled_bookings(app):
    vehicles, _, _ = report(app, 30)
    assert vehicles["V007"]["rentals"] == 0  # Jane's Elantra booking was cancelled


def test_km_driven_counts_rentals_returned_in_period(app):
    vehicles, _, summary = report(app, 30)
    assert vehicles["V003"]["km_driven"] == 1150  # Sara's; Chris's return isn't logged yet
    assert vehicles["V002"]["km_driven"] == 520
    assert summary["km_driven"] == sum(v["km_driven"] for v in vehicles.values())


def test_report_sorted_most_used_first(app):
    vehicles, _, summary = report(app, 30)
    utils = [v["utilization"] for v in vehicles.values()]
    assert utils == sorted(utils, reverse=True)
    assert summary["top"]["id"] == next(iter(vehicles))


def test_report_by_vehicle_type(app):
    vehicles, by_type, _ = report(app, 30)
    types = {t["type"]: t for t in by_type}
    assert types["SUV"]["vehicles"] == 4 and types["Truck"]["vehicles"] == 1
    assert sum(t["days_rented"] for t in by_type) == sum(v["days_rented"] for v in vehicles.values())
    suv_days = sum(v["days_rented"] for v in vehicles.values() if v["type"] == "SUV")
    assert types["SUV"]["utilization"] == pytest.approx(suv_days / (4 * 30))


def test_report_period_choice(client):
    staff_login(client)
    assert b"(7 days)" in client.get("/staff/reports?days=7").data
    assert b"(30 days)" in client.get("/staff/reports?days=999").data  # unknown -> default


@pytest.mark.parametrize("since,status,expected", [
    (2000, "Available", "OK"),
    (8000, "Available", "Service soon"),
    (10000, "Available", "Service due"),
    (15000, "Maintenance", "In maintenance"),
])
def test_maintenance_status_rules(since, status, expected):
    v = {"mileage_km": 30000 + since, "last_service_km": 30000, "status": status}
    assert store.maintenance_status(v) == expected


def test_log_return_km_updates_odometer(client, app):
    rid = res_id_for(app, 4, "V003", D(-6))  # Chris's Explorer, returned 3 days ago
    staff_login(client)
    html = client.get("/staff/reports").get_data(as_text=True)
    assert "Returns to log" in html and f"R-{rid}" in html
    r = log_km(client, rid, 380)
    assert r.status_code == 302
    assert vehicle(app, "V003")["mileage_km"] == 41200 + 380
    html = client.get(r.headers["Location"]).get_data(as_text=True)
    assert "Logged 380 km" in html and "Returns to log" not in html
    vehicles, _, _ = report(app, 30)
    assert vehicles["V003"]["km_driven"] == 1150 + 380


def test_logged_km_shows_on_customer_details_page(client, app):
    staff = app.test_client()
    staff_login(staff)
    log_km(staff, res_id_for(app, 4, "V003", D(-6)), 380)
    login(client)
    assert "41,580 km" in client.get("/vehicles/V003").get_data(as_text=True)


@pytest.mark.parametrize("km", ["", "-5", "abc", "20001"])
def test_log_return_rejects_bad_km(client, app, km):
    rid = res_id_for(app, 4, "V003", D(-6))
    staff_login(client)
    r = log_km(client, rid, km)
    assert b"whole number from 0 to 20,000" in client.get(r.headers["Location"]).data
    assert vehicle(app, "V003")["mileage_km"] == 41200


def test_log_return_only_once_and_only_finished_rentals(client, app):
    staff_login(client)
    already = res_id_for(app, 1, "V004", D(-40))     # Jane's BMW, km already logged
    future = res_id_for(app, 1, "V002", D(5))         # hasn't happened yet
    cancelled = res_id_for(app, 1, "V007", D(-15))
    r = log_km(client, already, 100)
    assert b"already been logged" in client.get(r.headers["Location"]).data
    for rid in (future, cancelled):
        r = log_km(client, rid, 100)
        assert b"Only finished rentals" in client.get(r.headers["Location"]).data
    assert vehicle(app, "V004")["mileage_km"] == 18900 and vehicle(app, "V002")["mileage_km"] == 34500


def test_mark_serviced_resets_counter(client, app):
    staff_login(client)
    r = client.post("/staff/vehicles/V003/serviced", data={"csrf_token": csrf(client), "days": 7})
    assert r.headers["Location"].endswith("/staff/reports?days=7")
    v = vehicle(app, "V003")
    assert v["last_service_km"] == v["mileage_km"]
    vehicles, _, summary = report(app, 30)
    assert vehicles["V003"]["maintenance"] == "OK" and summary["service_due"] == 0
    assert client.post("/staff/vehicles/V999/serviced", data={"csrf_token": csrf(client)}).status_code == 404


def test_report_actions_require_staff_and_csrf(client, app):
    rid = res_id_for(app, 4, "V003", D(-6))
    login(client)  # customer
    assert log_km(client, rid, 100).status_code == 403
    assert client.post("/staff/vehicles/V003/serviced", data={"csrf_token": csrf(client)}).status_code == 403
    staff_login(client)
    assert client.post(f"/staff/reports/returns/{rid}", data={"km": 100}).status_code == 400
    assert vehicle(app, "V003")["mileage_km"] == 41200


def test_old_database_gets_new_columns(tmp_path):
    """A car_rental.db made before REP-02 is upgraded when the app starts."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL);
        CREATE TABLE vehicles (id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
            category TEXT NOT NULL, price_per_day INTEGER NOT NULL, seats INTEGER NOT NULL,
            transmission TEXT NOT NULL, fuel_type TEXT NOT NULL, mileage_km INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'Available');
        CREATE TABLE reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
            vehicle_id TEXT NOT NULL, pickup_date TEXT NOT NULL, return_date TEXT NOT NULL,
            total_price INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'Confirmed',
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO users (name, email, password_hash, role) VALUES ('X', 'x@example.com', 'h', 'staff');
        INSERT INTO vehicles VALUES ('V001', 'Toyota Camry', 'Sedan', 'Economy', 45, 5,
            'Automatic', 'Petrol', 28000, 'Available');
    """)
    old.commit()
    old.close()
    app = create_app({"TESTING": True, "DATABASE": str(path)})
    with app.app_context():
        db = store.get_db()
        v = db.execute("SELECT * FROM vehicles WHERE id = 'V001'").fetchone()
        assert v["last_service_km"] == 28000  # treated as just serviced
        assert "km_driven" in [c[1] for c in db.execute("PRAGMA table_info(reservations)")]


# ----------------------------------------------------------------- VEH-01 manage vehicles
NEW_CAR = {"name": "Toyota Corolla", "type": "Sedan", "category": "Economy", "price_per_day": "50",
           "seats": "5", "transmission": "Automatic", "fuel_type": "Hybrid", "mileage_km": "1200",
           "status": "Available"}


def add_car(client, **changes):
    return client.post("/staff/vehicles/new", data=dict(NEW_CAR, csrf_token=csrf(client), **changes))


def edit_car(client, vid, **changes):
    v = dict(NEW_CAR, name="Ford Explorer XLT", type="SUV", category="Premium", price_per_day="99", seats="7")
    return client.post(f"/staff/vehicles/{vid}/edit", data=dict(v, csrf_token=csrf(client), **changes))


def set_status(client, vid, status):
    return client.post(f"/staff/vehicles/{vid}/status", data={"status": status, "csrf_token": csrf(client)})


def test_vehicle_pages_require_staff(client):
    for url in ["/staff/vehicles", "/staff/vehicles/new", "/staff/vehicles/V001/edit"]:
        assert client.get(url).status_code == 302
    login(client)
    for url in ["/staff/vehicles", "/staff/vehicles/new", "/staff/vehicles/V001/edit"]:
        assert client.get(url).status_code == 403
    assert add_car(client).status_code == 403
    assert set_status(client, "V001", "Maintenance").status_code == 403


def test_vehicle_list_shows_whole_fleet(client):
    staff_login(client)
    html = client.get("/staff/vehicles").get_data(as_text=True)
    for vid, name, *_ in store.SEED_VEHICLES:
        assert vid in html and name in html
    assert "10 vehicles total" in html
    assert "Set to Maintenance" in html and "Set Available" in html  # Golf is in maintenance


@pytest.mark.parametrize("query,shown,hidden", [
    ("q=toyota", ["Toyota Camry", "Toyota RAV4"], ["Honda CR-V"]),
    ("q=V010", ["Ford F-150"], ["Ford Explorer"]),
    ("type=Hatchback", ["Volkswagen Golf", "Mazda3 Sport"], ["Toyota Camry"]),
    ("category=Luxury", ["BMW 3 Series"], ["Toyota Camry"]),
    ("status=Maintenance", ["Volkswagen Golf"], ["Mazda3 Sport"]),
    ("type=SUV&category=Standard", ["Honda CR-V", "Toyota RAV4", "Kia Sportage"], ["Ford Explorer"]),
])
def test_vehicle_search_and_filters(client, query, shown, hidden):
    staff_login(client)
    html = client.get(f"/staff/vehicles?{query}").get_data(as_text=True)
    rows = html.split("<tbody>")[1].split("</tbody>")[0]
    assert all(v in rows for v in shown) and not any(v in rows for v in hidden)
    assert "Showing" in html


def test_add_vehicle(client, app):
    staff_login(client)
    r = add_car(client)
    assert r.status_code == 302 and r.headers["Location"].endswith("/staff/vehicles")
    v = vehicle(app, "V011")
    assert v["name"] == "Toyota Corolla" and v["price_per_day"] == 50 and v["fuel_type"] == "Hybrid"
    assert v["mileage_km"] == 1200 and v["last_service_km"] == 1200  # new car counts as serviced
    assert b"added as V011" in client.get("/staff/vehicles").data


def test_new_vehicle_appears_in_customer_search_and_can_be_booked(client, app):
    staff = app.test_client()
    staff_login(staff)
    add_car(staff)
    login(client)
    assert "Toyota Corolla" in client.get(f"/home?pickup={D(20)}&return={D(23)}&type=Sedan").get_data(as_text=True)
    assert reserve(client, "V011", D(20), D(23)).headers["Location"].startswith("/reservations/")


def test_vehicle_added_in_maintenance_is_hidden(client, app):
    staff = app.test_client()
    staff_login(staff)
    add_car(staff, status="Maintenance")
    login(client)
    assert "Toyota Corolla" not in client.get(f"/home?pickup={D(20)}&return={D(23)}").get_data(as_text=True)


@pytest.mark.parametrize("field,value,message", [
    ("name", "", "Enter the vehicle name."),
    ("name", "x" * 61, "under 60 characters"),
    ("type", "Spaceship", "Choose a type."),
    ("category", "", "Choose a category."),
    ("price_per_day", "abc", "Price per day must be a whole number."),
    ("price_per_day", "0", "Price per day must be between 1 and 2,000."),
    ("seats", "20", "Seats must be between 1 and 15."),
    ("transmission", "CVT", "Choose a transmission."),
    ("fuel_type", "Coal", "Choose a fuel type."),
    ("mileage_km", "-1", "Mileage must be between 0 and 1,000,000."),
    ("status", "Stolen", "Choose an availability."),
])
def test_add_vehicle_validation(client, app, field, value, message):
    staff_login(client)
    r = add_car(client, **{field: value})
    assert r.status_code == 400 and message in r.get_data(as_text=True).replace("&#39;", "'")
    assert vehicle(app, "V011") is None


def test_add_vehicle_form_keeps_entered_values_on_error(client):
    staff_login(client)
    html = add_car(client, seats="99").get_data(as_text=True)
    assert 'value="Toyota Corolla"' in html and 'value="50"' in html


def test_edit_vehicle(client, app):
    staff_login(client)
    html = client.get("/staff/vehicles/V003/edit").get_data(as_text=True)
    assert 'value="Ford Explorer"' in html and "41,200" in html
    r = edit_car(client, "V003", mileage_km="5")
    assert r.status_code == 302
    v = vehicle(app, "V003")
    assert v["name"] == "Ford Explorer XLT" and v["price_per_day"] == 99
    assert v["mileage_km"] == 41200  # mileage can't be edited, only logged through returns


def test_price_change_only_affects_new_bookings(client, app):
    crv = res_id_for(app, 1, "V002", D(5))  # Jane booked 4 days x $65 = $260
    staff = app.test_client()
    staff_login(staff)
    edit_car(staff, "V002", name="Honda CR-V", category="Standard", price_per_day="80", seats="5")
    login(client)
    assert "$260" in client.get(f"/reservations/{crv}").get_data(as_text=True)
    assert "$240" in client.get(f"/vehicles/V002?pickup={D(20)}&return={D(23)}").get_data(as_text=True)


def test_edit_vehicle_validation_and_unknown(client, app):
    staff_login(client)
    r = edit_car(client, "V003", price_per_day="")
    assert r.status_code == 400 and b"Price per day must be a whole number" in r.data
    assert vehicle(app, "V003")["price_per_day"] == 85
    assert client.get("/staff/vehicles/V999/edit").status_code == 404


def test_set_maintenance_hides_car_and_warns_about_bookings(client, app):
    staff = app.test_client()
    staff_login(staff)
    r = set_status(staff, "V002", "Maintenance")  # CR-V: Sara on rent now, Jane in 5 days
    html = staff.get(r.headers["Location"]).get_data(as_text=True)
    assert "now in Maintenance" in html and "2 upcoming bookings" in html
    assert vehicle(app, "V002")["status"] == "Maintenance"
    login(client)
    assert "Honda CR-V" not in client.get(f"/home?pickup={D(20)}&return={D(23)}").get_data(as_text=True)
    assert "Not available for these dates" in client.get(f"/vehicles/V002?pickup={D(20)}&return={D(23)}").get_data(as_text=True)
    assert "Honda CR-V" in current_section(client.get("/reservations").get_data(as_text=True))  # booking kept


def test_set_available_returns_car_to_search(client, app):
    staff = app.test_client()
    staff_login(staff)
    html = staff.get(set_status(staff, "V006", "Available").headers["Location"]).get_data(as_text=True)
    assert "now Available" in html and "upcoming booking" not in html
    login(client)
    assert "Volkswagen Golf" in client.get(f"/home?pickup={D(20)}&return={D(23)}").get_data(as_text=True)


def test_set_status_rejects_bad_input(client):
    staff_login(client)
    assert set_status(client, "V001", "Stolen").status_code == 400
    assert set_status(client, "V999", "Maintenance").status_code == 404
    assert client.post("/staff/vehicles/V001/status", data={"status": "Maintenance"}).status_code == 400


def test_next_vehicle_id(app):
    with app.app_context():
        assert store.next_vehicle_id(store.get_db()) == "V011"


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
    assert ids == sorted(ids, reverse=True) and len(ids) == 8  # capped at 8


def test_dashboard_other_date(client):
    login(client, "staff@example.com", "staff123", "staff")
    html = daily_report(client.get(f"/staff/dashboard?date={D(-5)}").get_data(as_text=True))
    assert "Chris Park" in html and "Jane Doe" not in html
