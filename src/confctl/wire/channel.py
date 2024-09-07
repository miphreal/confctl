import asyncio
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from typing import Any, AsyncGenerator, Protocol


class Channel(Protocol):
    def send(self, ev: Any, /) -> None:
        ...

    def recv(self) -> Any:
        ...


class AsyncChannel(Protocol):
    def send(self, ev: Any, /) -> None:
        ...

    async def recv(self) -> AsyncGenerator:
        ...

    def reset_sleeping_delay(self):
        ...


def create_channel() -> tuple[AsyncChannel, Channel]:
    """
    Bi-directional channel with async interface on one side and sync on the other.

    A (primary) <-> B (secondary) channel.

    Primary point provides async capabilities to listen to events and sync method to send events.
    Secondary channel provides sync capabilities to listen to events and sync method to send events.
    """
    primary_conn, secondary_conn = Pipe(duplex=True)
    return AsyncConn(primary_conn), secondary_conn


class AsyncConn:
    DEFAULT_SLEEP = 0.05
    MAX_SLEEP = 3
    GROWING_SLEEP_MULTIPLIER = 1.5

    _conn: Connection

    def __init__(self, conn: Connection) -> None:
        self._conn = conn
        self._reset_sleeping_delay = asyncio.Event()
        self._sleeping_delay = self.DEFAULT_SLEEP

    def send(self, ev, /):
        self._conn.send(ev)

    def reset_sleeping_delay(self):
        self._reset_sleeping_delay.set()

    async def recv(self):
        loop = asyncio.get_running_loop()

        while True:
            if self._conn.poll():
                ev = self._conn.recv()
                await asyncio.sleep(0.01)
                self._sleeping_delay = self.DEFAULT_SLEEP
                yield ev
            else:
                self._reset_sleeping_delay.clear()
                sleeping_reset = loop.create_task(self._reset_sleeping_delay.wait())
                wait_timeout = loop.create_task(asyncio.sleep(self._sleeping_delay))
                _, pending = await asyncio.wait(
                    [sleeping_reset, wait_timeout],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()

                if self._reset_sleeping_delay.is_set():
                    # means we explicitly triggered `_reset_sleeping_delay` event
                    self._sleeping_delay = self.DEFAULT_SLEEP
                else:
                    # means we exceeded `self._sleeping_delay`
                    self._sleeping_delay = min(
                        self._sleeping_delay * self.GROWING_SLEEP_MULTIPLIER,
                        self.MAX_SLEEP,
                    )
