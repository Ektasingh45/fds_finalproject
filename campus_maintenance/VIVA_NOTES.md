# Viva and Presentation Notes

Simple explanations you can say in your own words during the viva.

---

## 1. The project in one minute

"Our project is a Campus Maintenance and Complaint Management System built with
Django. There are two logins, chosen from a 'Login as' drop-down: Student /
Faculty and Administrator. Students and faculty report problems like a broken
fan or a leaking tap, and each complaint gets a unique ID. Simple rules decide
the priority and deadline. Nothing is assigned automatically: the
administrator picks a worker from an 'Assign to' drop-down, or closes the
complaint directly (for example a duplicate). Workers don't log in. The administrator tracks every complaint with
just three words: Open (no worker yet), In Progress (worker assigned) and
Closed (work done). Every change is saved in a history table. Finally, we use Pandas, NumPy and Matplotlib to show
charts of complaints per category and per building, monthly trends and
overdue work by priority."

## 2. Problem and solution

**Problem:** complaints given verbally or by phone are easy to forget, nobody
knows their status, it is unclear who is responsible, overdue work is not
noticed, and repeated problems in the same room are not visible.

**Solution:** one central website with tracking IDs, admin assignment,
deadlines, a status history and analytics.

We should say honestly that this problem should be confirmed by talking to
students, faculty and maintenance staff at our own college.

## 3. End-to-end workflow

1. Student chooses "Login as: Student / Faculty", logs in and fills the complaint form.
2. Django validates the form on the server.
3. `submit_complaint()` in `services.py`:
   - calculates priority with the rules,
   - calculates the deadline,
   - saves the complaint (the reference ID is created from the database id),
   - leaves it Open for the admin (no automatic assignment),
   - writes the history row.
4. Student sees the confirmation page with the ID.
5. Admin ("Login as: Administrator") sees it at the top of the Open list (newest first),
   assigns a worker from the drop-down (In Progress), and closes it with a note when done.
6. Student either confirms (complaint becomes *Closed*) or requests reopening.
7. Admin reviews the reopening request: approve → *Reopened* with a new deadline; reject → stays *Resolved*.
8. Throughout, overdue complaints are detected whenever a dashboard is opened.

## 4. The three Django apps

| App | Responsibility | Key files |
|-----|---------------|-----------|
| `accounts` | Registration, login, roles, staff accounts | `models.py` (Profile), `permissions.py` (get_role, role_required) |
| `complaints` | Complaint workflow and admin supervision | `models.py`, `services.py` (all rules), `views.py`, `forms.py` |
| `analytics_app` | Reports, charts, CSV export/upload | `analysis.py` (Pandas/NumPy/Matplotlib), `views.py` |

`config/` holds the project settings and the main URL file.

## 5. Django concepts used

- **Model**: a Python class that becomes a database table. `Complaint` → table `complaints_complaint`.
- **Migration**: a file that describes how to create/change tables. `makemigrations` writes it, `migrate` applies it.
- **View**: a Python function that receives a request and returns a response (usually an HTML page).
- **URL pattern**: connects a URL like `/complaints/new/` to a view.
- **Template**: HTML with placeholders like `{{ complaint.title }}`. All pages extend `base.html` (template inheritance).
- **Form**: validates user input on the server and shows error messages. `ModelForm` builds a form from a model.
- **Authentication**: Django's `User` model, login/logout views and password hashing.
- **Decorator**: `@role_required(ROLE_ADMIN)` wraps a view and blocks other roles.
- **Context processor**: makes `user_role` available in every template for the navigation menu.
- **Management command**: `seed_demo` is our own `python manage.py` command.
- **Messages framework**: the green/red notices after an action.

## 6. Why Django and SQLite?

- Django includes authentication, an admin site, forms, an ORM, CSRF protection and
  migrations, so we did not have to build those ourselves.
- Python is the language we know best, and Pandas/NumPy/Matplotlib are also Python.
- SQLite needs no installation; the whole database is one file. It is enough for a
  college demo. For real use we would switch to PostgreSQL by changing settings.

## 7. Assignment by the administrator

There is no automatic assignment. Every new complaint is Open with no worker.
On the dashboard each Open row has an "Assign to" drop-down listing the active
workers; choosing one calls `assign_complaint()` in `services.py`, which saves
the worker, changes the status to Assigned (shown as In Progress) and writes a
history row. The admin can change the worker later, or close an Open or In
Progress complaint with a note.

## 8. Priority and deadline

Priority rules:
1. start from the reporter's urgency,
2. electrical/plumbing/water supply are at least Medium,
3. safety words like "spark", "fire", "exposed wire" make it Urgent,
4. the reporter is warned that an Urgent complaint may be a safety risk.

