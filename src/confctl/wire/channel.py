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
    _conn: Connection

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def send(self, ev, /):
        self._conn.send(ev)

    async def recv(self):
        loop = asyncio.get_running_loop()

        while True:
            # Drain all available messages
            while self._conn.poll():
                try:
                    yield self._conn.recv()
                except EOFError:
                    return

            # Wait for the fd to become readable
            readable = asyncio.Event()
            loop.add_reader(self._conn.fileno(), readable.set)
            try:
                await readable.wait()
            finally:
                loop.remove_reader(self._conn.fileno())
