"""Strict loopback-only Windows server harness for a development probe.

No services, firewall rules, accounts, global installations or cloud resources.
The release archive stays in an ignored build directory and is checked before use.
"""

import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
import zipfile
import shutil
from collections import Counter
import re

SERVER_VERSION = "1.13.10"
ARCHIVE_NAME = f"livekit_{SERVER_VERSION}_windows_amd64.zip"
ARCHIVE_SHA256 = "fd4b7c2c3c1e4c71adaa4f6a046ad1c0abaaaf1e09fae904b35bf231ffae11d2"
RELEASE_URL = f"https://github.com/livekit/livekit/releases/download/v{SERVER_VERSION}/{ARCHIVE_NAME}"


RFC1918 = tuple(ipaddress.ip_network(net) for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def owned_rfc1918_addresses() -> set[str]:
    command = (
        "$rows=@(Get-NetIPAddress -AddressFamily IPv4 -AddressState Preferred | "
        "Where-Object { (Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue).Status -eq 'Up' } | "
        "ForEach-Object {$_.IPAddress}); ConvertTo-Json -InputObject @($rows) -Compress")
    response = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, timeout=15, creationflags=hidden_flags())
    if response.returncode:
        raise RuntimeError("local_interface_ownership_query_failed")
    values = json.loads(response.stdout or "[]")
    return {value for value in values if any(ipaddress.ip_address(value) in net for net in RFC1918)}


def validate_rtc_address(value: str, owned: set[str] | None = None) -> str:
    address = ipaddress.IPv4Address(value)
    if str(address) != value:
        raise ValueError("invalid_probe_rtc_address")
    if value == "127.0.0.1":
        return value
    if not any(address in net for net in RFC1918) or value not in (
            owned_rfc1918_addresses() if owned is None else owned):
        raise ValueError("probe_rtc_address_not_owned_rfc1918")
    return value


def validate_probe_stun_url(value: str, udp_port: int, rtc_address: str = "127.0.0.1",
                            *, owned: set[str] | None = None) -> str:
    """Only the audited server's exact IPv4 loopback endpoint is permitted.

    STUN uses RFC7064's scheme:host:port form, not an HTTP-style authority.
    Exact canonical matching excludes DNS, userinfo, queries and alternate ports.
    This is a probe boundary, not a policy imposed on the application core.
    """
    validate_rtc_address(rtc_address, owned)
    if (type(udp_port) is not int or not 1024 < udp_port < 65536
            or value != f"stun:{rtc_address}:{udp_port}"):
        raise ValueError("invalid_probe_stun_url")
    return value


