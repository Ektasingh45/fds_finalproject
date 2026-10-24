"""
Template filters that turn a detailed status (e.g. "assigned") into one of
the administrator's three tracking words: Open, In Progress, Closed.

Usage in a template:
    {% load tracking %}
    {{ entry.new_status|tracking_label }}
"""
from django import template

from complaints.models import TRACKING_LABELS, tracking_group

register = template.Library()


@register.filter
def tracking(status):
    """'assigned' -> 'in_progress' (used for the CSS class)."""
    return tracking_group(status)


@register.filter
def tracking_label(status):
    """'assigned' -> 'In Progress'."""
    return TRACKING_LABELS.get(tracking_group(status), "")
