# Campus Maintenance and Complaint Management System (CampusFix)

A Django web application where students and faculty report campus maintenance
problems and the administrator assigns a maintenance worker and tracks each
complaint as **Open**, **In Progress** or **Closed**.

Second-year B.Tech CSE college project. Python, Django, SQLite, HTML/CSS
(no JavaScript), Pandas, NumPy and Matplotlib.

---

## 1. Problem statement

Complaints about classrooms, labs, washrooms, electrical fittings, furniture or
water supply are often reported verbally, by phone or through informal messages.
That makes it hard to:

- know the current status of a complaint,
- know who is responsible for it,
- notice when work is overdue,
- see locations where the same kind of problem keeps coming back.

> **Note:** This is a common situation, but it is not true for every college.
> Before presenting it as a real problem for *your* campus, confirm it by
> talking to a few students, faculty members and maintenance staff.

## 2. Proposed solution

One web application that:

1. lets students and faculty submit complaints and receive a unique reference ID,
2. **automatically** sets a priority and deadline using simple documented rules,
3. keeps every new complaint **Open** until the administrator assigns a worker from an
   **"Assign to" drop-down** (there is no automatic assignment),
4. gives the administrator a simple tracker with only three words:
   **Open** (no worker yet), **In Progress** (worker assigned) and **Closed** (work done),
5. records every status change in a history table,
6. produces analytics charts with Pandas, NumPy and Matplotlib.

## 3. Roles and features

The login page has a **"Login as"** drop-down with two options: *Student / Faculty*
and *Administrator*. The choice must match the account's real role (checked on the server).

| Role | Logs in? | What they can do |
|------|----------|------------------|
| **Student / Faculty** | Yes ("Login as: Student / Faculty") | Register, submit complaints (with optional photo), see only their own complaints, view status history, confirm a fix (closes the complaint) or request reopening |
| **Administrator** | Yes ("Login as: Administrator") | Sees every complaint as **Open**, **In Progress** or **Closed**, with priority **Low**, **Medium** or **High** (filterable). **Assign** a worker from a drop-down (Open → In Progress), add work notes, **Close** when the work is done (In Progress → Closed), decide reopening requests, view analytics charts, export CSV, analyse a historical CSV |
| **Maintenance worker** | **No** | A name in the "Assign to" drop-down (e.g. *Ramesh Kumar (Electrical)*). Workers have no password; the administrator records their work. |

### Automatic rules (in `complaints/services.py`)

**Priority rules**

1. Start with the urgency selected by the reporter (Low / Medium / High / Urgent).
2. Electrical, plumbing and water-supply complaints are at least **Medium**.
3. If the title or description contains a safety word (fire, smoke, spark, shock,
   exposed wire, short circuit, gas leak, flood, collapse and others), the priority
   becomes **Urgent**.
4. The reporter is told the complaint may be a safety risk and was marked Urgent.
   The system cannot check whether a hazard is real.

**Deadline rule:** deadline = submission time + target hours for the priority.
A reopened complaint gets a fresh deadline from the moment it is reopened.

| Priority | Example target time |
|----------|--------------------|
| Urgent | 4 hours |
| High | 24 hours |
| Medium | 72 hours |
| Low | 7 days |

These are **example demonstration values, not official college service
guarantees**. They are stored in the `PriorityDeadline` table; a superuser can
change them in the Django admin site at `/django-admin/`.

**Overdue:** deadline has passed **and** status is not Resolved or Closed. This is
calculated each time a dashboard loads, so no background scheduler is needed.

**Assignment is done by the administrator only.** A new complaint is never
assigned automatically. It shows as **Open** on the administrator's dashboard,
where each row has its own "Assign to" drop-down. Assigning moves it to
**In Progress**. The administrator can also change the worker of any In
Progress complaint.

**Closing.** The administrator can close both **Open** and **In Progress**
complaints (each row on the dashboard has a *Close* button), for example a
duplicate complaint can be closed without assigning anyone. A note is required.

**Status transitions**

```
Submitted  -> Assigned, Closed
Assigned   -> In Progress, Resolved, Closed
In Progress-> Resolved, Closed
Resolved   -> Closed (reporter confirms / admin), Reopened (admin approves request)
Reopened   -> In Progress, Resolved, Closed
Closed     -> (final)
```

