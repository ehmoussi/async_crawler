import logging
import selectors
import socket
import ssl
from selectors import EVENT_READ, EVENT_WRITE, DefaultSelector
from typing import Any, Callable, Generator

logging.basicConfig(level=logging.DEBUG)


class Future:
    def __init__(self) -> None:
        self.result: Any = None
        self._callbacks: list[Callable[[Future], Any]] = []

    def add_done_callback(self, callback: Callable[["Future"], Any]) -> None:
        self._callbacks.append(callback)

    def set_result(self, result: Any) -> None:
        self.result = result
        for callback in self._callbacks:
            callback(self)


class Task:
    def __init__(self, coro) -> None:
        self.coro: Generator[Future, Any, Any] = coro
        f = Future()
        f.set_result(None)
        self.step(f)

    def step(self, future: Future) -> None:
        try:
            next_future = self.coro.send(future.result)
        except StopIteration:
            return
        else:
            next_future.add_done_callback(self.step)


class Fetcher:
    def __init__(self) -> None:
        self.selector = DefaultSelector()
        self.hostname = "xkcd.com"
        self.port = 443
        self.context = ssl.create_default_context()
        self.ssl_sock: ssl.SSLSocket | None = None
        self.response: bytes = b""
        self.request: str = ""
        self.future: Future | None = None

    def fetch(self, url: str) -> Generator[Future, bytes | bool | None, None]:
        self.request = f"GET {url} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n"
        self.response = b""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setblocking(False)
            logging.debug("Start connection")
            self.future = Future()
            sock.connect_ex((self.hostname, self.port))
            with self.context.wrap_socket(
                sock, server_hostname=self.hostname, do_handshake_on_connect=False
            ) as self.ssl_sock:
                self.selector.register(self.ssl_sock.fileno(), EVENT_WRITE, self.on_connected)
                yield self.future
                self.selector.unregister(self.ssl_sock.fileno())
                yield from self.do_handshake()
                logging.debug("Send request")
                self.ssl_sock.send(self.request.encode("ascii"))
                yield from self.read_all()

    def read_all(self) -> Generator[Future, bytes | None, None]:
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        logging.debug("Start reading")
        while True:
            chunk = yield from self.read_chunck()
            if chunk is None:
                continue
            elif len(chunk) > 0:
                self.response += chunk
            else:
                break
        logging.debug("Finished reading")

    def read_chunck(self) -> Generator[Future, bytes | None, bytes | None]:
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        self.future = Future()
        self.selector.register(self.ssl_sock.fileno(), EVENT_READ, self.on_read)
        chunk = yield self.future
        assert not isinstance(chunk, bool), "The future has an unexpected result"
        self.selector.unregister(self.ssl_sock.fileno())
        return chunk

    def do_handshake(self) -> Generator[Future, bool, None]:
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        logging.debug("Start Handshake")
        while True:
            self.future = Future()
            self.selector.register(self.ssl_sock.fileno(), EVENT_WRITE, self.on_handshake)
            is_done = yield self.future
            assert isinstance(is_done, bool), "The future has an unexpected result"
            self.selector.unregister(self.ssl_sock.fileno())
            if is_done is not None and is_done:
                break
        logging.debug("Handshake done")

    # ------------------ Callbacks ---------------------------------------

    def on_read(self):
        try:
            chunk = self.ssl_sock.recv(4096)
        except ssl.SSLWantReadError:
            self.future.set_result(None)
            logging.debug("Receiving chunk in progress ...")
        else:
            logging.debug("Read a chunk of 4096 bytes")
            self.future.set_result(chunk)

    def on_handshake(self):
        try:
            self.ssl_sock.do_handshake(block=False)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            logging.debug("Handshake in progress ...")
            self.future.set_result(False)
        else:
            self.future.set_result(True)

    def on_connected(self):
        logging.debug("Connected")
        self.future.set_result(None)

    # ------------------ Deprecated ---------------------------------------

    def read(self, key: selectors.SelectorKey, mask: int) -> None:
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        self.selector.unregister(key.fd)
        try:
            chunk = self.ssl_sock.recv(4096)
        except (ssl.SSLWantReadError, OSError):
            logging.debug("Chunk not complete")
            self.selector.register(key.fd, EVENT_READ, self._read)
        else:
            if len(chunk) > 0:
                logging.debug("Read a chunk of 4096 bytes")
                self.response += chunk
                self.selector.register(key.fd, EVENT_READ, self._read)
            else:
                logging.debug("Finished reading")

    def handshake_finished(self, key: selectors.SelectorKey, mask: int) -> None:
        self.selector.unregister(key.fd)
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        logging.debug("Handshake Finished")
        logging.debug("Send request")
        request_encoded = self.request.encode("ascii")
        self.ssl_sock.send(request_encoded)
        logging.debug("Start reading")
        self.selector.register(key.fd, EVENT_WRITE, self._read)

    def start_handshake(self, key: selectors.SelectorKey, mask: int) -> None:
        logging.debug("Start Handshake")
        self.selector.unregister(key.fd)
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        try:
            self.ssl_sock.do_handshake(block=False)
        except (ssl.SSLWantReadError, ssl.SSLWantWriteError):
            self.selector.register(key.fd, EVENT_WRITE, self.start_handshake)
        else:
            self.selector.register(key.fd, EVENT_WRITE, self.handshake_finished)

    def connected(self, key: selectors.SelectorKey, mask: int) -> None:
        logging.debug("Connected")
        self.selector.unregister(key.fd)
        self.selector.register(key.fd, EVENT_WRITE, self.start_handshake)

    def loop(self) -> None:
        while True:
            try:
                events = self.selector.select()
            except OSError:
                break
            else:
                for event_key, event_mask in events:
                    callback = event_key.data
                    callback()  # event_key, event_mask)


def main() -> None:
    fetcher = Fetcher()
    Task(fetcher.fetch("/353/"))
    fetcher.loop()
    print(fetcher.response.decode())


if __name__ == "__main__":
    main()
