"""Self-signed certificate for serving the HUD over HTTPS on the LAN."""

from __future__ import annotations

import datetime as _dt
import ipaddress
import os
import socket
from pathlib import Path
from typing import List, Optional, Tuple

from amy.server.auth import amy_state_dir


def default_paths() -> Tuple[Path, Path]:
    d = amy_state_dir() / "tls"
    return d / "amy-cert.pem", d / "amy-key.pem"


def resolve_tls() -> Optional[Tuple[str, str]]:
    """(certfile, keyfile) from AMY_TLS_CERT/AMY_TLS_KEY, else the generated pair if present."""
    cert = os.environ.get("AMY_TLS_CERT") or ""
    key = os.environ.get("AMY_TLS_KEY") or ""
    if cert and key:
        return cert, key
    c, k = default_paths()
    if c.is_file() and k.is_file():
        return str(c), str(k)
    return None


def generate_self_signed(
    *, hosts: Optional[List[str]] = None, days: int = 825, out: Optional[Tuple[Path, Path]] = None
) -> Tuple[Path, Path]:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
    except ImportError as e:  # pragma: no cover - optional extra
        raise RuntimeError("pip install 'amy[tls]' (needs the cryptography package)") from e

    cert_path, key_path = out or default_paths()
    names = set(hosts or [])
    names.update({"localhost", "127.0.0.1", socket.gethostname()})
    try:
        from amy.server.app import _lan_ip

        names.add(_lan_ip())
    except Exception:  # noqa: S110 - LAN address is a nice-to-have SAN
        pass

    sans: List[x509.GeneralName] = []
    for n in sorted(names):
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(n)))
        except ValueError:
            sans.append(x509.DNSName(n))

    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Amy HUD (self-signed)")])
    now = _dt.datetime.now(_dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path
