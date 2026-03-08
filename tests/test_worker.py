"""Integration test — runs the full worker process pipeline."""

import shutil
import tempfile
from multiprocessing import Pipe
from pathlib import Path

from confctl.deps.worker import build_specs
from confctl.wire.events import EvOpStart, EvOpFinish, EvOpError

from conftest import CONFIGS_ROOT


def drain_events(reader):
    """Read all events from a pipe, handling EOF gracefully."""
    events = []
    while reader.poll(0.1):
        try:
            events.append(reader.recv())
        except EOFError:
            break
    return events


class TestBuildSpecs:
    def test_resolves_greeter_spec(self, tmp_output):
        """Run the worker's build_specs in-process (not as subprocess)."""
        reader, writer = Pipe(duplex=False)

        build_specs(
            specs=["conf::tools/greeter"],
            configs_root=CONFIGS_ROOT,
            events_channel=writer,
        )
        writer.close()

        events = drain_events(reader)
        types = [ev.typ for ev in events]

        # Must have start/finish for the root build/specs
        assert "op/start" in types
        assert "op/finish" in types

        # Should have build/dep starts for the greeter
        build_starts = [
            ev for ev in events
            if isinstance(ev, EvOpStart) and ev.op == "build/dep"
        ]
        assert len(build_starts) >= 1

        # No errors
        errors = [ev for ev in events if isinstance(ev, EvOpError)]
        assert len(errors) == 0

    def test_resolves_chain_spec(self, tmp_output):
        """Chain spec depends on greeter — both should resolve."""
        reader, writer = Pipe(duplex=False)

        build_specs(
            specs=["conf::tools/chain"],
            configs_root=CONFIGS_ROOT,
            events_channel=writer,
        )
        writer.close()

        events = drain_events(reader)

        build_starts = [
            ev for ev in events
            if isinstance(ev, EvOpStart) and ev.op == "build/dep"
        ]
        # At least chain + greeter
        assert len(build_starts) >= 2

        errors = [ev for ev in events if isinstance(ev, EvOpError)]
        assert len(errors) == 0

    def test_renders_file(self, tmp_output):
        """File renderer should produce output file."""
        reader, writer = Pipe(duplex=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy fixtures so we can inject output_root into root config
            configs = Path(tmpdir) / "configs"
            shutil.copytree(CONFIGS_ROOT, configs)

            with open(configs / ".confbuild.py", "a") as f:
                f.write(f'\noutput_root = "{tmp_output}"\n')

            build_specs(
                specs=["conf::tools/file_renderer"],
                configs_root=configs,
                events_channel=writer,
            )
            writer.close()

        events = drain_events(reader)

        errors = [ev for ev in events if isinstance(ev, EvOpError)]
        assert len(errors) == 0

        output_file = tmp_output / "file_renderer" / "output.conf"
        assert output_file.exists()
        content = output_file.read_text()
        assert "setting_a = value_a" in content

    def test_default_spec_is_main(self, tmp_output):
        """Empty specs list should resolve conf:::main."""
        reader, writer = Pipe(duplex=False)

        build_specs(
            specs=[],
            configs_root=CONFIGS_ROOT,
            events_channel=writer,
        )
        writer.close()

        events = drain_events(reader)

        # Should start and finish without error (root .confbuild.py has no main())
        finishes = [
            ev for ev in events
            if isinstance(ev, EvOpFinish) and ev.op == "build/specs"
        ]
        assert len(finishes) == 1
