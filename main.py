import socket
import ssl


def fetch(url: str) -> None:
    hostname = "xkcd.com"
    port = 443
    context = ssl.create_default_context()
    request = f"GET {url} HTTP/1.0\r\nHost: xkcd.com\r\n\r\n"
    response = b""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setblocking(False)
        err = sock.connect_ex((hostname, port))
        while err != 0:
            err = sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        with context.wrap_socket(
            sock, server_hostname=hostname, do_handshake_on_connect=False
        ) as s_sock:
            while True:
                try:
                    s_sock.do_handshake(False)
                except IOError:
                    ...
                else:
                    break
            request_encoded = request.encode("ascii")
            s_sock.send(request_encoded)
            while True:
                try:
                    chunck = s_sock.recv(4096)
                except ssl.SSLWantReadError:
                    pass
                else:
                    while chunck:
                        response += chunck
                        while True:
                            try:
                                chunck = s_sock.recv(4096)
                            except ssl.SSLWantReadError:
                                ...
                            else:
                                break
                    break
            # links = parse_links(response)
            # q.add(links)
    print(response.decode())


def main() -> None:
    fetch("/353/")


if __name__ == "__main__":
    main()
