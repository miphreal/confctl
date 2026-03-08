from __future__ import annotations

from rich.console import ConsoleRenderable

from confctl.ui._base import OpBase, _ops_ui_registry
from confctl.wire import events
from confctl.wire.channel import AsyncChannel


class OpsView(ConsoleRenderable):
    root_op: OpBase | None = None

    def __init__(self) -> None:
        self.ops_map: dict[tuple[str, ...], OpBase] = {}

    def get_parent_node(self, op_path: tuple[str, ...]):
        for i in range(len(op_path), 0, -1):
            node = self.ops_map.get(tuple(op_path[:i]))
            if node is not None:
                return node
        return None

    def build_op(self, op_name: str, op_data):
        if cls := _ops_ui_registry.get(op_name):
            return cls(op_name=op_name, data=op_data)
        return OpBase(op_name=op_name, data=op_data)

    async def listen_to_channel(self, channel: AsyncChannel):
        from confctl.ui._ops import OpBuildConfigs, OpBuildDep

        async for event in channel.recv():
            match event:
                case events.EvOpStart() as ev:
                    op = self.build_op(op_name=ev.op, op_data=ev.data)

                    if self.root_op is None and isinstance(op, OpBuildConfigs):
                        self.root_op = op

                    parent = self.get_parent_node(ev.op_path)
                    if self.root_op and isinstance(op, OpBuildDep):
                        self.root_op.ops.append(op)
                    elif parent:
                        parent.ops.append(op)

                    self.ops_map[ev.op_path] = op

                    op.handle_start(ev.ts)

                case events.EvOpLog(op_path=op_path, log=log):
                    op = self.ops_map[op_path]
                    op.handle_log(log)
                case events.EvOpProgress(op_path=op_path, data=data):
                    op = self.ops_map[op_path]
                    op.handle_progress(**data)
                case events.EvOpError(op_path=op_path, error=error, tb=tb):
                    op = self.ops_map[op_path]
                    op.handle_error(error, tb)
                case events.EvOpStop(op_path=op_path, reason=reason, data=data):
                    op = self.ops_map[op_path]
                    op.handle_stop(reason, data)
                case events.EvOpFinish(op_path=op_path, op=op_name, ts=ts):
                    op = self.ops_map[op_path]
                    op.handle_finish(ts)
                    if op_name == "build/specs":
                        return
                case events.EvDebug(op_path=op_path, log=log):
                    op = self.root_op if self.root_op else self.ops_map[op_path]
                    op.handle_log(f"DEBUG: {log}\n")

    def __rich_console__(self, *args):
        yield self.root_op if self.root_op else "Loading..."
