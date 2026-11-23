"""Web push without extra dependencies: VAPID (RFC 8292) and aes128gcm payload encryption (RFC 8291/8188)."""

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

RECORD_SIZE = 4096


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_decode(text: str) -> bytes:
    text = text.strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def generate_vapid_keys() -> tuple[str, str]:
    """Returns (public, private) as base64url: uncompressed point and raw 32-byte scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return b64u_encode(_public_bytes(key.public_key())), b64u_encode(private)


def vapid_key(private_b64: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64u_decode(private_b64), "big"), ec.SECP256R1())


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None, sender: ec.EllipticCurvePrivateKey | None = None) -> bytes:
    """Encrypts a push message for a subscription (single aes128gcm record)."""
    ua_public = b64u_decode(p256dh)
    auth_secret = b64u_decode(auth)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    sender = sender or ec.generate_private_key(ec.SECP256R1())
    as_public = _public_bytes(sender.public_key())
    shared = sender.exchange(ec.ECDH(), receiver)
    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(payload) > RECORD_SIZE - 17 - 86:
        raise ValueError("push payload too large")
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    header = salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public
    return header + ciphertext


def vapid_headers(endpoint: str, public_b64: str, private_b64: str, subject: str) -> dict[str, str]:
    parsed = urlparse(endpoint)
    claims = {"aud": f"{parsed.scheme}://{parsed.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": subject or "mailto:admin@localhost"}
    token = jwt.encode(claims, vapid_key(private_b64), algorithm="ES256")
    return {"Authorization": f"vapid t={token}, k={public_b64}"}


@dataclass
class PushResult:
    ok: bool
    gone: bool  # subscription expired or unsubscribed -> delete it
    status: int


def send(endpoint: str, p256dh: str, auth: str, message: dict, *, public_key: str, private_key: str, subject: str, ttl: int = 86400, client: httpx.Client | None = None) -> PushResult:
    body = encrypt(json.dumps(message, ensure_ascii=False).encode(), p256dh, auth)
    headers = {
        **vapid_headers(endpoint, public_key, private_key, subject),
        "TTL": str(ttl),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "Urgency": "normal",
    }
    own = client is None
    client = client or httpx.Client(timeout=15)
    try:
        res = client.post(endpoint, content=body, headers=headers)
    except httpx.HTTPError:
        return PushResult(False, False, 0)
    finally:
        if own:
            client.close()
    return PushResult(res.status_code in (200, 201, 202), res.status_code in (404, 410), res.status_code)
