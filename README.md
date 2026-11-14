# Car Rental System: Sprint 1 Prototype
CP317B, Group 9

A working prototype built with Python, Flask and SQLite. It's styled after the Milestone 2 wireframes.

## Run it

You need Python 3.10 or newer.

**macOS / Linux**

```bash
cd car-rental-system
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

**Windows (PowerShell)**

```powershell
cd car-rental-system
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Then open http://127.0.0.1:5000 in your browser. Stop the server with `Ctrl+C`.

- The database (`car_rental.db`) is created and filled with demo data the first time the app starts.
- Older `car_rental.db` files are upgraded automatically when new columns are added, so the app won't crash on an old file. Delete it anyway to get the latest demo data.
- **Delete `car_rental.db` before a demo.** The demo rentals are dated around the day the database was created, so a fresh file puts rentals on "today" again.
- On a Mac, if port 5000 is already in use (AirPlay Receiver uses it), run `flask --app app run --port 5001` and open http://127.0.0.1:5001 instead.

## Logins

All demo accounts are created automatically. On the login page, use the button that matches the account's role.

| Role     | Name          | Email                | Password    | Login button              |
|----------|---------------|----------------------|-------------|---------------------------|
| Customer | Jane Doe      | customer@example.com | password123 | Login as Customer         |
| Customer | Michael Brown | michael@example.com  | password123 | Login as Customer         |
| Customer | Sara Lee      | sara@example.com     | password123 | Login as Customer         |
| Customer | Chris Park    | chris@example.com    | password123 | Login as Customer         |
| Staff    | J. Smith      | staff@example.com    | staff123    | Login as Employee (Staff) |

**Sign up:** the Sign Up tab creates a new *customer* account using any name, a valid email that isn't already registered, and a password of at least 8 characters. For example: `Test User` / `test@example.com` / `testpass123`. You're logged in straight away. Staff accounts can't be created through sign-up.

## What it should do

**As a customer** (log in as `customer@example.com`):

1. **Search:** you land on Search Cars. Pick pickup and return dates, and optionally a vehicle type and category, then click **Search Vehicles**. Only cars free for the whole period appear. The Volkswagen Golf never appears because it's in maintenance.
2. **View details:** click **View Details** on a car to see its specs, daily price, and trip total.
3. **Choose your days:** in the "When do you need it?" box, change the pickup or return date and click **Check availability**. The total and availability update. If you change a date without checking, the Reserve button is disabled until you do.
4. **Reserve:** click **Reserve This Vehicle**. A confirmation page shows a reference number (e.g. `R-1007`), the dates, and the total.
5. **No double bookings:** open the same car for overlapping dates. It shows "Booked for these dates" and can't be reserved. Booking from the day the last rental ends is allowed.
6. **Rental History:** click **Rental History** in the top bar. Jane has two completed rentals, one cancelled rental (no charge shown) and today's Toyota Camry as Active. Use the status filter buttons to narrow the list. Upcoming bookings aren't listed here; they're under My Reservations.
7. **My Reservations:** click **My Reservations**. Today's Camry shows as Active ("Rental in progress", no Cancel button). The Honda CR-V is Upcoming with a **Cancel** button and its free-cancellation deadline. Click **Cancel** → **Yes, cancel reservation**. It moves to Past reservations as Cancelled, shows under Cancelled in Rental History, and the CR-V appears in Search again for those dates.

**As staff** (log out, then log in as `staff@example.com` with **Login as Employee (Staff)**):

1. **Daily Rental Report:** the dashboard shows every rental on today's date (pickups, returns, and cars out on rent) plus fleet counts. Use the ‹ › arrows or the date picker to view another day.
2. **Recent bookings:** the reservation you just made is at the top of this table, with the customer, car, rental days, and total. Click its pickup date to jump to that day's report. Cancelled bookings disappear from both the daily report and this table.
3. **Vehicle Utilization Report:** click **Reports**. Switch between the last 7, 30 and 90 days. Vehicles are sorted most-used first, with a utilization bar for each, and the by-type table below shows which kinds of car are used most. The Ford Explorer shows **Service due** (over 10,000 km since its last service), and the Camry and F-150 show **Service soon**.
4. **Log a return:** under **Returns to log**, enter the km driven for Chris Park's Ford Explorer (e.g. 380) and click **Save**. The Explorer's odometer goes up by 380, and customers see the new mileage on its details page. Then click **Mark serviced** on the Explorer; its "Since service" resets to 0 and the status changes to OK.
5. **Manage Vehicles:** click **Vehicles**. Search for "toyota", or filter by type, category or availability. Click **+ Add Vehicle**, fill in e.g. Toyota Corolla / Sedan / Economy / $50 / 5 seats, and save. It gets the next ID (V011) and appears in customer search straight away. Leave a field empty to see the error messages.
6. **Maintenance:** click **Set to Maintenance** on the Honda CR-V. You get a warning that it still has upcoming bookings, and customers no longer see it in search (their existing bookings are kept). Click **Set Available** to bring it back. **Edit** a car to change its price; existing bookings keep their original total.

