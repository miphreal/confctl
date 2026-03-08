"""Tests for the async channel (IPC communication)."""

import asyncio

from confctl.wire.channel import create_channel


class TestAsyncChannel:
    def test_send_recv_roundtrip(self):
        async def _test():
            async_end, sync_end = create_channel()
            sync_end.send({"type": "test", "value": 42})

            events = []
            async for ev in async_end.recv():
                events.append(ev)
                # Only expect one event
                break

            assert events == [{"type": "test", "value": 42}]

        asyncio.run(_test())

    def test_multiple_messages(self):
        async def _test():
            async_end, sync_end = create_channel()
            sync_end.send("msg1")
            sync_end.send("msg2")
            sync_end.send("msg3")

            events = []
            async for ev in async_end.recv():
                events.append(ev)
                if len(events) == 3:
                    break

            assert events == ["msg1", "msg2", "msg3"]

        asyncio.run(_test())

    def test_handles_closed_connection(self):
        async def _test():
            async_end, sync_end = create_channel()
            sync_end.send("last")
            sync_end.close()

            events = []
            async for ev in async_end.recv():
                events.append(ev)

            assert events == ["last"]

        asyncio.run(_test())
