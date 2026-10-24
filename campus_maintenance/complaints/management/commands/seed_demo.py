"""
Create demonstration accounts, maintenance workers and sample complaints.
There is no automatic assignment: in the sample history the administrator
assigned every worker by hand.

Usage (PowerShell):
    python manage.py seed_demo
    python manage.py seed_demo --reset          # delete complaints and recreate them
    python manage.py seed_demo --password "MyDemoPass#2026"

All accounts created here are TEST accounts for a classroom demonstration.
Never use these passwords for real accounts.
"""
import random
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.demo_accounts import DEMO_PASSWORD
from accounts.models import Profile
from complaints.models import (
    Category,
    Complaint,
    ComplaintStatusHistory,
    Priority,
    PriorityDeadline,
    ReopenRequest,
    Status,
)
from complaints.services import DEFAULT_TARGET_HOURS, calculate_priority

# Accounts that can log in: username, first name, last name, role, department
DEMO_USERS = [
    ("admin_demo", "Asha", "Menon", Profile.Role.ADMIN, "Estate Office"),
    ("student_demo", "Rohan", "Sharma", Profile.Role.STUDENT, "CSE"),
    ("student_two", "Meera", "Iyer", Profile.Role.STUDENT, "ECE"),
    ("student_three", "Arjun", "Nair", Profile.Role.STUDENT, "Mechanical"),
    ("faculty_demo", "Kavita", "Rao", Profile.Role.FACULTY, "Mechanical"),
    ("faculty_two", "Sanjay", "Gupta", Profile.Role.FACULTY, "CSE"),
]

# Maintenance workers: they appear in the "Assign to" drop-down but cannot log in.
DEMO_WORKERS = [
    ("staff_electric", "Ramesh", "Kumar", "Electrical", "98450 11111"),
    ("staff_electric2", "Anil", "Verma", "Electrical", "98450 11112"),
    ("staff_plumber", "Suresh", "Patil", "Plumbing", "98450 22222"),
    ("staff_carpenter", "Mahesh", "Yadav", "Carpentry", "98450 33333"),
    ("staff_housekeeping", "Lata", "Devi", "Housekeeping", "98450 44444"),
    ("staff_it", "Imran", "Shaikh", "IT Support", "98450 55555"),
    ("staff_civil", "Gopal", "Singh", "Civil / Masonry", "98450 66666"),
]

# Which worker the administrator chose for each category in the sample history.
ADMIN_CHOICE = {
    Category.ELECTRICAL: "staff_electric",
    Category.PLUMBING: "staff_plumber",
    Category.WATER_SUPPLY: "staff_plumber",
    Category.FURNITURE: "staff_carpenter",
    Category.CLEANING: "staff_housekeeping",
    Category.NETWORK: "staff_it",
    Category.EQUIPMENT: "staff_it",
    Category.CIVIL: "staff_civil",
    Category.OTHER: "staff_housekeeping",
}

# title, description, category, building, floor, room, urgency, days ago, final status
DEMO_COMPLAINTS = [
    # --- Closed (4) ---
    ("Ceiling fan not working", "The fan in room 204 does not start even at full speed.", Category.ELECTRICAL, "Main Block", "2", "204", Priority.MEDIUM, 150, Status.CLOSED),
    ("Broken bench", "One bench in the last row is broken and wobbles when someone sits on it.", Category.FURNITURE, "Main Block", "1", "104", Priority.LOW, 120, Status.CLOSED),
    ("Wi-Fi not available in lab", "Students cannot connect to the campus Wi-Fi in Lab 3.", Category.NETWORK, "CSE Block", "3", "Lab 3", Priority.HIGH, 100, Status.CLOSED),
    ("Tap leaking again", "The same tap in the washroom started leaking again.", Category.PLUMBING, "Hostel A", "1", "Washroom 1", Priority.MEDIUM, 20, Status.RESOLVED),
    # --- In Progress (3) ---
    ("Door lock jammed", "The classroom door lock is jammed and the door does not close.", Category.CIVIL, "Admin Block", "1", "Room 110", Priority.LOW, 25, Status.IN_PROGRESS),
    ("Fan making loud noise", "The ceiling fan makes a loud grinding noise.", Category.ELECTRICAL, "Main Block", "2", "204", Priority.MEDIUM, 12, Status.IN_PROGRESS),
    ("Computers not booting", "Five computers in Lab 3 do not boot after the weekend.", Category.EQUIPMENT, "CSE Block", "3", "Lab 3", Priority.HIGH, 6, Status.ASSIGNED),
    # --- Open (2) ---
    ("Notice board fallen", "The notice board near the entrance has come off the wall.", Category.OTHER, "Library", "G", "Entrance", Priority.LOW, 5, Status.SUBMITTED),
    ("Water leakage from ceiling", "Water is dripping from the ceiling near the stairs after rain.", Category.CIVIL, "Library", "1", "Staircase", Priority.HIGH, 1, Status.SUBMITTED),
]

