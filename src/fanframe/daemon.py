"""FanFrame privileged daemon.

Runs as root under systemd. It owns the only privileged operations — setting fan
duty and restoring automatic control — and exposes them over a group-restricted
Unix socket. The GUI never runs as root; it just talks to this socket.

Thermal failsafe: while in manual mode a background thread polls the CPU
sensors, and if any exceeds the critical threshold it hands control straight
back to the EC. This is a guardrail against a too-low manual duty, not a curve.
"""
from __future__ import annotations

import grp
import logging
import os
import socket
import threading
from dataclasses import dataclass, field

from . import ec, protocol, sensors

LOG = logging.getLogger("fanframed")

FAILSAFE_INTERVAL_S = 3.0
DEFAULT_CRITICAL_C = 92.0
MAX_REQUEST_BYTES = 64 * 1024
CLIENT_TIMEOUT_S = 5
LISTEN_BACKLOG = 8


@dataclass(frozen=True)
class State:
    # Manual duty per EC fan index (0-based). A fan absent from this map is
    # under automatic (EC) control.
    fans: dict[int, int] = field(default_factory=dict)


class Daemon:
    def __init__(
        self,
        socket_path: str = protocol.DEFAULT_SOCKET_PATH,
        controller: ec.EcController | None = None,
        socket_group: str | None = None,
        critical_c: float = DEFAULT_CRITICAL_C,
    ):
        self._socket_path = socket_path
        self._ec = controller or ec.EcController()
        self._group = socket_group
        self._critical_c = critical_c
        self._state = State()
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def _fans_view(self) -> dict[str, int]:
        # JSON object keys must be strings; keep the wire shape consistent
        # whether handle() is called in-process or over the socket.
        return {str(index): duty for index, duty in self._state.fans.items()}

    # ---- request handling -------------------------------------------------
    def handle(self, request: dict) -> dict:
        cmd = request.get("cmd")
        try:
            if cmd == protocol.CMD_STATUS:
                with self._lock:
                    return protocol.ok_response(fans=self._fans_view())
            if cmd == protocol.CMD_SET_DUTY:
                duty = protocol.clamp_duty(int(request.get("value", 0)))
                fan = request.get("fan")
                fan = int(fan) if fan is not None else None
                self._ec.set_duty(duty, fan)
                with self._lock:
                    fans = dict(self._state.fans)
                    if fan is None:
                        fans = {}  # all fans set at once: no meaningful per-fan state
                    else:
                        fans[fan] = duty
                    self._state = State(fans)
                LOG.info("manual duty %d%% on fan %s", duty, "all" if fan is None else fan)
                return protocol.ok_response(fan=fan, duty=duty)
            if cmd == protocol.CMD_AUTO:
                fan = request.get("fan")
                fan = int(fan) if fan is not None else None
                self._ec.set_auto(fan)
                with self._lock:
                    fans = dict(self._state.fans)
                    if fan is None:
                        fans = {}
                    else:
                        fans.pop(fan, None)
                    self._state = State(fans)
                LOG.info("automatic control restored for fan %s", "all" if fan is None else fan)
                return protocol.ok_response(fan=fan)
            return protocol.error_response(f"unknown command: {cmd!r}")
        except (ec.EcError, ValueError, TypeError) as exc:
            LOG.warning("command %r failed: %s", cmd, exc)
            return protocol.error_response(str(exc))

    # ---- thermal failsafe -------------------------------------------------
    def _failsafe_tick(self) -> None:
        with self._lock:
            manual = bool(self._state.fans)
        if not manual:
            return
        try:
            snapshot = sensors.read_snapshot()
        except OSError:
            return
        hottest = snapshot.max_cpu_celsius
        if hottest is None or hottest < self._critical_c:
            return
        LOG.warning("FAILSAFE: cpu %.1f C >= %.1f C, restoring auto", hottest, self._critical_c)
        try:
            self._ec.set_auto(None)
            with self._lock:
                self._state = State({})
        except ec.EcError as exc:
            LOG.error("failsafe could not restore auto: %s", exc)

    def _failsafe_loop(self) -> None:
        while not self._stop.wait(FAILSAFE_INTERVAL_S):
            self._failsafe_tick()

    # ---- socket server ----------------------------------------------------
    def _prepare_socket(self) -> socket.socket:
        parent = os.path.dirname(self._socket_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        try:
            os.unlink(self._socket_path)
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(self._socket_path)
        self._apply_permissions()
        server.listen(LISTEN_BACKLOG)
        return server

    def _apply_permissions(self) -> None:
        """Restrict the socket to a trusted group so only it can drive the fans."""
        os.chmod(self._socket_path, 0o660)
        if not self._group:
            return
        try:
            gid = grp.getgrnam(self._group).gr_gid
        except KeyError:
            LOG.warning("group %r not found, leaving socket group unchanged", self._group)
            return
        os.chown(self._socket_path, -1, gid)

    def _serve_client(self, conn: socket.socket) -> None:
        with conn:
            conn.settimeout(CLIENT_TIMEOUT_S)
            buffer = b""
            try:
                while b"\n" not in buffer:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    buffer += chunk
                    if len(buffer) > MAX_REQUEST_BYTES:
                        return
                line, _, _ = buffer.partition(b"\n")
                response = self.handle(protocol.decode_message(line))
            except (OSError, ValueError) as exc:
                response = protocol.error_response(str(exc))
            try:
                conn.sendall(protocol.encode_message(response))
            except OSError:
                pass

    def run(self) -> None:
        server = self._prepare_socket()
        LOG.info("listening on %s", self._socket_path)
        threading.Thread(target=self._failsafe_loop, name="failsafe", daemon=True).start()
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except OSError:
                    break
                self._serve_client(conn)
        finally:
            self._stop.set()
            server.close()
            try:
                os.unlink(self._socket_path)
            except FileNotFoundError:
                pass


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    daemon = Daemon(
        socket_path=os.environ.get("FANFRAME_SOCKET", protocol.DEFAULT_SOCKET_PATH),
        controller=ec.EcController(tool_path=os.environ.get("FANFRAME_TOOL", ec.DEFAULT_TOOL_PATH)),
        socket_group=os.environ.get("FANFRAME_GROUP") or None,
        critical_c=float(os.environ.get("FANFRAME_CRITICAL_C", DEFAULT_CRITICAL_C)),
    )
    daemon.run()


if __name__ == "__main__":
    main()
