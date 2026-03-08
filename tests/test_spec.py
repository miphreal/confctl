"""Tests for spec parsing."""

from confctl.deps.spec import parse_spec, Spec


class TestParseSpec:
    def test_explicit_resolver(self):
        spec = parse_spec("conf::tools/kitty:main", default_resolver_name="conf")
        assert spec.resolver_name == "conf"
        assert spec.spec == "tools/kitty:main"
        assert spec.fqn == "conf::tools/kitty:main"

    def test_default_resolver(self):
        spec = parse_spec("tools/kitty", default_resolver_name="conf")
        assert spec.resolver_name == "conf"
        assert spec.spec == "tools/kitty"

    def test_empty_resolver_uses_default(self):
        spec = parse_spec("::something", default_resolver_name="fallback")
        assert spec.resolver_name == "fallback"
        assert spec.spec == "something"

    def test_brew_spec(self):
        spec = parse_spec("brew::neovim@0.9", default_resolver_name="conf")
        assert spec.resolver_name == "brew"
        assert spec.spec == "neovim@0.9"

    def test_fqn_hash(self):
        s1 = parse_spec("conf::a:b", default_resolver_name="conf")
        s2 = parse_spec("conf::a:b", default_resolver_name="conf")
        assert hash(s1) == hash(s2)

    def test_str_returns_fqn(self):
        spec = parse_spec("path::/tmp/file", default_resolver_name="path")
        assert str(spec) == "path::/tmp/file"

    def test_whitespace_stripped(self):
        spec = parse_spec("  conf :: tools/shell  ", default_resolver_name="x")
        assert spec.resolver_name == "conf"
        assert spec.spec == "tools/shell"
