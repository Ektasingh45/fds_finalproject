from django.contrib.auth.models import User
from django.db import models


class Profile(models.Model):
    """
    Extra information for each user. Django's built-in User model stores the
    username, password hash, name and email. This profile adds the role.
    """

    class Role(models.TextChoices):
        STUDENT = "student", "Student"
        FACULTY = "faculty", "Faculty"
        STAFF = "staff", "Maintenance Staff"
        ADMIN = "admin", "Administrator"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.STUDENT)
    # Department for students/faculty, or team name for staff (e.g. "Electrical")
    department = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=15, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"
