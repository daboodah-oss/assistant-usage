#!/usr/bin/env python3
"""ProxyCommand: tunnel SSH through the egress HTTP proxy via CONNECT.

Reads HTTPS_PROXY from the environment (http://user:pass@host:port),
opens a CONNECT tunnel to the target given as argv host/port, then
relays stdin/stdout <-> socket. Proxy credentials come from the env
and are never printed.
"""
import base64
import os
import select
import socket
import sys
import urllib.parse

host, port = sys.argv[1], int(sys.argv[2])
proxy = urllib.parse.urlparse(os.environ["HTTPS_PROXY"])
s = socket.create_connection((proxy.hostname, proxy.port), timeout=30)
auth = base64.b64encode(
    f"{urllib.parse.unquote(proxy.username)}:{urllib.parse.unquote(proxy.password)}".encode()
).decode()
s.sendall(
    f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
    f"Proxy-Authorization: Basic {auth}\r\n\r\n".encode()
)
resp = b""
while b"\r\n\r\n" not in resp:
    chunk = s.recv(4096)
    if not chunk:
        sys.exit(1)
    resp += chunk
if b" 200" not in resp.split(b"\r\n", 1)[0]:
    sys.exit(1)
s.setblocking(False)
stdin = sys.stdin.buffer
stdout = sys.stdout.buffer
while True:
    r, _, _ = select.select([s, stdin], [], [])
    if s in r:
        data = s.recv(65536)
        if not data:
            break
        stdout.write(data)
        stdout.flush()
    if stdin in r:
        data = os.read(0, 65536)
        if not data:
            break
        s.sendall(data)
