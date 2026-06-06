"""
Key rotation and cryptographic key management for the Vela VPP platform.

Manages symmetric and asymmetric keys for:
  - API authentication tokens
  - Field device communication encryption
  - Data-at-rest encryption keys
  - HMAC signing keys for audit logs

Follows NIST SP 800-57 key management recommendations.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple


class KeyPurpose(str, Enum):
    API_AUTH = "api_auth"
    DATA_ENCRYPTION = "data_encryption"
    AUDIT_SIGNING = "audit_signing"
    DEVICE_COMM = "device_comm"
    TOKEN_SIGNING = "token_signing"


class KeyStatus(str, Enum):
    ACTIVE = "active"
    PRE_ACTIVE = "pre_active"       # Generated, not yet in use
    INACTIVE = "inactive"           # Superseded, retained for decryption
    COMPROMISED = "compromised"     # Must not be used
    DESTROYED = "destroyed"         # Key material deleted


@dataclass
class CryptoKey:
    key_id: str
    purpose: KeyPurpose
    algorithm: str          # "AES-256-GCM", "HMAC-SHA256", "Ed25519"
    status: KeyStatus
    created_at: datetime
    activated_at: Optional[datetime]
    expires_at: Optional[datetime]
    rotation_due_at: Optional[datetime]
    key_material: bytes     # In production: this would be a KMS reference, not plaintext
    version: int = 1
    tags: Dict[str, str] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def needs_rotation(self) -> bool:
        if self.rotation_due_at is None:
            return False
        return datetime.now(timezone.utc) > self.rotation_due_at


class KeyStore:
    """In-memory key store (production should use HSM or cloud KMS)."""

    def __init__(self) -> None:
        self._keys: Dict[str, CryptoKey] = {}

    def store(self, key: CryptoKey) -> None:
        self._keys[key.key_id] = key

    def get(self, key_id: str) -> CryptoKey:
        if key_id not in self._keys:
            raise KeyError(f"Key {key_id} not found")
        return self._keys[key_id]

    def list_active(self, purpose: Optional[KeyPurpose] = None) -> List[CryptoKey]:
        keys = [k for k in self._keys.values() if k.status == KeyStatus.ACTIVE]
        if purpose:
            keys = [k for k in keys if k.purpose == purpose]
        return keys

    def deactivate(self, key_id: str) -> None:
        key = self.get(key_id)
        key.status = KeyStatus.INACTIVE

    def mark_compromised(self, key_id: str) -> None:
        key = self.get(key_id)
        key.status = KeyStatus.COMPROMISED


class KeyManager:
    """
    NIST-compliant key lifecycle manager.

    Handles key generation, activation, rotation, and destruction
    following SP 800-57 Part 1 guidelines.
    """

    # Key lifetimes by purpose (days)
    KEY_LIFETIMES: Dict[KeyPurpose, int] = {
        KeyPurpose.API_AUTH: 90,
        KeyPurpose.DATA_ENCRYPTION: 365,
        KeyPurpose.AUDIT_SIGNING: 730,
        KeyPurpose.DEVICE_COMM: 365,
        KeyPurpose.TOKEN_SIGNING: 30,
    }

    # Rotation warning period (days before expiry)
    ROTATION_WARNING_DAYS: int = 14

    def __init__(self, store: Optional[KeyStore] = None) -> None:
        self.store = store or KeyStore()
        self._rotation_log: List[Dict] = []

    def generate_key(
        self,
        purpose: KeyPurpose,
        algorithm: str = "HMAC-SHA256",
        tags: Optional[Dict[str, str]] = None,
        activate_immediately: bool = True,
    ) -> CryptoKey:
        """
        Generate a new cryptographic key.

        Returns:
            Newly created CryptoKey.
        """
        now = datetime.now(timezone.utc)
        lifetime_days = self.KEY_LIFETIMES.get(purpose, 365)
        rotation_days = lifetime_days - self.ROTATION_WARNING_DAYS

        # Generate key material (length by algorithm)
        key_len = {
            "AES-256-GCM": 32,
            "AES-128-GCM": 16,
            "HMAC-SHA256": 32,
            "HMAC-SHA512": 64,
            "Ed25519": 32,
        }.get(algorithm, 32)

        key_material = os.urandom(key_len)

        # Existing active key for same purpose -> deactivate
        if activate_immediately:
            for old_key in self.store.list_active(purpose):
                self.store.deactivate(old_key.key_id)

        key = CryptoKey(
            key_id=str(uuid.uuid4()),
            purpose=purpose,
            algorithm=algorithm,
            status=KeyStatus.ACTIVE if activate_immediately else KeyStatus.PRE_ACTIVE,
            created_at=now,
            activated_at=now if activate_immediately else None,
            expires_at=now + timedelta(days=lifetime_days),
            rotation_due_at=now + timedelta(days=rotation_days),
            key_material=key_material,
            tags=tags or {},
        )
        self.store.store(key)
        return key

    def rotate_key(self, key_id: str) -> Tuple[CryptoKey, CryptoKey]:
        """
        Rotate a key: generate successor, deactivate predecessor.

        Returns:
            (old_key, new_key)
        """
        old_key = self.store.get(key_id)
        new_key = self.generate_key(
            purpose=old_key.purpose,
            algorithm=old_key.algorithm,
            tags={**old_key.tags, "rotated_from": key_id},
            activate_immediately=True,
        )
        new_key.version = old_key.version + 1

        self._rotation_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "old_key_id": key_id,
            "new_key_id": new_key.key_id,
            "purpose": old_key.purpose.value,
            "reason": "scheduled_rotation",
        })
        return old_key, new_key

    def check_rotation_due(self) -> List[CryptoKey]:
        """Return all active keys that are due for rotation."""
        return [
            k for k in self.store.list_active()
            if k.needs_rotation or k.is_expired
        ]

    def sign(self, key_id: str, data: bytes) -> str:
        """
        HMAC-sign data with the specified key.

        Returns:
            Base64-encoded signature.
        """
        key = self.store.get(key_id)
        if key.status != KeyStatus.ACTIVE:
            raise ValueError(f"Key {key_id} is not active (status: {key.status})")
        if key.algorithm not in ("HMAC-SHA256", "HMAC-SHA512"):
            raise ValueError(f"Key {key_id} algorithm {key.algorithm} not suitable for signing")

        h_algo = hashlib.sha256 if "256" in key.algorithm else hashlib.sha512
        mac = hmac.new(key.key_material, data, h_algo).digest()
        return base64.b64encode(mac).decode()

    def verify(self, key_id: str, data: bytes, signature: str) -> bool:
        """Verify HMAC signature."""
        key = self.store.get(key_id)
        h_algo = hashlib.sha256 if "256" in key.algorithm else hashlib.sha512
        expected_mac = hmac.new(key.key_material, data, h_algo).digest()
        try:
            provided_mac = base64.b64decode(signature.encode())
            return hmac.compare_digest(expected_mac, provided_mac)
        except Exception:
            return False

    def rotation_history(self) -> List[Dict]:
        return list(self._rotation_log)
