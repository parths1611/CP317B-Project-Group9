"""Car Rental System — prototype (CP317B, Group 9).

Stories built so far:
  AUTH    Login / sign-up with customer and staff roles
  UI-01   Search Available Cars
  UI-02   View Car Details
  UI-03   Reserve a Car (with availability check, FR-10)
  UI-04   View Rental History (Sprint 2)
  REP-01  Daily Rental Report (staff dashboard)

Run:  python app.py   then open http://127.0.0.1:5000
"""
import math
import os
import secrets
import sqlite3
from datetime import date, timedelta
from functools import wraps

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

import db as store


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.path.join(app.root_path, "car_rental.db"),
    )
    if test_config:
        app.config.update(test_config)

    app.teardown_appcontext(store.close_db)
    with app.app_context():
        store.init_db()

    register_routes(app)
    return app


# ---------------------------------------------------------------------------
# Auth helpers (role-based access — NFR Security)
# ---------------------------------------------------------------------------
def login_required(role=None):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return redirect(url_for("login", next=request.path))
            if role and g.user["role"] != role:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def parse_date(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def default_dates():
    """Tomorrow to three days later, used when the customer hasn't picked dates yet."""
    t = date.today()
    return (t + timedelta(days=1)).isoformat(), (t + timedelta(days=4)).isoformat()


def validate_dates(pickup_raw, return_raw):
    """Returns (pickup, return, error)."""
    pickup, ret = parse_date(pickup_raw), parse_date(return_raw)
    if not pickup or not ret:
        return None, None, "Please choose a pickup and return date."
    if pickup < date.today():
        return None, None, "Pickup date can't be in the past."
    if ret <= pickup:
        return None, None, "Return date must be after the pickup date."
    if (ret - pickup).days > 60:
        return None, None, "Rentals can be at most 60 days."
    return pickup, ret, None


def register_routes(app):

    @app.before_request
    def load_user():
        uid = session.get("user_id")
        g.user = None
        if uid is not None:
            g.user = store.get_db().execute(
                "SELECT id, name, email, role FROM users WHERE id = ?", (uid,)
            ).fetchone()
        # CSRF: every POST must echo the session's token.
        if request.method == "POST":
            token = session.get("csrf_token")
            if not token or not secrets.compare_digest(request.form.get("csrf_token", ""), token):
                abort(400, "Form expired. Please go back and try again.")

    @app.context_processor
    def inject_globals():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return {"csrf_token": session["csrf_token"], "today": date.today(),
                "TYPES": store.TYPES, "CATEGORIES": store.CATEGORIES}

    @app.template_filter("pretty_date")
    def pretty_date(value):
        d = date.fromisoformat(value) if isinstance(value, str) else value
        # %-d isn't supported on Windows, so build the day number by hand.
        return f"{d:%b} {d.day}, {d.year}"

    @app.template_filter("long_date")
    def long_date(d):
        return f"{d:%A, %B} {d.day}, {d.year}"

    @app.template_filter("res_id")
    def res_id(value):
        return f"R-{value}"

    # ------------------------------------------------------------------ auth
    @app.route("/")
    def index():
        if g.user is None:
            return redirect(url_for("login"))
        return redirect(url_for("dashboard" if g.user["role"] == "staff" else "home"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            wanted_role = request.form.get("role", "customer")
            user = store.get_db().execute(
                "SELECT * FROM users WHERE email = ?", (email,)
            ).fetchone()
            if user is None or not check_password_hash(user["password_hash"], password):
                flash("Incorrect email or password.", "error")
            elif user["role"] != wanted_role:
                flash("This account can't sign in as "
                      + ("an employee." if wanted_role == "staff" else "a customer."), "error")
            else:
                session.clear()
                session["user_id"] = user["id"]
                nxt = request.args.get("next", "")
                if nxt.startswith("/") and not nxt.startswith("//"):
                    return redirect(nxt)
                return redirect(url_for("index"))
            return render_template("login.html", tab="login", email=email), 401
        return render_template("login.html", tab="login")

    @app.route("/signup", methods=["POST"])
    def signup():
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        error = None
        if not name or not email or not password:
            error = "All fields are required."
        elif "@" not in email or "." not in email.split("@")[-1]:
            error = "Please enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        if error is None:
            try:
                db = store.get_db()
                cur = db.execute(
                    "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, 'customer')",
                    (name, email, generate_password_hash(password)),
                )
                db.commit()
            except sqlite3.IntegrityError:
                error = "An account with that email already exists."
        if error:
            flash(error, "error")
            return render_template("login.html", tab="signup", name=name, email=email), 400
        session.clear()
        session["user_id"] = cur.lastrowid
        flash(f"Welcome, {name}! Your account is ready.", "success")
        return redirect(url_for("home"))

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # ------------------------------------------------- UI-01 search (customer)
    @app.route("/home")
    @login_required("customer")
    def home():
        args = request.args
        default_pickup, default_return = default_dates()
        pickup_raw = args.get("pickup") or default_pickup
        return_raw = args.get("return") or default_return
        vtype = args.get("type") or None
        category = args.get("category") or None
        if vtype and vtype not in store.TYPES:
            vtype = None
        if category and category not in store.CATEGORIES:
            category = None

        pickup, ret, error = validate_dates(pickup_raw, return_raw)
        vehicles = []
        if error:
            flash(error, "error")
        else:
            vehicles = store.search_available(
                store.get_db(), pickup.isoformat(), ret.isoformat(), vtype, category)
        return render_template(
            "home.html", vehicles=vehicles, pickup=pickup_raw, ret=return_raw,
            vtype=vtype or "", category=category or "",
            days=(ret - pickup).days if not error else 0)

    # ------------------------------------------------ UI-02 details (customer)
    @app.route("/vehicles/<vehicle_id>")
    @login_required("customer")
    def vehicle_details(vehicle_id):
        db = store.get_db()
        v = db.execute("SELECT * FROM vehicles WHERE id = ?", (vehicle_id,)).fetchone()
        if v is None:
            abort(404)
        # The customer picks (or changes) their rental days right on this page.
        default_pickup, default_return = default_dates()
        pickup_raw = request.args.get("pickup") or default_pickup
        return_raw = request.args.get("return") or default_return
        pickup, ret, error = validate_dates(pickup_raw, return_raw)
        days = (ret - pickup).days if not error else 0
        available = (not error) and store.is_vehicle_available(
            db, vehicle_id, pickup.isoformat(), ret.isoformat())
        return render_template(
            "details.html", v=v, pickup=pickup, ret=ret, days=days,
            pickup_raw=pickup_raw, return_raw=return_raw,
            date_error=error, available=available,
            back=url_for("home", **{k: request.args[k] for k in ("pickup", "return")
                                     if k in request.args}))

    # ------------------------------------------------ UI-03 reserve (customer)
    @app.route("/vehicles/<vehicle_id>/reserve", methods=["POST"])
    @login_required("customer")
    def reserve(vehicle_id):
        pickup, ret, error = validate_dates(request.form.get("pickup"), request.form.get("return"))
        details = url_for("vehicle_details", vehicle_id=vehicle_id,
                          pickup=request.form.get("pickup"), **{"return": request.form.get("return")})
        if error:
            flash(error, "error")
            return redirect(details)
        try:
            rid = store.create_reservation(
                store.get_db(), g.user["id"], vehicle_id, pickup.isoformat(), ret.isoformat())
        except store.VehicleUnavailable:
            flash("Sorry, this vehicle was just booked for those dates. "
                  "Please choose different dates or another vehicle.", "error")
            return redirect(details)
        return redirect(url_for("confirmation", reservation_id=rid))

    @app.route("/reservations/<int:reservation_id>")
    @login_required("customer")
    def confirmation(reservation_id):
        r = store.get_db().execute(
            """SELECT r.*, v.name AS vehicle, v.type, v.category, v.price_per_day
               FROM reservations r JOIN vehicles v ON v.id = r.vehicle_id
               WHERE r.id = ? AND r.user_id = ?""",
            (reservation_id, g.user["id"]),
        ).fetchone()
        if r is None:  # missing, or someone else's booking (privacy)
            abort(404)
        days = (date.fromisoformat(r["return_date"]) - date.fromisoformat(r["pickup_date"])).days
        return render_template("confirmation.html", r=r, days=days)

    # ----------------------------------------- UI-04 rental history (customer)
    HISTORY_PER_PAGE = 10

    @app.route("/history")
    @login_required("customer")
    def rental_history():
        status = request.args.get("status")
        if status not in store.HISTORY_STATUSES:
            status = None
        rows = store.rental_history(store.get_db(), g.user["id"], date.today().isoformat())
        total_records = len(rows)
        if status:
            rows = [r for r in rows if r["rental_status"] == status]
        pages = max(1, math.ceil(len(rows) / HISTORY_PER_PAGE))
        page = min(max(request.args.get("page", 1, type=int), 1), pages)
        start = (page - 1) * HISTORY_PER_PAGE
        return render_template(
            "history.html", rows=rows[start:start + HISTORY_PER_PAGE], matched=len(rows),
            total_records=total_records, status=status, page=page, pages=pages)

    # ------------------------------------------------ REP-01 dashboard (staff)
    @app.route("/staff/dashboard")
    @login_required("staff")
    def dashboard():
        day = parse_date(request.args.get("date")) or date.today()
        db = store.get_db()
        rows = [dict(r, day_status=store.day_status(r, day.isoformat()))
                for r in store.daily_rentals(db, day.isoformat())]
        stats = store.fleet_stats(db, day.isoformat())
        recent = store.recent_reservations(db)
        return render_template("dashboard.html", day=day, rows=rows, stats=stats, recent=recent,
                               prev_day=day - timedelta(days=1), next_day=day + timedelta(days=1))

    # --------------------------------------------- later sprints (placeholders)
    PLANNED = {
        "reservations": ("My Reservations", "UI-05 Manage Reservation", "Sprint 2", "customer"),
        "profile": ("Profile", "Account management", "Sprint 2", "customer"),
        "staff-vehicles": ("Manage Vehicles", "Manage Vehicle Information (FR-6)", "Sprint 2", "staff"),
        "staff-reservations": ("Reservations", "Monitor Reservations", "Sprint 2", "staff"),
        "staff-reports": ("Reports", "REP-02 / REP-03 Reports", "Sprint 2–3", "staff"),
    }

    @app.route("/planned/<page>")
    def planned(page):
        if page not in PLANNED:
            abort(404)
        title, story, sprint, role = PLANNED[page]
        if g.user is None:
            return redirect(url_for("login"))
        if g.user["role"] != role:
            abort(403)
        return render_template("planned.html", title=title, story=story, sprint=sprint, page=page)

    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403,
                               message="You don't have access to this page."), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Page not found."), 404

    @app.errorhandler(400)
    def bad_request(e):
        return render_template("error.html", code=400, message=e.description), 400


if __name__ == "__main__":
    create_app().run(debug=True)
