"""Tests for the event/ops tracking system."""

from multiprocessing import Pipe

from confctl.wire.events import (
    OpsTracking,
    EvOpStart,
    EvOpLog,
    EvOpProgress,
    EvOpError,
    EvOpFinish,
    ForceStop,
)


def make_ops():
    reader, writer = Pipe(duplex=False)
    return OpsTracking(writer), reader


class TestOpsTracking:
    def test_op_emits_start_and_finish(self):
        ops, reader = make_ops()
        with ops.op("test/op", key="val"):
            pass

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        types = [ev.typ for ev in events]
        assert types == ["op/start", "op/finish"]
        assert events[0].data == {"key": "val"}

    def test_op_emits_log(self):
        ops, reader = make_ops()
        with ops.op("test/op") as op:
            op.log("hello")

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        log_events = [ev for ev in events if ev.typ == "op/log"]
        assert len(log_events) == 1
        assert log_events[0].log == "hello"

    def test_op_emits_progress(self):
        ops, reader = make_ops()
        with ops.op("test/op") as op:
            op.progress(status="running", pct=50)

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        progress = [ev for ev in events if ev.typ == "op/progress"]
        assert len(progress) == 1
        assert progress[0].data == {"status": "running", "pct": 50}

    def test_op_captures_exception(self):
        ops, reader = make_ops()
        with ops.op("test/op") as op:
            raise ValueError("boom")

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        errors = [ev for ev in events if ev.typ == "op/error"]
        assert len(errors) == 1
        assert "boom" in errors[0].error
        assert op.error is not None

    def test_op_handles_force_stop(self):
        ops, reader = make_ops()
        with ops.op("test/op"):
            ops.force_stop("cancelled", {"info": 1})

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        stops = [ev for ev in events if ev.typ == "op/stop"]
        assert len(stops) == 1
        assert stops[0].reason == "cancelled"
        assert stops[0].data == {"info": 1}

    def test_nested_ops_have_correct_paths(self):
        ops, reader = make_ops()
        with ops.op("outer"):
            with ops.op("inner"):
                pass

        events = []
        while reader.poll(0.1):
            events.append(reader.recv())

        starts = [ev for ev in events if ev.typ == "op/start"]
        assert len(starts) == 2
        # outer has 1-element path, inner has 2-element path
        assert len(starts[0].op_path) == 1
        assert len(starts[1].op_path) == 2
        # inner path starts with outer's path
        assert starts[1].op_path[0] == starts[0].op_path[0]

    def test_seq_id_is_per_instance(self):
        ops1, _ = make_ops()
        ops2, _ = make_ops()
        id1 = ops1.get_op_id("a")
        id2 = ops2.get_op_id("a")
        # Both start from 0, confirming instance-level isolation
        assert id1 == id2
