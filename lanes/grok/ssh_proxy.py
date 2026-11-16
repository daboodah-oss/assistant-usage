#!/usr/bin/env python3
"""ProxyCommand: tunnel SSH through the box's HTTP CONNECT egress proxy.

Grok-lane variant of lanes/muse/ssh_proxy.py. Proxy address, in order:
HTTPS_PROXY / https_proxy (http://[user:pass@]host:port; credentials optional),
then SAND_EGRESS_TUNNEL_PROXY_ADDR (host:port, no auth). Credentials are never printed.
Usage: ssh -o ProxyCommand='python3 ssh_proxy.py %h %p' ...
"""
import base64, os, select, socket, sys, urllib.parse

host, port = sys.argv[1], int(sys.argv[2])
raw = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
if raw:
    p = urllib.parse.urlparse(raw if "://" in raw else "http://" + raw)
    phost, pport, user, pw = p.hostname, p.port or 80, p.username, p.password
else:
    addr = os.environ.get("SAND_EGRESS_TUNNEL_PROXY_ADDR", "127.0.0.1:8791")
    phost, _, pp = addr.rpartition(":"); pport, user, pw = int(pp), None, None
s = socket.create_connection((phost, pport), timeout=30)
hdr = f"CONNECT {host}:{port} HTTP/1.1\r\nHost: {host}:{port}\r\n"
if user is not None:
    cred = f"{urllib.parse.unquote(user)}:{urllib.parse.unquote(pw or '')}".encode()
    hdr += "Proxy-Authorization: Basic " + base64.b64encode(cred).decode() + "\r\n"
s.sendall((hdr + "\r\n").encode())
resp = b""
while b"\r\n\r\n" not in resp:
    chunk = s.recv(4096)
    if not chunk:
        sys.exit(1)
    resp += chunk
if b" 200" not in resp.split(b"\r\n", 1)[0]:
    sys.stderr.write("ssh_proxy: CONNECT refused: %r\n" % resp.split(b"\r\n", 1)[0][:80]); sys.exit(1)
extra = resp.split(b"\r\n\r\n", 1)[1]
if extra:
    sys.stdout.buffer.write(extra); sys.stdout.buffer.flush()
s.settimeout(None)
while True:
    r, _, _ = select.select([s, 0], [], [])
    if s in r:
        data = s.recv(65536)
        if not data:
            break
        sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
    if 0 in r:
        data = os.read(0, 65536)
        if not data:
            break
        s.sendall(data)
