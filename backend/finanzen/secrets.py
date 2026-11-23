"""Encryption of stored secrets (bank PINs) with AES-256-GCM and the key from SECRETS_KEY."""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "v1:"


class SecretsError(Exception):
    pass


def _key(secrets_key: str) -> bytes:
    if not secrets_key:
        raise SecretsError("SECRETS_KEY ist nicht gesetzt – PINs können nicht gespeichert werden.")
    try:
        key = base64.b64decode(secrets_key)
    except ValueError as exc:
        raise SecretsError("SECRETS_KEY ist kein gültiges Base64.") from exc
    if len(key) != 32:
        raise SecretsError("SECRETS_KEY muss 32 Byte lang sein (openssl rand -base64 32).")
    return key


def encrypt(secrets_key: str, plaintext: str, context: str) -> str:
    nonce = os.urandom(12)
    data = AESGCM(_key(secrets_key)).encrypt(nonce, plaintext.encode(), context.encode())
    return PREFIX + base64.b64encode(nonce + data).decode()


def decrypt(secrets_key: str, token: str, context: str) -> str:
    if not token.startswith(PREFIX):
        raise SecretsError("Unbekanntes Format")
    raw = base64.b64decode(token[len(PREFIX) :])
    try:
        return AESGCM(_key(secrets_key)).decrypt(raw[:12], raw[12:], context.encode()).decode()
    except Exception as exc:  # noqa: BLE001
        raise SecretsError("Die gespeicherte PIN lässt sich nicht entschlüsseln (SECRETS_KEY geändert?).") from exc
