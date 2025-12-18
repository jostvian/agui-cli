import base64
import json
import os
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Generator, Iterable, Union
from urllib.parse import urlparse
from urllib.request import Request, urlopen

JsonValue = Union[str, int, float, bool, None, dict, list]


@dataclass
class AgUIMessage:
    """A normalized message coming from the ag-ui server."""

    text: str
    raw: JsonValue


class AgUIClient:
    """Minimal client capable of speaking to an ag-ui server.

    The implementation supports HTTP(S) streaming endpoints (Server-Sent Events
    or newline-delimited JSON) and WebSocket endpoints. The server URL is
    expected to be provided entirely via the AG_UI_SERVER environment variable
    or an explicit argument, including any path required by the server.
    """

    def __init__(self, server_url: str, timeout: int = 10) -> None:
        self.server_url = server_url
        self.timeout = timeout

    def stream(self, question: str) -> Generator[AgUIMessage, None, None]:
        """Stream responses for a question from the ag-ui server.

        Parameters
        ----------
        question:
            The prompt sent to the server. The value is wrapped in a simple JSON
            payload so the server can decide how to route the request.
        """

        parsed = urlparse(self.server_url)
        if parsed.scheme in {"ws", "wss"}:
            yield from self._stream_websocket(parsed, question)
        elif parsed.scheme in {"http", "https"}:
            yield from self._stream_http(parsed.geturl(), question)
        else:
            raise ValueError(f"Unsupported AG_UI_SERVER scheme: {parsed.scheme}")

    def _stream_http(self, url: str, question: str) -> Iterable[AgUIMessage]:
        payload = json.dumps({"question": question}, ensure_ascii=False).encode()
        req = Request(
            url,
            data=payload,
            headers={
                "Accept": "text/event-stream, application/json",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(req, timeout=self.timeout) as resp:
            for raw_line in resp:
                line = raw_line.decode(errors="replace").strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                yield self._normalize_message(line)

    def _stream_websocket(self, parsed, question: str) -> Iterable[AgUIMessage]:
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "wss" else 80)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        sock = socket.create_connection((hostname, port), timeout=self.timeout)
        if parsed.scheme == "wss":
            context = ssl.create_default_context()
            sock = context.wrap_socket(sock, server_hostname=hostname)

        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {hostname}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(handshake.encode())
        response_headers = self._read_http_response_headers(sock)
        if "101" not in response_headers.split("\r\n", 1)[0]:
            sock.close()
            raise ConnectionError("WebSocket upgrade failed")

        self._send_websocket_message(sock, json.dumps({"question": question}))
        try:
            for opcode, payload in self._recv_websocket_messages(sock):
                if opcode == 0x1:  # text frame
                    text = payload.decode(errors="replace")
                    yield self._normalize_message(text)
                elif opcode == 0x8:  # close
                    break
                elif opcode == 0x9:  # ping
                    self._send_websocket_frame(sock, 0xA, payload)
                # ignore binary and continuation frames for simplicity
        finally:
            sock.close()

    def _read_http_response_headers(self, sock: socket.socket) -> str:
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = sock.recv(1)
            if not chunk:
                break
            buffer += chunk
        return buffer.decode(errors="replace")

    def _send_websocket_message(self, sock: socket.socket, text: str) -> None:
        payload = text.encode()
        self._send_websocket_frame(sock, 0x1, payload, mask=True)

    def _send_websocket_frame(
        self, sock: socket.socket, opcode: int, payload: bytes, mask: bool = True
    ) -> None:
        first_byte = 0x80 | (opcode & 0x0F)
        length = len(payload)
        header = bytearray([first_byte])

        if length < 126:
            header.append((0x80 if mask else 0x00) | length)
        elif length < (1 << 16):
            header.append((0x80 if mask else 0x00) | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append((0x80 if mask else 0x00) | 127)
            header.extend(length.to_bytes(8, "big"))

        if mask:
            mask_key = os.urandom(4)
            header.extend(mask_key)
            masked_payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
            payload = masked_payload

        sock.sendall(header + payload)

    def _recv_exact(self, sock: socket.socket, nbytes: int) -> bytes:
        data = b""
        while len(data) < nbytes:
            chunk = sock.recv(nbytes - len(data))
            if not chunk:
                raise ConnectionError("Socket connection closed unexpectedly")
            data += chunk
        return data

    def _recv_websocket_messages(self, sock: socket.socket):
        while True:
            header = self._recv_exact(sock, 2)
            first, second = header
            opcode = first & 0x0F
            masked = (second & 0x80) != 0
            length = second & 0x7F

            if length == 126:
                length = int.from_bytes(self._recv_exact(sock, 2), "big")
            elif length == 127:
                length = int.from_bytes(self._recv_exact(sock, 8), "big")

            mask_key = b""
            if masked:
                mask_key = self._recv_exact(sock, 4)

            payload = self._recv_exact(sock, length) if length else b""
            if masked and length:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            yield opcode, payload
            time.sleep(0.01)  # yield control lightly for long streams

    def _normalize_message(self, raw_text: str) -> AgUIMessage:
        try:
            parsed: JsonValue = json.loads(raw_text)
        except json.JSONDecodeError:
            return AgUIMessage(text=raw_text, raw=raw_text)

        if isinstance(parsed, dict):
            prefix = (
                parsed.get("user")
                or parsed.get("sender")
                or parsed.get("name")
                or parsed.get("role")
            )
            body = (
                parsed.get("message")
                or parsed.get("content")
                or parsed.get("text")
                or parsed.get("body")
            )
            if body is None:
                body = json.dumps(parsed, ensure_ascii=False)
            elif isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False)

            text = f"{prefix}: {body}" if prefix else str(body)
            return AgUIMessage(text=text, raw=parsed)

        return AgUIMessage(text=str(parsed), raw=parsed)
