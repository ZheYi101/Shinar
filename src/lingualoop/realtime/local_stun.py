"""Small IPv4 Binding responder for the owned, local RTC test stack.

The media mux is not a STUN discovery server. A real Binding response avoids
both that false assumption and the SFU's default public discovery servers.
"""

import socket
import struct
import threading

COOKIE = 0x2112A442


def binding_response(packet: bytes, peer: tuple[str, int]) -> bytes | None:
    if len(packet) < 20 or len(packet) > 512:
        return None
    kind, length, cookie = struct.unpack("!HHI", packet[:8])
    if kind != 1 or cookie != COOKIE or length % 4 or len(packet) != length + 20:
        return None
    address = struct.unpack("!I", socket.inet_aton(peer[0]))[0] ^ COOKIE
    value = struct.pack("!BBHI", 0, 1, peer[1] ^ (COOKIE >> 16), address)
    return (
        struct.pack("!HHI", 0x101, 12, COOKIE) + packet[8:20] + struct.pack("!HH", 0x20, 8) + value
    )


class LocalStunServer:
    """An explicitly bound, short-lived fixture; no relay or public listener."""

    def __init__(self, address: str, port: int) -> None:
        from .local_server import validate_rtc_address

        self.address = validate_rtc_address(address)
        self.port = port
        self.requests = 0
        self._closed = threading.Event()

    def __enter__(self) -> "LocalStunServer":
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind((self.address, self.port))
            self.port = self.socket.getsockname()[1]
            self.socket.settimeout(0.1)
        except BaseException:
            self.socket.close()
            raise
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        return self

    def _serve(self) -> None:
        while not self._closed.is_set():
            try:
                packet, peer = self.socket.recvfrom(513)
                response = binding_response(packet, peer)
                if response:
                    self.socket.sendto(response, peer)
                    self.requests += 1
            except TimeoutError:
                continue
            except OSError:
                if self._closed.is_set():
                    return

    def __exit__(self, *_: object) -> None:
        self._closed.set()
        self.socket.close()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            raise RuntimeError("local_stun_cleanup_failed")
