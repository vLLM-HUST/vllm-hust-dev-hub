"""Bounded authenticated local API with a separate durable-operation worker."""

import os
from pathlib import Path
import socket
import socketserver
import stat
import threading
import time

from .host_authority import peer_from_unix_socket
from .lifecycle import PROTOCOL
from .schema import ControlError, canonical, decode, require

MAX_REQUEST = 4096


class LifecycleServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = False
    block_on_close = True
    # Bound concurrent clients, including peers which do not finish their body.
    request_queue_size = 16

    def __init__(self, path, authority):
        self.authority = authority
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(path, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        connection = self.request
        connection.settimeout(2)
        try:
            uid = peer_from_unix_socket(connection).uid
            raw = bytearray()
            deadline = time.monotonic() + 2
            while True:
                connection.settimeout(max(0.001, deadline - time.monotonic()))
                require(time.monotonic() < deadline, "request_timeout")
                part = connection.recv(MAX_REQUEST + 1 - len(raw))
                if not part:
                    break
                raw.extend(part)
                require(len(raw) <= MAX_REQUEST, "request_too_large")
            result = self.server.authority.dispatch(uid, decode(bytes(raw)))
            payload = {"ok": True, "protocol": PROTOCOL, **result}
        except ControlError as exc:
            payload = {"ok": False, "protocol": PROTOCOL, "error": str(exc)}
        except Exception:
            payload = {
                "ok": False,
                "protocol": PROTOCOL,
                "error": "service_unavailable",
            }
        try:
            connection.sendall((canonical(payload) + "\n").encode())
        except OSError:
            pass  # Disconnect cannot cancel or duplicate an admitted operation.


def serve(path, authority, *, socket_gid=None, stop=None):
    """Private socket parent must already exist; never replace a live listener."""
    import fcntl

    stop = stop or threading.Event()
    path = Path(path)
    require(path.is_absolute() and path.resolve() == path, "invalid_socket_path")
    parent = path.parent.stat()
    require(
        parent.st_uid == os.geteuid()
        and stat.S_IMODE(parent.st_mode) in {0o700, 0o750},
        "private_socket_directory_required",
    )
    fd = os.open(
        authority.store.root / "lifecycle-server.lock",
        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
        0o600,
    )
    server = None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if path.exists():
            info = path.lstat()
            require(
                stat.S_ISSOCK(info.st_mode) and info.st_uid == os.geteuid(),
                "unsafe_socket_path",
            )
            # Same state directory is the mandatory singleton scope. Also refuse
            # any reachable listener, even if configured against a different DB.
            with socket.socket(socket.AF_UNIX) as probe:
                probe.settimeout(0.25)
                try:
                    probe.connect(str(path))
                except ConnectionRefusedError:
                    pass
                else:
                    raise ControlError("listener_already_running")
            path.unlink()
        server = LifecycleServer(str(path), authority)
        if socket_gid is not None:
            os.chown(path, os.geteuid(), socket_gid)
        os.chmod(path, 0o660 if socket_gid is not None else 0o600)
        server.timeout = 0.2

        def worker():
            while not stop.is_set():
                try:
                    changed = authority.tick()
                except Exception:
                    changed = False  # Durable pending state survives outages.
                stop.wait(0.01 if changed else 0.2)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        while not stop.is_set():
            server.handle_request()
        # Qualified backend effects are bounded; complete before releasing scope.
        thread.join()
    finally:
        if server is not None:
            server.server_close()
            path.unlink(missing_ok=True)
        os.close(fd)
