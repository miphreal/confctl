"""Tests for core actions (sh, render, conf, msg, dep) using the full runtime."""

from pathlib import Path


class TestShAction:
    def test_echo_command(self, runtime):
        services, registry, ctx, collector = runtime

        result = registry.resolve("conf::tools/greeter")

        # greeter runs sh("echo '{{ greeting }} from shell'")
        # conf(shell_output=...) stores it as LazyTemplate — use attr access to unwrap
        assert result.shell_output == "Hello from shell"

    def test_sh_returns_exit_code(self, runtime):
        services, registry, ctx, collector = runtime

        from confctl.deps.spec import parse_spec
        from confctl.deps.dep import Dep

        spec = parse_spec("conf::tools/greeter", default_resolver_name="conf")
        dep_obj = Dep(spec=spec, ctx=ctx.new_child())
        sh_fn = dep_obj.get_action("run/sh")

        result = sh_fn("true")
        assert bool(result) is True
        assert result.exitcode == 0

        result = sh_fn("false")
        assert bool(result) is False
        assert result.exitcode != 0

    def test_sh_captures_output(self, runtime):
        services, registry, ctx, collector = runtime

        from confctl.deps.spec import parse_spec
        from confctl.deps.dep import Dep

        spec = parse_spec("conf::tools/greeter", default_resolver_name="conf")
        dep_obj = Dep(spec=spec, ctx=ctx.new_child())
        sh_fn = dep_obj.get_action("run/sh")

        result = sh_fn("echo hello && echo world")
        assert "hello" in result.output
        assert "world" in result.output


class TestRenderFileAction:
    def test_renders_template_to_file(self, runtime, tmp_output):
        services, registry, ctx, collector = runtime

        registry.resolve("conf::tools/file_renderer")

        output_file = tmp_output / "file_renderer" / "output.conf"
        assert output_file.exists()

        content = output_file.read_text()
        assert "# Config for test-app" in content
        assert "setting_a = value_a" in content
        assert "setting_b = 42" in content

    def test_creates_output_directory(self, runtime, tmp_output):
        services, registry, ctx, collector = runtime

        registry.resolve("conf::tools/file_renderer")

        output_dir = tmp_output / "file_renderer"
        assert output_dir.is_dir()


class TestConfAction:
    def test_sets_context_values(self, runtime):
        services, registry, ctx, collector = runtime

        result = registry.resolve("conf::tools/greeter")
        # Use attribute access to unwrap LazyTemplate
        assert result.target_name == "world"

    def test_inherits_global_context(self, runtime):
        services, registry, ctx, collector = runtime

        result = registry.resolve("conf::tools/greeter")
        # greeting is set in root .confbuild.py
        assert result.greeting == "Hello"


class TestDepChaining:
    def test_dependency_chain(self, runtime):
        services, registry, ctx, collector = runtime

        # chain depends on greeter
        registry.resolve("conf::tools/chain")
        events = collector.collect_all()

        # Both build/dep ops should have completed
        from confctl.wire.events import EvOpStart
        build_starts = [
            ev for ev in events
            if isinstance(ev, EvOpStart) and ev.op == "build/dep"
        ]
        # At least 2: chain + greeter
        assert len(build_starts) >= 2


class TestPathResolver:
    def test_path_creates_parent_dirs(self, runtime, tmp_output):
        services, registry, ctx, collector = runtime

        result = registry.resolve(f"path::{tmp_output}/nested/dir/file.txt")
        assert isinstance(result, Path)
        assert (tmp_output / "nested" / "dir").is_dir()

    def test_dir_creates_directory(self, runtime, tmp_output):
        services, registry, ctx, collector = runtime

        result = registry.resolve(f"dir::{tmp_output}/created_dir")
        assert isinstance(result, Path)
        assert result.is_dir()
