"""django-axes lockout → AuthLog hook."""

from axes.signals import user_locked_out
from django.dispatch import receiver

from .events import record_lockout


@receiver(user_locked_out)
def _on_lockout(sender, request, username, ip_address, **kwargs):
    record_lockout(identifier=username, ip=ip_address)
