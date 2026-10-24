from django.contrib import admin

from .models import Complaint, ComplaintStatusHistory, PriorityDeadline, ReopenRequest


class HistoryInline(admin.TabularInline):
    model = ComplaintStatusHistory
    extra = 0
    readonly_fields = ["old_status", "new_status", "changed_by", "note", "created_at"]
    can_delete = False


@admin.register(Complaint)
class ComplaintAdmin(admin.ModelAdmin):
    list_display = ["reference_id", "title", "category", "priority", "status", "assigned_to", "submitted_at"]
    list_filter = ["status", "priority", "category"]
    search_fields = ["reference_id", "title", "building"]
    readonly_fields = ["reference_id"]
    inlines = [HistoryInline]


admin.site.register(PriorityDeadline)
admin.site.register(ReopenRequest)
