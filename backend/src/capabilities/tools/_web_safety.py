"""Public-web request guards for web tools."""

from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urljoin, urlparse


_DENIED_IP_REASONS = (
    "is_loopback",
    "is_private",
    "is_link_local",
    "is_reserved",
    "is_multicast",
    "is_unspecified",
)


def validate_public_http_url(url: str) -> str:
    """Validate that a URL targets a public HTTP(S) host."""

    parsed = urlparse(str(url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise PermissionError("url must be a valid public http(s) URL")

    host = parsed.hostname
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise PermissionError("url must include a valid port") from exc

    try:
        addr_infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise PermissionError(f"url host could not be resolved: {host}") from exc

    if not addr_infos:
        raise PermissionError(f"url host could not be resolved: {host}")

    for _, _, _, _, sockaddr in addr_infos:
        address = sockaddr[0]
        if _is_denied_ip(address):
            raise PermissionError(
                f"url target is not allowed: {host} resolves to {address}"
            )

    return parsed.geturl()


def open_public_url(
    request: urllib.request.Request,
    *,
    timeout: float,
) -> object:
    """Open a request after validating the original and redirected targets."""

    validate_public_http_url(request.full_url)
    opener = urllib.request.build_opener(_ValidatingRedirectHandler)
    return opener.open(request, timeout=max(1, min(timeout, 30)))


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate redirect destinations before urllib follows them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        target = urljoin(req.full_url, newurl)
        validate_public_http_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _is_denied_ip(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or any(getattr(ip, attr) for attr in _DENIED_IP_REASONS)
