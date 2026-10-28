"""ERP sync on the "post" queue (it talks to the ERP, like posting does)."""

from celery import shared_task

from .models import ErpConnection
from .sync import sync_connection


@shared_task(name="post.sync_erp")
def sync_erp(connection_id: str, full: bool = False) -> str:
    connection = ErpConnection.objects.get(pk=connection_id)
    return sync_connection(connection, full=full).id


@shared_task(name="post.sync_all_erp")
def sync_all_erp() -> int:
    """Beat task (every 15 minutes): queue one incremental sync per connected org."""
    ids = list(ErpConnection.objects.values_list("id", flat=True))
    for connection_id in ids:
        sync_erp.delay(connection_id)
    return len(ids)
