"""Minimal CONNECT proxy that permits only Cloudflare Workers AI's HTTPS host."""

import select
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_AUTHORITY = "api.cloudflare.com:443"
LISTEN_ADDRESS = ("0.0.0.0", 3128)
RELAY_BUFFER_BYTES = 64 * 1024
IDLE_TIMEOUT_SECONDS = 60


def is_allowed_authority(authority: str) -> bool:
    """Accept one exact TLS destination; do not permit arbitrary proxy targets."""
    return authority == ALLOWED_AUTHORITY


class CloudflareConnectHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_CONNECT(self) -> None:
        if not is_allowed_authority(self.path):
            self.send_error(403, "only api.cloudflare.com:443 is allowed")
            return

        try:
            upstream = socket.create_connection(("api.cloudflare.com", 443), timeout=15)
        except OSError:
            self.send_error(502, "Cloudflare connection failed")
            return

        self.send_response(200, "Connection Established")
        self.end_headers()
        self.close_connection = True
        self.connection.settimeout(None)
        upstream.settimeout(None)
        sockets = (self.connection, upstream)
        destinations = {self.connection: upstream, upstream: self.connection}

        try:
            while True:
                readable, _, exceptional = select.select(
                    sockets, (), sockets, IDLE_TIMEOUT_SECONDS
                )
                if exceptional or not readable:
                    return
                for source in readable:
                    payload = source.recv(RELAY_BUFFER_BYTES)
                    if not payload:
                        return
                    destinations[source].sendall(payload)
        except OSError:
            return
        finally:
            upstream.close()

    def log_message(self, _format: str, *_args: object) -> None:
        # Request paths are not secrets, but omit proxy traffic from the build log.
        return


def main() -> None:
    server = ThreadingHTTPServer(LISTEN_ADDRESS, CloudflareConnectHandler)
    server.daemon_threads = True
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