**What the administrator sees.** The detailed statuses above are kept in the
database (for the history and the reporter's view), but the administrator's
pages show only three words:

| Administrator sees | Detailed statuses | How it gets there |
|---|---|---|
| **Open** | Submitted | Complaint submitted, no worker yet |
| **In Progress** | Assigned, In Progress, Reopened | Administrator assigns a worker |
| **Closed** | Resolved, Closed | Administrator chooses *Close complaint*, with a note (from Open or In Progress) |

Admin pages also show priority as only **Low**, **Medium** or **High**. A complaint the
safety rules marked *Urgent* is shown to the administrator as **High**.

Closing needs a note. Closing sets
the detailed status to *Resolved*, so the reporter can still confirm the fix or
ask for reopening. A reopening request is shown as a **Reopen requested** badge;
the administrator approves (back to In Progress, or back to Open if no worker
was assigned) or rejects it.

All admin lists are **arranged by date, newest complaint first**.

## 4. Technology stack

| Technology | Used for |
|-----------|----------|
| Python 3.11+ (tested on 3.13) | Backend language |
| Django 5.2 | Web framework, authentication, ORM, forms, templates, migrations |
| SQLite | Database (one file, no server needed) |
| HTML5 + CSS3 | Pages and responsive styling (no JavaScript at all) |
| Pandas | Grouping, counting, cleaning CSV data, monthly trends |
| NumPy | Mean / median / 90th percentile resolution time, recurring-pattern window search |
| Matplotlib | Server-side PNG charts shown as static images |
| Pillow | Required by Django's `ImageField` to verify uploaded photos |

## 5. Project structure

```
campus_maintenance/
├── manage.py                     Django command-line tool
├── requirements.txt              Python packages with exact versions
├── README.md                     This file
├── VIVA_NOTES.md                 Viva questions, explanations, demo script
├── .gitignore                    Files that must not go to GitHub
├── .env.example                  Example environment variables
├── config/
│   ├── settings.py               All settings (database, apps, upload limits)
│   ├── urls.py                   Sends URL prefixes to each app
│   └── wsgi.py                   Entry point for web servers
├── accounts/                     Users and roles
│   ├── models.py                 Profile (role, department, phone)
│   ├── permissions.py            get_role(), role_required decorator
│   ├── context_processors.py     Puts user_role into every template
│   ├── forms.py                  RegistrationForm, StaffCreateForm
│   ├── views.py                  home redirect, register, staff management
│   ├── urls.py                   /, /login/, /logout/, /register/, /staff/...
│   ├── admin.py                  Django admin registration
│   ├── migrations/               Database migration files
│   └── tests.py                  Registration and staff-management tests
├── complaints/                   Main complaint workflow
│   ├── models.py                 Complaint, ComplaintStatusHistory,
│   │                             PriorityDeadline, ReopenRequest
│   ├── services.py               All business rules (priority, deadline, assignment,
│   │                             transitions, overdue, reopening)
│   ├── forms.py                  Complaint, staff update, admin and filter forms
│   ├── views.py                  Dashboards, detail page, all actions
│   ├── urls.py                   /complaints/... routes
│   ├── admin.py                  Django admin registration
│   ├── management/commands/seed_demo.py   Creates demo data
│   ├── migrations/
│   └── tests.py                  Submission, rules, permissions, history, overdue, reopening
├── analytics_app/                Reports
│   ├── analysis.py               Pandas/NumPy statistics, CSV cleaning, Matplotlib charts
│   ├── forms.py                  Historical CSV upload form
│   ├── views.py                  Analytics page, CSV export, historical upload
│   ├── urls.py                   /analytics/... routes
│   └── tests.py                  Export, CSV validation, empty/incomplete data
├── templates/
│   ├── base.html                 Shared layout (header, navigation, messages)
│   ├── home.html, 403.html, 404.html
│   ├── includes/                 form_fields.html, badges.html
│   ├── accounts/                 login, register
│   ├── complaints/               dashboards, form, detail, lists, settings
│   └── analytics_app/            dashboard, historical_upload, _report
├── static/
│   ├── css/style.css             All styling
│   └── samples/historical_complaints_sample.csv
└── media/                        Uploaded photos (private, git-ignored)
```

### How a request flows through Django

```
Browser ──> config/urls.py ──> app urls.py ──> view function
                                                │  1. checks login + role (permissions.py)
                                                │  2. validates form input (forms.py)
                                                │  3. runs rules (services.py)
                                                │  4. reads/writes database (models.py → SQLite)
                                                ▼
                                    template (templates/*.html) ──> HTML page to browser
```

Example: submitting a complaint
`POST /complaints/new/` → `complaints/urls.py` → `views.complaint_create` →
`ComplaintForm` validates → `services.submit_complaint()` calculates priority,
deadline, saves, assigns staff and writes history → redirect to the
confirmation page with the reference ID.

## 6. Database design

```
User (Django built-in)
 ├── 1 ─── 1  Profile                (role: student / faculty / staff / admin)
 ├── 1 ─── *  Complaint.reporter     (who reported it)
 ├── 1 ─── *  Complaint.assigned_to  (staff member, may be empty)
 └── 1 ─── *  ReopenRequest.requested_by / reviewed_by

Complaint
 ├── 1 ─── *  ComplaintStatusHistory
 └── 1 ─── *  ReopenRequest

PriorityDeadline   (one row per priority, stand-alone setting)
```

| Model | Important fields | Notes |
|-------|-----------------|-------|
| **Profile** | `user` (OneToOne), `role`, `department`, `phone` | Extends Django's User without replacing it. Superusers are always treated as admin. |
| **Complaint** | `reference_id` (unique), `reporter`, `title`, `description`, `category`, `building`, `floor`, `room`, `reported_urgency`, `priority`, `safety_review_needed`, `status`, `assigned_to`, `submitted_at`, `deadline`, `resolved_at`, `resolution_notes`, `photo`, `resolution_photo`, `reopen_count`, `updated_at` | `reference_id` = `CMP-<year>-<id>`, made from the unique database id after the first save. A check constraint stops `resolved_at` from being before `submitted_at`. `reporter` uses PROTECT so complaint records are not lost if someone tries to delete a user. |
| **ComplaintStatusHistory** | `complaint`, `old_status`, `new_status`, `changed_by`, `note`, `created_at` | One row per status change or work note. `changed_by` = who made the change. |
| **PriorityDeadline** | `priority` (unique), `target_hours` (1–720) | Configurable deadlines. Defaults in `services.py` are used if a row is missing. |
| **ReopenRequest** | `complaint`, `requested_by`, `reason`, `status` (pending/approved/rejected), `admin_note`, `reviewed_by`, `reviewed_at` | A partial unique constraint allows only one *pending* request per complaint. |

Location is stored once in the complaint (building, floor, room) and the
building name is cleaned (`"  main   block "` → `"Main Block"`) so analytics
can group it reliably.

## 7. Security

- Django authentication; passwords are stored as salted PBKDF2 hashes, never as plain text.
- Password strength validators on registration.
- Every view checks the role on the server with `role_required(...)`. Hiding buttons is only cosmetic.
- Students see only their own complaints; staff only complaints assigned to them;
  anyone else gets **404**, so the system does not even reveal that a complaint exists.
- Nobody can register as staff or admin; staff accounts are created by the admin.
- All state-changing actions use POST forms with Django's CSRF token. Logout is also POST.
- Uploads: only `.jpg/.jpeg/.png`, max 2 MB, content verified by Pillow, saved
  under a random file name.
- **Uploaded photos are private.** There is no public `/media/` URL; photos are
  served by `complaint_photo` only after the same permission check as the complaint.
- CSV upload: `.csv` only, max 2 MB and 20,000 rows, UTF-8 only, read as plain text
  (`dtype=str`), never saved to the database.
- CSV export: admin only, and cells starting with `= + - @` are prefixed with `'`
  to prevent spreadsheet formula injection.
- Template auto-escaping prevents HTML/script injection in complaint text.
- Secret key, debug flag and allowed hosts come from environment variables. The
  fallback key in `settings.py` is for local development only.
- `db.sqlite3`, `media/` and `.env` are in `.gitignore`.

## 8. Installation (Windows PowerShell)

Requires Python 3.11 or newer (`python --version`).

```powershell
# 1. Go to the project folder
cd C:\path\to\campus_maintenance

# 2. Create and activate a virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1
# If you see "running scripts is disabled", run this once, then activate again:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 3. Install the packages
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4. Create the database tables
python manage.py migrate

# 5. Create your own administrator account (choose your own password)
python manage.py createsuperuser

# 6. (Optional) Load demo data - test accounts and sample complaints
python manage.py seed_demo

# 7. Start the server
python manage.py runserver
```

Open http://127.0.0.1:8000/ in a browser. Stop the server with `Ctrl + C`.

If you change a model later, run:

```powershell
python manage.py makemigrations
python manage.py migrate
```

## 9. Demo data and test accounts

`python manage.py seed_demo` creates test accounts, 7 maintenance workers,
assignment rules, deadline settings and 9 sample complaints (2 Open, 3 In Progress, 4 Closed; Low, Medium and High priority) spread over about
five months. The sample data includes complaints waiting for the admin to assign
a worker, work in progress, Overdue, Safety-review, disputed (pending
reopening) and repeatedly reopened complaints.

**Login accounts** — all use the password **`DemoPass@2026`**. These are
**test accounts for demonstration only** (choose your own with
`python manage.py seed_demo --password "YourDemoPassword"`).

| Username | Choose in "Login as" | Role |
|----------|---------------------|------|
| `admin_demo` | Administrator | Administrator (Asha Menon) |
| `student_demo`, `student_two`, `student_three` | Student / Faculty | Student |
| `faculty_demo`, `faculty_two` | Student / Faculty | Faculty |

**Maintenance workers** (no login, shown in the "Assign to" drop-down):

| Worker | Team |
|--------|------|
| Ramesh Kumar | Electrical |
| Anil Verma | Electrical |
| Suresh Patil | Plumbing |
| Mahesh Yadav | Carpentry |
| Lata Devi | Housekeeping |
| Imran Shaikh | IT Support |
| Gopal Singh | Civil / Masonry |

Workers are not managed in the app; a superuser can add or edit them in the
Django admin site (`/django-admin/`).

To start again with fresh sample complaints: `python manage.py seed_demo --reset`.

## 10. Analytics, CSV export and historical CSV

**Analytics page** (`/analytics/`, admin only) shows **four charts only**:

1. complaints by category (bar chart),
2. complaints by building, top 10 (bar chart),
3. monthly trend of submitted vs resolved (line chart),
4. open complaints by priority, within deadline vs overdue (stacked bar chart).

`analytics_app/analysis.py` also calculates average/median/90th-percentile
resolution time, overdue percentage, most reported locations and **potential
recurring patterns** (at least 2 complaints with the same category at the same
normalised location within 30 days). These are covered by the automated tests
but are not displayed, to keep the page to charts only.

**Admin dashboard boxes are clickable.** The three boxes (Open, In Progress,
Closed) each open *All Complaints* showing only those complaints, using the
same rule as the count, so the number in the box always matches the list.

**CSV export** (`/analytics/export/`) downloads all complaints. From *All
Complaints* you can export only the filtered rows.

**Historical CSV analysis** (`/analytics/historical/`) creates an independent
report from an uploaded file. Nothing is inserted into the live database.

| Column | Required | Example |
|--------|----------|---------|
| `complaint_id` | Yes | H-001 |
| `category` | Yes | electrical |
| `building` | Yes | Main Block |
| `priority` | Yes | low / medium / high / urgent |
| `status` | Yes | submitted / assigned / in_progress / resolved / reopened / closed |
| `submitted_at` | Yes | 2025-07-03 09:15 |
| `floor` | No | 2 |
| `room` | No | 204 |
| `resolved_at` | No | 2025-07-04 16:00 (blank if unresolved) |

Handling of bad data: rows with no category, building or valid submitted date
are skipped; unreadable or impossible resolved dates are ignored; unknown
priorities/statuses are shown as "unknown". Every correction is listed as a
warning on the page. A sample file is at
`static/samples/historical_complaints_sample.csv` (also downloadable from the
upload page). It contains 2 deliberately invalid rows so you can show the cleaning.

## 11. Testing

### Automated tests

```powershell
python manage.py test
```

103 tests in `accounts/tests.py`, `complaints/tests.py` and `analytics_app/tests.py` cover:

| # | Area | Example test |
|---|------|--------------|
| 1 | Valid submission | `test_valid_submission_creates_complaint` |
| 2 | Unique IDs | `test_reference_ids_are_unique` |
| 3 | Admin-only assignment | `test_new_complaint_is_never_assigned_automatically`, `test_admin_can_assign_manually` |
| 4 | Ordering and closing | `test_admin_lists_are_newest_first_with_close_buttons`, `test_open_complaint_can_be_closed` |
| 5 | Priority & deadline | `test_safety_keyword_makes_urgent_and_flags_review`, `test_default_deadline_hours` |
| 6 | Student access | `test_student_cannot_view_other_students_complaint`, `test_other_student_cannot_see_photo` |
| 7 | Worker / login restrictions | `test_worker_account_has_no_access`, `test_worker_cannot_log_in`, `test_student_cannot_log_in_as_admin` |
| 8 | Status updates | `test_assigned_complaint_shows_as_in_progress`, `test_admin_closes_complaint`, `test_close_needs_an_assigned_worker`, `test_admin_pages_show_only_three_tracking_words` |
| 9 | History | `test_status_change_is_recorded_in_history` |
| 10 | Overdue / dashboard | `test_resolved_complaint_is_never_overdue`, `test_dashboard_boxes_open_matching_lists` |
| 11 | Reopening | `test_admin_approval_reopens_complaint`, `test_duplicate_pending_request_is_blocked` |
| 12 | Invalid forms/uploads | `test_non_image_upload_is_rejected`, `test_oversized_photo_is_rejected` |
| 13 | CSV export | `test_admin_can_export_csv`, `test_formula_values_are_neutralised` |
| 14 | Invalid CSV | `test_missing_columns_rejected`, `test_invalid_values_are_handled` |
| 15 | Empty/incomplete analytics | `test_empty_dataset_report`, `test_incomplete_dataset_without_resolved_dates` |

Run one app only: `python manage.py test complaints`.
Run one test: `python manage.py test complaints.tests.ReopenTests.test_admin_approval_reopens_complaint`.

### Manual testing checklist

Use the demo accounts. Tick each item.

**Login page**
- [ ] The "Login as" drop-down shows only *Student / Faculty* and *Administrator*.
- [ ] `student_demo` with "Login as: Administrator" → error, not logged in.
- [ ] `admin_demo` with "Login as: Student / Faculty" → error, not logged in.
- [ ] A worker username (e.g. `staff_electric`) cannot log in.

**Student / faculty**
- [ ] Register a new student account; weak or mismatched passwords show errors.
- [ ] Submit a complaint with an empty title → error message, nothing saved.
- [ ] Upload a `.gif` or a renamed text file as photo → rejected.
- [ ] Submit a valid electrical complaint → confirmation page shows `CMP-...` ID, *Submitted*, "Waiting for the administrator to assign", deadline.
- [ ] Submit a complaint whose description says "sparks from socket" → *Urgent*, safety warning shown.
- [ ] Submit a complaint in category *Other* → *Submitted*, "Waiting for the administrator to assign".
- [ ] Dashboard shows totals and only your own complaints.
- [ ] Change the URL to another user's complaint id → 404 page.
- [ ] Open `/complaints/admin/` → 403 page.

**Administrator (`admin_demo`)**
- [ ] Admin menu shows only Dashboard, All Complaints and Analytics.
- [ ] Dashboard shows three boxes: Open, In Progress, Closed. No other status words appear.
- [ ] *Open* list: pick a worker in a row's drop-down → *Assign* → it moves to *In Progress*.
- [ ] Open an In Progress complaint → *Change worker* → history entry.
- [ ] *Close or add a note*: add a work note → history entry, still In Progress.
- [ ] Choose *Close complaint* with no note → error. Add a note and a photo → *Closed*.
- [ ] Click *Close* on an **Open** complaint (no worker) → write a note → it moves to *Closed*.
- [ ] Submit a new complaint as a student → it appears at the **top** of the admin's *Open* list (newest first), with no worker.
- [ ] Click each box → the list shows only those complaints and the count matches the box.

**Student again**
- [ ] Open the resolved complaint → *Is it fixed?* box. Request reopening with a reason.

**Administrator again**
- [ ] The closed complaint shows a *Reopen requested* badge. Approve it → back to *In Progress*.
- [ ] Analytics page shows only the four charts (no tables).
- [ ] Export CSV and open it in Excel (status column shows Open / In Progress / Closed).
- [ ] Upload the sample CSV → report plus cleaning warnings. Upload a `.txt` or a CSV with wrong columns → clear error. Check that *All Complaints* did not grow.

**Layout**
- [ ] Shrink the browser to phone width: navigation wraps, tables scroll sideways, forms stay usable.
- [ ] Disable JavaScript in the browser: everything still works (the project has none).

## 12. Screenshots checklist (for report / GitHub)

1. Home page
2. Registration page with a validation error
3. Complaint form
4. Confirmation page with reference ID
5. Student dashboard
6. Complaint detail with status history timeline
7. Login page with the "Login as" drop-down
8. Complaint page with the "Assign to" drop-down and Close form
9. Admin dashboard (Open / In Progress / Closed boxes and lists)
10. Reopening request review
11. Analytics page with charts
12. Historical CSV report with cleaning warnings
13. Exported CSV opened in Excel
14. Mobile view of a dashboard
15. Terminal showing `python manage.py test` passing

Use only demo data in screenshots; never real names or photos.

## 13. Troubleshooting

| Problem | Fix |
|---------|-----|
| `python` not recognised | Install Python from python.org and tick "Add python.exe to PATH", or use `py` instead of `python`. |
| `Activate.ps1 cannot be loaded because running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, then activate again. |
| `ModuleNotFoundError: No module named 'django'` | The virtual environment is not active. Run `.\venv\Scripts\Activate.ps1` (you should see `(venv)` in the prompt). |
| `no such table: ...` | Run `python manage.py migrate`. |
| Page has no styling when `DJANGO_DEBUG=False` | Django's development server only serves CSS when DEBUG is True. Keep DEBUG True for local demos. |
| "Your account has no role yet" | The user was created in Django admin without a Profile. Add a Profile for them in `/django-admin/`. |
| Port 8000 already in use | `python manage.py runserver 8080` |
| Forgot admin password | `python manage.py changepassword <username>` |
| Want a clean start | Stop the server, delete `db.sqlite3` and the files inside `media/`, then `migrate` and `seed_demo` again. |
| Matplotlib font cache message on first run | Normal; it only happens once. |

## 14. Known limitations

- Safety detection is keyword-based. It can miss hazards described in other words
  and can flag harmless text (e.g. "fire extinguisher missing").
- Every complaint must be assigned by the administrator; there is no automatic routing or workload balancing.
- No email/SMS notifications; users check the website.
- Assignment rules and deadline hours have no page in the app; they are changed
  in the Django admin site by a superuser. Changing deadline hours does not change
  deadlines of existing complaints.
- Overdue is calculated when a page loads, not pushed as an alert.
- Locations are free text; the analysis normalises spelling/spacing but "Lab 3" and
  "Computer Lab 3" are still treated as different places.
- SQLite and Django's development server are fine for a demo, not for many users at once.
- Workers do not log in, so progress is only as up to date as the administrator records it.
  A future version could give workers their own login again.
- Workers are not managed inside the app; they are added or edited in the Django admin site by a superuser.
- The administrator sees only Open / In Progress / Closed, so details such as overdue
  or priority are not shown on admin pages (they still exist in the data and the charts).

## 15. Future improvements

- Email notifications when status changes (Django's `send_mail`).
- Fixed building/room list maintained by the admin instead of free text.
- Suggest a worker in the drop-down based on the complaint's category.
- Feedback rating after a complaint is closed.
- PostgreSQL and a production server (Gunicorn/Nginx) for real deployment.
- Department-wise reports and PDF export.

## 16. Publishing on GitHub

Create an empty repository on GitHub first (no README), then:

```powershell
cd C:\path\to\campus_maintenance
git init
git add .
git status          # check that venv/, db.sqlite3 and media/ files are NOT listed
git commit -m "Campus Maintenance and Complaint Management System"
git branch -M main
git remote add origin https://github.com/<your-username>/campus-maintenance.git
git push -u origin main
```

Never commit real passwords, a real secret key, real complaint photos or the
`db.sqlite3` file.
