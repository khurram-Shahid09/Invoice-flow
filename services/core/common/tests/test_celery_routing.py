import pytest

from config.celery import app


@pytest.mark.parametrize("queue", ["ingest", "extract", "check", "post"])
def test_tasks_route_to_their_own_queue(queue: str) -> None:
    route = app.amqp.router.route({}, f"{queue}.some_task")
    assert route["queue"].name == queue
    assert route["queue"].exchange.name == queue
    assert route["queue"].routing_key == queue


def test_queues_do_not_share_bindings() -> None:
    keys = {(q.exchange.name, q.routing_key) for q in app.conf.task_queues}
    assert len(keys) == 4
