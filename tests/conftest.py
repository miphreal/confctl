"""Shared test fixtures for confctl tests."""

import pytest
from multiprocessing import Pipe
from pathlib import Path

from confctl.deps.ctx import Ctx
from confctl.deps.registry import Registry
from confctl.deps.runtime import RuntimeServices, active_services, active_ctx
from confctl.deps.worker import DEFAULT_RESOLVERS
from confctl.wire.events import OpsTracking, Event


FIXTURES_DIR = Path(__file__).parent / "fixtures"
CONFIGS_ROOT = FIXTURES_DIR / "configs"


class EventCollector:
    """Collects events sent through a multiprocessing Connection."""

    def __init__(self, conn):
        self._conn = conn

    def collect_all(self) -> list[Event]:
        events = []
        while self._conn.poll(timeout=0.1):
            events.append(self._conn.recv())
        return events

    def collect_by_type(self, typ: str) -> list[Event]:
        return [ev for ev in self.collect_all() if ev.typ == typ]


@pytest.fixture
def tmp_output(tmp_path):
    """Provides a temp directory for test outputs."""
    return tmp_path


@pytest.fixture
def event_collector():
    """Creates a pipe pair and returns (OpsTracking, EventCollector)."""
    reader, writer = Pipe(duplex=False)
    ops = OpsTracking(writer)
    collector = EventCollector(reader)
    return ops, collector


@pytest.fixture
def runtime(event_collector, tmp_output):
    """Sets up a full RuntimeServices environment with contextvars.

    Returns (services, registry, global_ctx, EventCollector).
    """
    ops, collector = event_collector
    global_ctx = Ctx()
    registry = Registry(global_ctx=global_ctx)

    services = RuntimeServices(
        ops=ops, registry=registry, configs_root=CONFIGS_ROOT
    )
    active_services.set(services)
    active_ctx.set(global_ctx)

    global_ctx["global_ctx"] = global_ctx
    global_ctx["output_root"] = str(tmp_output)

    registry.setup_resolvers(DEFAULT_RESOLVERS)

    return services, registry, global_ctx, collector
