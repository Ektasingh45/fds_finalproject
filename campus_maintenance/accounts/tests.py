from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Profile
from .permissions import get_role

TEST_PASSWORD = "TestPass#12345"


class RegistrationTests(TestCase):
    def registration_data(self, **changes):
        data = {
            "username": "newstudent",
            "first_name": "New",
            "last_name": "Student",
            "email": "new@example.com",
            "role": "student",
            "department": "CSE",
            "password1": TEST_PASSWORD,
            "password2": TEST_PASSWORD,
        }
        data.update(changes)
        return data

    def test_student_can_register(self):
        response = self.client.post(reverse("register"), self.registration_data())
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        user = User.objects.get(username="newstudent")
        self.assertEqual(user.profile.role, Profile.Role.STUDENT)
        self.assertNotEqual(user.password, TEST_PASSWORD)  # stored as a hash
        self.assertTrue(user.check_password(TEST_PASSWORD))

    def test_cannot_register_as_staff_or_admin(self):
        for role in ["staff", "admin"]:
            response = self.client.post(reverse("register"), self.registration_data(role=role, username=f"x{role}"))
            self.assertEqual(response.status_code, 200)
            self.assertFalse(User.objects.filter(username=f"x{role}").exists())

    def test_duplicate_email_rejected(self):
        self.client.post(reverse("register"), self.registration_data())
        self.client.logout()
        response = self.client.post(reverse("register"), self.registration_data(username="another"))
        self.assertContains(response, "already exists")

    def test_superuser_is_treated_as_admin(self):
        superuser = User.objects.create_superuser("boss", "boss@example.com", TEST_PASSWORD)
        self.assertEqual(get_role(superuser), Profile.Role.ADMIN)


class LoginAsTests(TestCase):
    """The "Login as" drop-down must match the account's real role."""

    def setUp(self):
        for username, role in [("student1", "student"), ("faculty1", "faculty"), ("admin1", "admin"), ("worker1", "staff")]:
            user = User.objects.create_user(username, password=TEST_PASSWORD)
            Profile.objects.create(user=user, role=role)

    def login(self, username, login_as):
        return self.client.post(
            reverse("login"), {"login_as": login_as, "username": username, "password": TEST_PASSWORD}, follow=True
        )

    def test_student_logs_in_as_student(self):
        response = self.login("student1", "reporter")
        self.assertEqual(response.redirect_chain[-1][0], reverse("reporter_dashboard"))

    def test_faculty_logs_in_as_student_faculty(self):
        response = self.login("faculty1", "reporter")
        self.assertEqual(response.redirect_chain[-1][0], reverse("reporter_dashboard"))

    def test_admin_logs_in_as_admin(self):
        response = self.login("admin1", "admin")
        self.assertEqual(response.redirect_chain[-1][0], reverse("admin_dashboard"))

    def test_student_cannot_log_in_as_admin(self):
        response = self.login("student1", "admin")
        self.assertContains(response, "not an administrator account")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_admin_must_choose_administrator(self):
        response = self.login("admin1", "reporter")
        self.assertContains(response, "Choose &#x27;Administrator&#x27;")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_worker_cannot_log_in(self):
        for login_as in ["reporter", "admin"]:
            response = self.login("worker1", login_as)
            self.assertContains(response, "cannot log in")
            self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_as_dropdown_has_no_worker_option(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Student / Faculty")
        self.assertContains(response, "Administrator")
        self.assertNotContains(response, "Maintenance Staff")

    def test_wrong_password_still_rejected(self):
        response = self.client.post(reverse("login"), {"login_as": "reporter", "username": "student1", "password": "wrong"})
        self.assertContains(response, "correct username and password")

    def test_login_page_has_no_demo_accounts_table(self):
        for debug in [True, False]:
            with self.settings(DEBUG=debug):
                response = self.client.get(reverse("login"))
                self.assertNotContains(response, "Demo accounts")
                self.assertNotContains(response, "DemoPass")
