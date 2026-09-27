"""Thin product-side client. Transport retry must reuse the exact request_id."""

import socket

from .lifecycle import validate
from .schema import ControlError, canonical, decode, require


def call(socket_path, request, *, timeout=5):
    raw = canonical(validate(request)).encode()
    require(len(raw) <= 4096, "request_too_large")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(socket_path)
        connection.sendall(raw)
        connection.shutdown(socket.SHUT_WR)
        data = bytearray()
        while True:
            part = connection.recv(4096)
            if not part:
                break
            data.extend(part)
            require(len(data) <= 1024 * 1024, "response_too_large")
    result = decode(bytes(data))
    if not result["ok"]:
        raise ControlError(result["error"])
    return result