Deadline = submission time + target hours (example values: 4, 24, 72 and 168
hours). The admin can change these values. Overdue = deadline passed and status
not Resolved/Closed. This is checked with a database query each time a page
loads, so we don't need a background scheduler.

## 9. Pandas, NumPy, Matplotlib

- **Pandas**: we load complaints into a DataFrame and use `value_counts`,
  `groupby`, `to_period("M")` for monthly trends, `to_datetime(errors="coerce")`
  to handle bad dates, and filtering for cleaning the uploaded CSV.
- **NumPy**: `np.mean`, `np.median`, `np.percentile` for resolution time, and
  `np.searchsorted` to find how many complaints fall within a time window for
  recurring patterns.
- **Matplotlib**: draws bar, line and stacked bar charts on the server with the
  "Agg" backend, saves them as PNG in memory, converts them to base64 and shows
  them in an `<img>` tag. No JavaScript is needed.

## 10. Database relationships

- User 1–1 Profile (role).
- User 1–many Complaint as reporter; User 1–many Complaint as assigned staff (can be empty).
- Complaint 1–many ComplaintStatusHistory.
- Complaint 1–many ReopenRequest.
- PriorityDeadline is a stand-alone settings table.

## 11. Security decisions

- Passwords hashed by Django (PBKDF2 with salt).
- Role checks on the server for every view, not just hidden buttons.
- Other users' complaints return 404.
- CSRF tokens on every POST form; logout is POST.
- Photo uploads: type, size and real image content are checked; random file names;
  photos served only through a permission-checked view.
- CSV upload: extension, size, row count and encoding checks; values read as text; never saved.
- CSV export: admin only; formula injection prevented.
- Secret key from an environment variable; database, uploads and `.env` are git-ignored.

## 12. Testing

99 automated tests with Django's `TestCase`, which uses a separate temporary
test database. They cover submission, IDs, assignment, priority, deadlines,
permissions, status changes, history, overdue, reopening, invalid uploads, CSV
export and import, and empty/incomplete analytics. We also wrote a manual
testing checklist in the README.

Limitations: keyword safety detection is basic, no notifications, no workload
balancing, free-text locations.

---

## 13. Likely viva questions

1. **What is the main purpose of your project?**
   To give one place where campus maintenance complaints are reported, assigned by the administrator, tracked until fixed and analysed.

2. **Why did you choose Django?**
   It has built-in authentication, forms, ORM, admin and security features, and it uses Python, which we also use for data analysis.

3. **What is the difference between a model, a view and a template?**
   The model is the data/table, the view is the logic that handles a request, and the template is the HTML shown to the user.

4. **How is the complaint ID generated?**
   After the first save, the complaint gets a unique database id. We build `CMP-<year>-<id padded to 5 digits>` from it and save again. Since the id is unique, the reference ID is unique, and the field also has a unique constraint.

5. **How is a complaint assigned?**
   Only by the administrator. New complaints stay Open; the admin picks a worker from the "Assign to" drop-down, which moves the complaint to In Progress. We removed automatic assignment so one person decides who does each job.

6. **What happens if the electrician is on leave?**
   The admin simply picks another worker from the drop-down, or changes the worker of complaints already given to them.

7. **Can a student mark their own complaint as resolved?**
   No. The close view is protected with `@role_required(ROLE_ADMIN)`, so only the administrator can change the status. A student can only confirm a complaint that was already resolved, or request reopening.

7a. **Why don't maintenance workers log in?**
   To keep one person in control: the administrator assigns work and closes it. Workers are stored as users with no password (`set_unusable_password()`), so they appear in the drop-down but cannot log in.

7b. **How does the "Login as" drop-down work, and can someone cheat with it?**
   It's a field on our `RoleLoginForm`. After Django checks the password, the form compares the chosen option with the account's real role on the server. A student who picks "Administrator" gets an error and is not logged in. Even if someone bypassed the form, every admin view still checks the role.

7c. **Why does the administrator see only Open, In Progress and Closed?**
   To keep tracking simple. The database still stores detailed statuses (Submitted, Assigned, Resolved...) for the history and the student's view. A small mapping in `models.py` (`TRACKING_GROUPS`) turns them into the three words, and a template filter shows them on admin pages.

8. **How do you detect overdue complaints?**
   A query: deadline is less than now and status is not Resolved or Closed. It runs every time a dashboard loads.

9. **Why not use a scheduler like Celery to check deadlines?**
   It adds complexity. Since overdue status is only needed when someone looks at a dashboard, calculating it at that moment is enough.

10. **How does the system know a complaint is a safety issue?**
    It looks for words like fire, spark, shock or exposed wire. It cannot verify the hazard, so it only marks it Urgent and asks the admin to review it.