def hidden_flags() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def ensure_server(cache: Path, *, download: bool = False, cancel=None,
                  progress=lambda done, total: None, on_transfer=lambda event: None) -> Path:
    from lingualoop.local_speech.downloads import TransferEvent

    archive = cache / ARCHIVE_NAME
    on_transfer(TransferEvent(ARCHIVE_NAME, "verifying"))
    valid = archive.is_file() and hashlib.sha256(archive.read_bytes()).hexdigest() == ARCHIVE_SHA256
    if not valid:
        if not download:
            raise RuntimeError("livekit_archive_missing_use_download_server")
        cache.mkdir(parents=True, exist_ok=True)
        from .continuous_assets import server_package
        from lingualoop.local_speech.downloads import ModelStore

        folder = ModelStore(cache.parent, on_transfer=on_transfer).install(
            server_package(), cancel=cancel, progress=progress
        )
        temporary = archive.with_suffix(".preparing")
        shutil.copyfile(folder / ARCHIVE_NAME, temporary)
        os.replace(temporary, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise RuntimeError("livekit_archive_checksum_mismatch")
    executable = cache / f"server-{SERVER_VERSION}" / "livekit-server.exe"
    on_transfer(TransferEvent("livekit-server.exe", "extracting"))
    # Re-extract this exact member each run; do not trust a replaced cached executable.
    with zipfile.ZipFile(archive) as bundle:
        executable.parent.mkdir(parents=True, exist_ok=True)
        executable.write_bytes(bundle.read("livekit-server.exe"))
    return executable


def server_config(http_port: int, tcp_port: int, udp_port: int, key: str, secret: str,
                  rtc_address: str = "127.0.0.1") -> dict:
    if len({http_port, tcp_port, udp_port}) != 3 or not all(
            1024 < port < 65536 for port in (http_port, tcp_port, udp_port)):
        raise ValueError("invalid_probe_ports")
    return {
        "port": http_port, "bind_addresses": ["127.0.0.1"],
        # v1.13.10's RTC TCP listener has no configurable bind IP. Disable it;
        # --bind restricts HTTP, while the IP filter restricts the UDP mux.
        "rtc": {"tcp_port": 0, "udp_port": udp_port,
                "use_external_ip": False, "node_ip": rtc_address,
                "enable_loopback_candidate": True, "stun_servers": [],
                "ips": {"includes": [f"{rtc_address}/32"]},
                "turn_servers": []},
        "turn": {"enabled": False}, "keys": {key: secret},
        "room": {"empty_timeout": 5, "departure_timeout": 2},
        "logging": {"level": "error"},
    }


def socket_snapshot(pid: int, expected: set[tuple[str, str, int]] | None = None) -> list[dict]:
    if os.name != "nt":
        raise RuntimeError("loopback_socket_audit_requires_windows")
    # PID is an integer created by this harness; credentials never enter the command.
    command = (
        f"$probePid={int(pid)}; $rows=@(); "
        "$rows+=@(Get-NetTCPConnection -OwningProcess $probePid -ErrorAction SilentlyContinue | "
        "Where-Object State -eq Listen | ForEach-Object { "
        "[PSCustomObject]@{protocol='tcp';address=$_.LocalAddress;port=$_.LocalPort}}); "
        "$rows+=@(Get-NetUDPEndpoint -OwningProcess $probePid -ErrorAction SilentlyContinue | "
        "ForEach-Object {[PSCustomObject]@{protocol='udp';address=$_.LocalAddress;port=$_.LocalPort}}); "
        "ConvertTo-Json -InputObject @($rows) -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            capture_output=True, text=True, timeout=30, creationflags=hidden_flags())
    if result.returncode:
        raise RuntimeError("loopback_socket_audit_failed")
    rows = json.loads(result.stdout or "[]")
    if expected is not None:
        if {(row["protocol"], row["address"], row["port"]) for row in rows} != expected:
            raise RuntimeError("server_socket_scope_mismatch")
        return rows
    if not all(ipaddress.ip_address(row["address"]).is_loopback for row in rows):
        raise RuntimeError("non_loopback_server_socket")
    return rows


class LocalServer:
    def __init__(self, executable: Path, cache: Path, *, http_port: int = 17880,
                 tcp_port: int = 17881, udp_port: int = 17882, diagnostic: bool = False) -> None:
        self.executable, self.cache = executable, cache
        self.http_port, self.tcp_port, self.udp_port = http_port, tcp_port, udp_port
        self.key = "local-probe"
        self.secret = secrets.token_urlsafe(40)
        self.process: subprocess.Popen | None = None
        self.pid: int | None = None
        self.bindings: list[dict] = []
        self.cleaned = False
        self.diagnostic = diagnostic
        self.safe_trace: dict = {}
        self.http_status: int | None = None
        self.rtc_address = "127.0.0.1"
        self.stun_port = http_port + 3
        self._stun = None

    @property
    def expected_bindings(self) -> set[tuple[str, str, int]]:
        return {("tcp", "127.0.0.1", self.http_port), ("udp", self.rtc_address, self.udp_port)}

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.http_port}"

    def __enter__(self) -> "LocalServer":
        if os.name != "nt":
            raise RuntimeError("local_probe_currently_windows_only")
        validate_rtc_address(self.rtc_address)
        config = server_config(self.http_port, self.tcp_port, self.udp_port, self.key, self.secret, self.rtc_address)
        # Empty STUN lists make the SFU advertise its public defaults.
        config["rtc"]["stun_servers"] = [f"{self.rtc_address}:{self.stun_port}"]
        if self.diagnostic:
            config["logging"]["level"] = "debug"
            config["logging"]["json"] = True
        # Refuse occupied ports rather than connect to or stop someone else's server.
        for kind, port in ((socket.SOCK_STREAM, self.http_port),
                           (socket.SOCK_DGRAM, self.udp_port)):
            with socket.socket(socket.AF_INET, kind) as check:
                check.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                check.bind((self.rtc_address if kind == socket.SOCK_DGRAM else "127.0.0.1", port))
        self.cache.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="server-", suffix=".json", dir=self.cache)
        self._config_path = Path(name)
        self._log = tempfile.TemporaryFile(mode="w+b", dir=self.cache)
        try:
            from .local_stun import LocalStunServer
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(config, handle)
            self._stun = LocalStunServer(self.rtc_address, self.stun_port).__enter__()
            self.process = subprocess.Popen(
                [str(self.executable), "--config", name, "--bind", "127.0.0.1"],
                stdin=subprocess.DEVNULL, stdout=self._log, stderr=self._log,
                creationflags=hidden_flags())
            self.pid = self.process.pid
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("livekit_server_exited_at_startup")
                try:
                    with socket.create_connection(("127.0.0.1", self.http_port), timeout=.2):
                        break
                except OSError:
                    time.sleep(.1)
            else:
                raise RuntimeError("livekit_server_startup_timeout")
            self.bindings = socket_snapshot(self.pid, self.expected_bindings)
            expected = {("tcp", self.http_port), ("udp", self.udp_port)}
            if not expected.issubset({(row["protocol"], row["port"]) for row in self.bindings}):
                raise RuntimeError("livekit_expected_loopback_sockets_missing")
            connection = http.client.HTTPConnection("127.0.0.1", self.http_port, timeout=2)
            try:
                connection.request("GET", "/")
                response = connection.getresponse()
                self.http_status = response.status
                response.read(1024)
            finally:
                connection.close()
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_: object) -> None:
        # Only the Popen process created above is ever stopped; never kill by name/port.
        try:
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.pid and socket_snapshot(self.pid):
                raise RuntimeError("livekit_server_socket_cleanup_failed")
            self.cleaned = self.process is not None and self.process.poll() is not None
        finally:
            if self._stun is not None:
                self._stun.__exit__(None, None, None)
            if hasattr(self, "_config_path"):
                self._config_path.unlink(missing_ok=True)
            if hasattr(self, "_log"):
                if self.diagnostic:
                    from .diagnostics import NativeTrace
                    trace = NativeTrace()
                    sites = Counter()
                    self._log.seek(0)
                    # JSON fields containing credentials or SDP are never copied.
                    for line in self._log.read(8_000_000).decode("utf-8", errors="replace").splitlines():
                        try:
                            entry = json.loads(line)
                            trace.observe(str(entry.get("msg", "")))
                            caller = entry.get("caller", "")
                            if re.fullmatch(r"[A-Za-z0-9_./-]+\.go:\d+", caller):
                                sites[caller] += 1
                        except (ValueError, TypeError):
                            pass
                    self.safe_trace = trace.snapshot()
                    self.safe_trace["source_sites"] = dict(sites)
                    # Server messages are parsed after exit; these positions are
                    # parse order, not real event elapsed-time measurements.
                    self.safe_trace["timeline_clock"] = "post_exit_parse_relative"
                self._log.close()
