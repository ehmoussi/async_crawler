import logging
import selectors
import socket
import ssl
from selectors import EVENT_READ, EVENT_WRITE, DefaultSelector

logging.basicConfig(level=logging.DEBUG)


class Fetcher:
    def __init__(self) -> None:
        self.selector = DefaultSelector()
        self.hostname = "xkcd.com"
        self.port = 443
        self.context = ssl.create_default_context()
        self.ssl_sock: ssl.SSLSocket | None = None
        self.response: bytes = b""
        self.request: str = ""

    def fetch(self, url: str) -> None:
        self.request = f"GET {url} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n"
        self.response = b""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setblocking(False)
            logging.debug("Start connection")
            sock.connect_ex((self.hostname, self.port))
            with self.context.wrap_socket(
                sock, server_hostname=self.hostname, do_handshake_on_connect=False
            ) as self.ssl_sock:
                self.selector.register(self.ssl_sock.fileno(), EVENT_WRITE, self.connected)
                self.loop()
                # links = parse_links(response)
                # q.add(links)
        print(self.response.decode())

    def read(self, key: selectors.SelectorKey, mask: int) -> None:
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        self.selector.unregister(key.fd)
        try:
            chunk = self.ssl_sock.recv(4096)
        except (ssl.SSLWantReadError, OSError):
            logging.debug("Chunk not complete")
            self.selector.register(key.fd, EVENT_READ, self.read)
        else:
            if len(chunk) > 0:
                logging.debug("Read a chunk of 4096 bytes")
                self.response += chunk
                self.selector.register(key.fd, EVENT_READ, self.read)
            else:
                logging.debug("Finished reading")

    def handshake_finished(self, key: selectors.SelectorKey, mask: int) -> None:
        self.selector.unregister(key.fd)
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        logging.debug("Handshake Finished")
        request_encoded = self.request.encode("ascii")
        logging.debug("Send request")
        self.ssl_sock.send(request_encoded)
        logging.debug("Start reading")
        self.selector.register(key.fd, EVENT_WRITE, self.read)

    def start_handshake(self, key: selectors.SelectorKey, mask: int) -> None:
        logging.debug("Start Handshake")
        self.selector.unregister(key.fd)
        assert self.ssl_sock is not None, "Can't call the method without a socket"
        try:
            self.ssl_sock.do_handshake(block=True)
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
                    callback(event_key, event_mask)


def main() -> None:
    Fetcher().fetch("/353/")


if __name__ == "__main__":
    main()