11. **What is a migration?**
    A file that records changes to models so Django can create or alter database tables. We run `makemigrations` and then `migrate`.

12. **How are passwords stored?**
    Django stores a salted PBKDF2 hash, not the password itself. Even the admin cannot read it.

13. **What is CSRF and how do you prevent it?**
    Cross-Site Request Forgery tricks a logged-in user's browser into sending a request. Django adds a secret token to each form with `{% csrf_token %}` and rejects POST requests without it.

14. **How do you stop a student from opening another student's complaint by changing the URL?**
    `get_visible_complaint()` checks that the user is the reporter or an admin. Otherwise it returns 404.

15. **Why are uploaded photos not in a public folder?**
    Photos could show private areas. They are served by a view that first checks permission, so only people allowed to see the complaint can see its photo.

16. **Where do you use Pandas?**
    Converting complaints to a DataFrame, counting by category and building, monthly trends with `to_period`, and cleaning uploaded CSV files.

17. **Where do you use NumPy, and why?**
    For mean, median and 90th-percentile resolution time, and `searchsorted` to count complaints inside a time window for recurring patterns. NumPy works directly on arrays, which makes these calculations short and fast.

18. **How are charts shown without JavaScript?**
    Matplotlib draws the chart on the server into a PNG in memory. We encode it as base64 and put it in an `<img src="data:image/png;base64,...">` tag.

19. **What is a "potential recurring pattern"?**
    At least N complaints with the same category at the same cleaned location within D days. It suggests a place to inspect, but it does not prove the same fault caused them.

20. **What if someone uploads a wrong CSV file?**
    We check the extension, size, encoding and required columns and show a clear error. Bad rows are skipped or fixed with warnings. Nothing is saved to the database.

21. **What is CSV injection and how did you handle it?**
    A cell starting with `=` can run as a formula in Excel. In the export we add an apostrophe before such values.

22. **Why does the reopening request need admin approval?**
    So disputes are reviewed by a person. Otherwise a complaint could be reopened forever without checking.

23. **How are students and faculty different?**
    Both are reporters with the same permissions. The role is stored so reports can tell them apart.

24. **How did you test the project?**
    We wrote 108 automated Django tests and a manual checklist. `python manage.py test` creates a temporary database, runs all tests and deletes it.

25. **What are the limitations?**
    Basic keyword safety detection, no notifications, only category-based assignment, free-text locations, and SQLite is only for small use.

26. **How would you deploy it for real?**
    Set `DEBUG=False`, use a strong secret key from an environment variable, move to PostgreSQL, run with Gunicorn behind Nginx, serve static files properly and use HTTPS.

27. **Why is there no JavaScript?**
    It was a project requirement, and HTML forms with server-side Django views are enough for this workflow. Filters use GET forms and actions use POST forms.

28. **What is `select_related` used for?**
    It loads related objects (like reporter and assigned staff) in the same query, so we don't run one extra query per table row.

---

## 14. Demonstration script (about 8 minutes)

**Before the viva:** run `python manage.py seed_demo --reset`, start the server,
and open two browser windows (one normal, one private).

1. **Introduction (1 min)**: problem statement, two logins (Student / Faculty and
   Administrator), workers as assignable names, tech stack. Show the login page
   with the "Login as" drop-down.
2. **Student (2 min)**: "Login as: Student / Faculty", `student_demo`.
   - Show the dashboard cards and table.
   - Submit "Sparks from socket near window", category Electrical, Hostel B / 3 / Room 315, urgency Medium.
   - Point out: ID created, priority raised to **Urgent**, safety warning, status Submitted (waiting for the admin), deadline 4 hours.
3. **Admin assigns and records progress (2.5 min)**: private window, "Login as: Administrator", `admin_demo`.
   - Dashboard: three boxes (Open, In Progress, Closed). The Sparks complaint is at the top of
     *Open* (newest first). Pick **Ramesh Kumar (Electrical)** in its drop-down and click *Assign*: it moves to In Progress.
   - Click *Close* on it, write a note and save: it moves to Closed.
   - Show that an Open complaint (e.g. *Notice board fallen*) can also be closed directly with a note.
   - Show the history timeline.
4. **Student again (30 s)**: open the resolved complaint, request reopening with a reason.
5. **Admin supervision (1.5 min)**:
   - The complaint shows *Reopen requested*: approve it (back to In Progress).
   - Also show that a student account with "Login as: Administrator" is refused.
6. **Dashboard boxes and analytics (1 min)**: click the *Closed* box (only closed complaints appear), then open Analytics and walk through the four charts.
   Export CSV. Upload the sample CSV and show the cleaning warnings and charts.
7. **Close (30 s)**: run `python manage.py test` (or show a screenshot of it passing),
   state the limitations and future work.
