"""Tests for the resolver registry."""

import pytest
from multiprocessing import Pipe

from confctl.deps.ctx import Ctx
from confctl.deps.registry import Registry, SpecNotFoundError
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

    def test_spec_not_found_is_user_facing(self):
        ctx = Ctx()
        reg = Registry(global_ctx=ctx)

        with pytest.raises(SpecNotFoundError) as exc_info:
            reg.resolve("tools/unknown")

        err = exc_info.value
        assert err.user_facing is True
        assert err.raw_spec == "tools/unknown"
        assert err.suggestions == []
        assert "Cannot find a handler for 'tools/unknown' spec." in str(err)

    def test_spec_not_found_suggests_close_matches(self):
        ctx = Ctx()
        reg = Registry(global_ctx=ctx)

        class ListingResolver(StubResolver):
            def list_specs(self):
                return ["tools/zsh", "tools/kitty", "macos/terminal"]

        reg.register_resolver(ListingResolver("test"))

        with pytest.raises(SpecNotFoundError) as exc_info:
            reg.resolve("macos/zsh")

        err = exc_info.value
        assert err.suggestions, "expected at least one suggestion"
        assert "Did you mean:" in str(err)
        assert any(s in err.suggestions for s in ["tools/zsh", "macos/terminal"])

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