**Access rules:** customers can't open staff pages and staff can't open customer pages (you get a 403 page). A customer can't view another customer's reservation. Profile and the staff Reservations page are still placeholders for later stories.

## Run the tests

With the virtual environment active:

```bash
python -m pytest -v
```

There are 119 tests, and each one is tagged with the story it checks.

## Sprint 1 stories → code

| Story | What works | Where |
|-------|------------|-------|
| Login / Sign up | Customer and staff login, customer sign-up, hashed passwords, role-based page access, CSRF protection on forms | `app.py` → `login`, `signup`, `login_required` |
| UI-01 Search Available Cars | Search by dates, type and category. Cars in maintenance or already booked for those dates are hidden | `db.py` → `search_available`; `templates/home.html` |
| UI-02 View Car Details | Specs, daily price, a "When do you need it?" date picker, trip total for the chosen days, live availability badge | `app.py` → `vehicle_details`; `templates/details.html` |
| UI-03 Reserve a Car | Books the car and shows a confirmation with a reference number. Overlapping bookings are blocked | `db.py` → `is_vehicle_available`, `create_reservation` |
| UI-04 View Rental History *(Sprint 2)* | Customers see their current and past rentals (vehicle, dates, duration, total, status), filter by Active / Completed / Cancelled, 10 per page. Only their own rentals are shown | `db.py` → `rental_history`, `rental_status`; `app.py` → `rental_history`; `templates/history.html` |
| UI-05 Manage Reservations *(Sprint 2)* | My Reservations lists upcoming and active bookings plus recent past ones. Customers can view each booking and cancel it up to 24 hours before pickup (cars are collected at 10:00), with an "are you sure?" step. Cancelling frees the car in search and removes it from the staff dashboard | `db.py` → `my_reservations`, `cancel_reservation`, `cancel_block_reason`; `app.py` → `my_reservations`, `cancel_reservation`; `templates/reservations.html`, `cancel.html` |
| REP-02 Vehicle Utilization Report *(Sprint 2)* | Staff see each vehicle's rentals, days rented and utilization % for the last 7, 30 or 90 days (plus a by-type summary), km driven, odometer, km since last service, and a maintenance status (OK, Service soon, Service due, In maintenance). Staff log the km driven when a car comes back, which updates its odometer, and can mark a car as serviced | `db.py` → `utilization_report`, `returns_to_log`, `record_return`, `mark_serviced`; `app.py` → `reports`, `log_return`, `mark_serviced`; `templates/reports.html` |
| VEH-01 Manage Vehicles *(Sprint 2)* | Staff see the whole fleet with search (name, type, ID) and type/category/availability filters, add vehicles (the next ID like V011 is assigned automatically), edit details and price, and switch a car between Available and Maintenance. Maintenance cars are hidden from customer search; staff get a warning if the car still has upcoming bookings. Price changes only affect new bookings | `db.py` → `list_vehicles`, `validate_vehicle`, `add_vehicle`, `update_vehicle`, `set_vehicle_status`; `app.py` → `manage_vehicles`, `add_vehicle`, `edit_vehicle`, `vehicle_status`; `templates/vehicles.html`, `vehicle_form.html` |
| REP-01 Daily Rental Report | Staff pick any date to see every rental that day plus fleet stats. A Recent bookings panel shows new reservations (with their rental days) as soon as they're made | `db.py` → `daily_rentals`, `fleet_stats`; `templates/dashboard.html` |

The nav links for later stories (Profile, staff Reservations) go to "Planned for Sprint 2/3" pages.

## Design notes worth mentioning in the report

- **Double-booking prevention (FR-10):** two rentals overlap when `existing.pickup < new.return AND existing.return > new.pickup`. Same-day turnaround is allowed, so a car returned on the 15th can be picked up again on the 15th. The check and the insert run inside one `BEGIN IMMEDIATE` transaction, so two people booking the same car at the same moment can't both succeed.
- **Privacy:** customers can only open their own reservations. Anyone else's returns a 404.
- **Accessibility:** every status badge shows text and never relies on colour alone. The app also has form labels, a skip link, visible focus outlines, and a layout that works on mobile.
- **Seed data is relative to today**, so the staff dashboard always has rentals to show during a demo.

## Project layout

```
app.py              routes, auth, validation
db.py               schema, seed data, availability + report queries
templates/          Jinja HTML pages
static/style.css    styling (matches wireframes)
tests/test_app.py   pytest suite
screenshots/        screenshots for the Sprint 1 report
```
