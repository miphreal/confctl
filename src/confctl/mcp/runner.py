from __future__ import annotations

from pathlib import Path

from confctl.wire import events
from confctl.wire.channel import create_channel
from confctl.deps.worker import run_worker


async def run_specs_headless(specs: list[str], configs_root: Path) -> dict:
    """Run specs in a worker process and collect events into a structured result."""
    ui_channel_end, worker_channel_end = create_channel()
    stop_worker = run_worker(
        specs=specs, configs_root=configs_root, events_channel=worker_channel_end
    )

    ops: dict[tuple[str, ...], dict] = {}
    ordered_paths: list[tuple[str, ...]] = []
    errors: list[dict] = []
    debug_log: list[str] = []

    try:
        async for event in ui_channel_end.recv():
            match event:
                case events.EvOpStart() as ev:
                    ops[ev.op_path] = {
                        "op": ev.op,
                        "op_path": list(ev.op_path),
                        "data": ev.data,
                        "logs": [],
                        "status": "in_progress",
                    }
                    ordered_paths.append(ev.op_path)
                case events.EvOpLog(op_path=op_path, log=log):
                    if op_path in ops:
                        ops[op_path]["logs"].append(log)
                case events.EvOpProgress(op_path=op_path, data=data):
                    if op_path in ops:
                        ops[op_path].setdefault("progress", []).append(data)
                case events.EvOpError(op_path=op_path, error=error, tb=tb):
                    if op_path in ops:
                        ops[op_path]["status"] = "failed"
                        ops[op_path]["error"] = error
                        ops[op_path]["traceback"] = tb
                    errors.append(
                        {"op_path": list(op_path), "error": error, "traceback": tb}
                    )
                case events.EvOpStop(op_path=op_path, reason=reason):
                    if op_path in ops:
                        ops[op_path]["status"] = "stopped"
                        ops[op_path]["stop_reason"] = reason
                case events.EvOpFinish(op_path=op_path, op=op_name):
                    if op_path in ops and ops[op_path]["status"] == "in_progress":
                        ops[op_path]["status"] = "succeeded"
                    if op_name == "build/specs":
                        break
                case events.EvDebug(log=log):
                    debug_log.append(log)
    finally:
        stop_worker()

    return {
        "specs": specs,
        "configs_root": str(configs_root),
        "ops": [ops[p] for p in ordered_paths],
        "errors": errors,
        "debug": debug_log,
        "succeeded": not errors,
    }


def list_available_specs(configs_root: Path) -> list[dict]:
    """Walk configs_root, find every `.confbuild.py` and `<name>.py` config,
    return a list of `{spec, path}` entries suitable for `confctl <spec>`.
    """
    configs_root = configs_root.resolve()
    if not configs_root.is_dir():
        return []

    results: list[dict] = []
    seen: set[str] = set()

    for path in sorted(configs_root.rglob(".confbuild.py")):
        rel_dir = path.parent.relative_to(configs_root)
        spec = "" if str(rel_dir) == "." else str(rel_dir)
        if spec in seen:
            continue
        seen.add(spec)
        results.append(
            {
                "spec": spec or "(root)",
                "path": str(path),
            }
        )
    return results
