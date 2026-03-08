"""Tests for the resolver registry."""

import pytest
from multiprocessing import Pipe

from confctl.deps.ctx import Ctx
from confctl.deps.registry import Registry
from confctl.deps.runtime import RuntimeServices, active_services, active_ctx
from confctl.wire.events import OpsTracking


class StubResolver:
    def __init__(self, name, result=None):
        self.name = name
        self.result = result
        self.resolved_specs = []

    def can_resolve(self, raw_spec, ctx):
        return raw_spec.startswith(f"{self.name}::")

    def resolve(self, raw_spec, ctx):
        self.resolved_specs.append(raw_spec)
        return self.result


class TestRegistry:
    def test_resolve_finds_matching_resolver(self):
        ctx = Ctx()
        reg = Registry(global_ctx=ctx)

        resolver = StubResolver("test", result="ok")
        reg.register_resolver(resolver)

        result = reg.resolve("test::something")
        assert result == "ok"
        assert resolver.resolved_specs == ["test::something"]

    def test_resolve_raises_for_unknown_spec(self):
        ctx = Ctx()
        reg = Registry(global_ctx=ctx)
        reg.register_resolver(StubResolver("test"))

        with pytest.raises(RuntimeError, match="Cannot find a handler"):
            reg.resolve("unknown::spec")

    def test_resolvers_checked_in_order(self):
        ctx = Ctx()
        reg = Registry(global_ctx=ctx)

        first = StubResolver("x", result="first")
        second = StubResolver("x", result="second")
        reg.register_resolver(first)
        reg.register_resolver(second)

        result = reg.resolve("x::foo")
        assert result == "first"
        assert len(second.resolved_specs) == 0

    def test_setup_resolvers_from_dotted_path(self, tmp_path):
        """Path resolver requires RuntimeServices to be set up."""
        _, writer = Pipe(duplex=False)
        ops = OpsTracking(writer)
        ctx = Ctx()
        ctx["global_ctx"] = ctx
        reg = Registry(global_ctx=ctx)

        services = RuntimeServices(ops=ops, registry=reg, configs_root=tmp_path)
        active_services.set(services)
        active_ctx.set(ctx)

        reg.setup_resolvers(["confctl.deps.resolvers.path.path"])
        result = reg.resolve("path::/tmp/test_registry_probe")
        assert str(result) == "/tmp/test_registry_probe"
