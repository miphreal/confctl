"""Tests for the context system (Ctx / ChainMap)."""

from confctl.deps.ctx import Ctx
from confctl.utils.template import LazyTemplate


class TestCtx:
    def test_basic_get_set(self):
        ctx = Ctx()
        ctx["key"] = "value"
        assert ctx.key == "value"

    def test_attribute_error_on_missing(self):
        ctx = Ctx()
        try:
            ctx.nonexistent
            assert False, "Should have raised AttributeError"
        except AttributeError:
            pass

    def test_child_inherits_parent(self):
        parent = Ctx({"a": 1, "b": 2})
        child = parent.new_child({"b": 20, "c": 30})
        assert child["a"] == 1
        assert child["b"] == 20
        assert child["c"] == 30
        # parent unchanged
        assert parent["b"] == 2

    def test_lazy_template_resolved_on_access(self):
        rendered_values = []

        def mock_render(template):
            rendered_values.append(template)
            return f"rendered:{template}"

        ctx = Ctx()
        ctx["lazy"] = LazyTemplate("hello {{ name }}", mock_render)

        # Access triggers rendering
        val = ctx.lazy
        assert val == "rendered:hello {{ name }}"
        assert len(rendered_values) == 1

        # Second access returns cached string (no re-render)
        val2 = ctx.lazy
        assert val2 == "rendered:hello {{ name }}"
        assert len(rendered_values) == 1

    def test_global_ctx_self_reference(self):
        ctx = Ctx()
        ctx["global_ctx"] = ctx
        assert ctx.global_ctx is ctx