WORK_NOTES = {
    Category.ELECTRICAL: "Checked wiring and replaced the faulty part.",
    Category.PLUMBING: "Replaced the washer and checked for leaks.",
    Category.WATER_SUPPLY: "Cleaned the filter and checked the pump.",
    Category.FURNITURE: "Repaired and tightened the furniture.",
    Category.CLEANING: "Area cleaned and bins emptied.",
    Category.NETWORK: "Reconfigured the access point and tested the connection.",
    Category.EQUIPMENT: "Serviced the equipment and tested it with the user.",
    Category.CIVIL: "Repair work completed and area cleared.",
    Category.OTHER: "Issue attended and fixed.",
}


class Command(BaseCommand):
    help = "Create demo accounts, workers and sample complaints (test data only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=DEMO_PASSWORD, help="Password for every demo login account.")
        parser.add_argument("--reset", action="store_true", help="Delete existing complaints before seeding.")

    @transaction.atomic
    def handle(self, *args, **options):
        random.seed(42)  # same data every time
        password = options["password"]

        if options["reset"]:
            Complaint.objects.all().delete()
            self.stdout.write("Deleted existing complaints.")

        users = self.create_users(password)
        self.create_settings()
        if Complaint.objects.exists():
            self.stdout.write(self.style.WARNING(
                "Complaints already exist, so sample complaints were not added. Use --reset to recreate them."
            ))
        else:
            self.create_complaints(users)

        self.stdout.write(self.style.SUCCESS("Demo data is ready."))
        self.stdout.write(f"Login accounts (password: {password}): " + ", ".join(row[0] for row in DEMO_USERS))
        self.stdout.write("Workers (no login): " + ", ".join(f"{row[1]} {row[2]} ({row[3]})" for row in DEMO_WORKERS))

    def create_users(self, password):
        users = {}
        for username, first_name, last_name, role, department in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            user.first_name = first_name
            user.last_name = last_name
            user.email = f"{username}@example.com"
            if created:
                user.set_password(password)  # stored as a hash, never as plain text
            user.save()
            Profile.objects.update_or_create(user=user, defaults={"role": role, "department": department})
            users[username] = user

        for username, first_name, last_name, team, phone in DEMO_WORKERS:
            worker, _ = User.objects.get_or_create(username=username)
            worker.first_name = first_name
            worker.last_name = last_name
            worker.is_active = True
            worker.set_unusable_password()  # workers never log in
            worker.save()
            Profile.objects.update_or_create(
                user=worker, defaults={"role": Profile.Role.STAFF, "department": team, "phone": phone}
            )
            users[username] = worker
        return users

    def create_settings(self):
        for priority, hours in DEFAULT_TARGET_HOURS.items():
            PriorityDeadline.objects.get_or_create(priority=priority, defaults={"target_hours": hours})

    def add_history(self, complaint, old_status, new_status, user, note, when):
        ComplaintStatusHistory.objects.create(
            complaint=complaint, old_status=old_status, new_status=new_status,
            changed_by=user, note=note, created_at=when,
        )

    def create_complaints(self, users):
        now = timezone.now()
        admin = users["admin_demo"]
        reporters = [users[name] for name in ["student_demo", "student_two", "faculty_demo", "student_three", "faculty_two"]]

        for index, row in enumerate(DEMO_COMPLAINTS):
            title, description, category, building, floor, room, urgency, days_ago, final_status = row
            submitted_at = now - timedelta(days=days_ago, hours=random.randint(1, 8))
            priority, review_needed, reasons = calculate_priority(category, urgency, title, description)
            deadline = submitted_at + timedelta(hours=DEFAULT_TARGET_HOURS[priority])
            reporter = reporters[index % len(reporters)]

            complaint = Complaint.objects.create(
                reporter=reporter, title=title, description=description, category=category,
                building=building, floor=floor, room=room, reported_urgency=urgency,
                priority=priority, safety_review_needed=review_needed and final_status != Status.CLOSED,
                status=Status.SUBMITTED, submitted_at=submitted_at, deadline=deadline,
            )
            self.add_history(
                complaint, "", Status.SUBMITTED, reporter,
                "Complaint submitted. " + " ".join(reasons) + " Waiting for the administrator to assign a worker.",
                submitted_at,
            )
            if final_status == Status.SUBMITTED:
                continue  # still Open, waiting for the administrator

            # --- The administrator assigns a worker by hand ---
            worker = users[ADMIN_CHOICE[category]]
            assigned_at = submitted_at + timedelta(hours=1)
            complaint.assigned_to = worker
            complaint.status = Status.ASSIGNED
            self.add_history(complaint, Status.SUBMITTED, Status.ASSIGNED, admin,
                             f"Assigned to {worker.get_full_name()} by administrator.", assigned_at)

            # --- Progress, recorded by the administrator on behalf of the worker ---
            if final_status in (Status.IN_PROGRESS, Status.RESOLVED, Status.CLOSED):
                started = assigned_at + timedelta(hours=random.randint(1, 6))
                complaint.status = Status.IN_PROGRESS
                self.add_history(complaint, Status.ASSIGNED, Status.IN_PROGRESS, admin,
                                 f"{worker.first_name} inspected the issue and started work.", started)

            if final_status in (Status.RESOLVED, Status.CLOSED):
                # Some complaints are resolved within the deadline, some late.
                resolve_hours = DEFAULT_TARGET_HOURS[priority] * random.choice([0.4, 0.7, 1.3])
                resolved_at = min(submitted_at + timedelta(hours=resolve_hours), now)
                complaint.status = Status.RESOLVED
                complaint.resolved_at = resolved_at
                complaint.resolution_notes = WORK_NOTES[category]
                self.add_history(complaint, Status.IN_PROGRESS, Status.RESOLVED, admin,
                                 f"{worker.first_name}: {complaint.resolution_notes}", resolved_at)

            if final_status == Status.CLOSED:
                complaint.status = Status.CLOSED
                closed_at = min(complaint.resolved_at + timedelta(hours=2), now)
                self.add_history(complaint, Status.RESOLVED, Status.CLOSED, reporter,
                                 "Reporter confirmed the issue is fixed.", closed_at)

            complaint.save()

        # One resolved complaint is disputed by the reporter (pending reopen request).
        disputed = Complaint.objects.get(title="Tap leaking again")
        reason = "The tap was tightened but it is still dripping at night."
        ReopenRequest.objects.create(complaint=disputed, requested_by=disputed.reporter, reason=reason)
        self.add_history(disputed, Status.RESOLVED, Status.RESOLVED, disputed.reporter,
                         "Reporter requested reopening: " + reason, now)

        # One complaint has already been reopened twice (repeated-reopen exception).
        repeated = Complaint.objects.get(title="Fan making loud noise")
        repeated.reopen_count = 2
        repeated.status = Status.REOPENED
        repeated.deadline = now - timedelta(hours=3)  # also overdue
        repeated.save()
        self.add_history(repeated, Status.RESOLVED, Status.REOPENED, admin,
                         "Reopening approved for the second time.", now - timedelta(days=4))
