import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

class IdempotencyError(Exception):
    """Base exception for idempotency failures."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)

class ReplayDetectedError(IdempotencyError):
    """Raised when an already-used nonce is submitted again."""

    def __init__(self, nonce: str):
        super().__init__(
            code="REPLAY_DETECTED",
            message=f"Request nonce has already been used: {nonce}",
        )

class IdempotencyConflictError(IdempotencyError):
    """
    Raised when the same idempotency key is reused with
    a different request payload.
    """

    def __init__(self, key: str):
        super().__init__(
            code="IDEMPOTENCY_CONFLICT",
            message=(
                "The idempotency key was previously used with "
                "a different request payload."
            ),
        )

@dataclass
class IdempotencyRecord:
    """
    Stored result of a processed request.
    """
    request_hash: str
    response: Any
    created_at: int
    expires_at: int

class IdempotencyLedger:
    """
    Thread-safe in-memory idempotency and replay-defense ledger.

    The ledger protects settlement operations from:
        - duplicate agent retries
        - replayed nonces
        - reused idempotency keys with modified payloads

    This is intentionally an in-memory implementation for the
    initial AMPP prototype. Redis SETNX will replace it later.
    """

    def __init__(
        self,
        ttl_seconds: int = 300,
        secret: str = "ampp-development-secret",
    ):
        self.ttl_seconds = ttl_seconds
        self.secret = secret.encode()
        self._records: dict[str, IdempotencyRecord] = {}
        self._used_nonces: dict[str, int] = {}
        self._lock = Lock()

    # Canonical request hashing
    def _canonicalize(self, payload: Any) -> bytes:
        """
        Convert a request payload into deterministic bytes.

        Sorting keys ensures that:

            {"a": 1, "b": 2}

        and

            {"b": 2, "a": 1}

        produce the same hash.
        """
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()

    def request_hash(self, payload: Any) -> str:
        """
        Return a SHA-256 hash of the canonical request payload.
        """
        canonical_payload = self._canonicalize(payload)
        return hashlib.sha256(
            canonical_payload
        ).hexdigest()

    # HMAC request fingerprint
    def fingerprint(
        self,
        payload: Any,
        nonce: str,
        timestamp: int,
    ) -> str:
        """
        Generate an HMAC-SHA256 fingerprint over:

            payload + nonce + timestamp

        This gives us a tamper-evident request identifier.
        """
        message = (
            self._canonicalize(payload)
            + b"|"
            + nonce.encode()
            + b"|"
            + str(timestamp).encode()
        )

        return hmac.new(
            self.secret,
            message,
            hashlib.sha256,
        ).hexdigest()

    # Cleanup
    def _cleanup_expired(self, now: int) -> None:
        """
        Remove expired idempotency records and nonces.
        """
        expired_keys = [
            key
            for key, record in self._records.items()
            if record.expires_at <= now
        ]

        for key in expired_keys:
            del self._records[key]

        expired_nonces = [
            nonce
            for nonce, expires_at in self._used_nonces.items()
            if expires_at <= now
        ]

        for nonce in expired_nonces:
            del self._used_nonces[nonce]

    # Nonce replay protection
    def check_nonce(
        self,
        nonce: str,
        *,
        now: int | None = None,
    ) -> None:
        """
        Verify that a nonce has not already been consumed.

        Raises:
            ReplayDetectedError
        """
        current_time = (
            int(time.time())
            if now is None
            else now
        )

        with self._lock:
            self._cleanup_expired(current_time)
            if nonce in self._used_nonces:
                raise ReplayDetectedError(nonce)

    def consume_nonce(
        self,
        nonce: str,
        *,
        now: int | None = None,
    ) -> None:
        """
        Atomically consume a nonce.

        This performs the check and insertion under the same lock,
        preventing two concurrent requests from consuming the
        same nonce.
        """
        current_time = (
            int(time.time())
            if now is None
            else now
        )

        with self._lock:
            self._cleanup_expired(current_time)
            if nonce in self._used_nonces:
                raise ReplayDetectedError(nonce)
            self._used_nonces[nonce] = (
                current_time + self.ttl_seconds
            )

    # Idempotency lookup
    def get(
        self,
        key: str,
        *,
        now: int | None = None,
    ) -> Any | None:
        """
        Return the cached response for an idempotency key.

        Returns None when the key has not been processed or has
        expired.
        """
        current_time = (
            int(time.time())
            if now is None
            else now
        )

        with self._lock:
            self._cleanup_expired(current_time)
            record = self._records.get(key)
            if record is None:
                return None
            return record.response

    def get_for_payload(
        self,
        key: str,
        payload: Any,
        *,
        now: int | None = None,
    ) -> Any | None:
        """
        Return the cached response for an idempotency key when the
        payload matches.

        Raises IdempotencyConflictError if the same key was previously
        used with a different payload.
        """
        current_time = (
            int(time.time())
            if now is None
            else now
        )
        payload_hash = self.request_hash(payload)

        with self._lock:
            self._cleanup_expired(current_time)
            existing = self._records.get(key)
            if existing is None:
                return None
            if existing.request_hash != payload_hash:
                raise IdempotencyConflictError(key)
            return existing.response

    # Idempotency registration
    def store(
        self,
        key: str,
        payload: Any,
        response: Any,
        *,
        now: int | None = None,
    ) -> None:
        """
        Store a successful request response.

        If the same key already exists:
            - same payload → idempotent replay
            - different payload → conflict
        """
        current_time = (
            int(time.time())
            if now is None
            else now
        )
        payload_hash = self.request_hash(payload)

        with self._lock:
            self._cleanup_expired(current_time)
            existing = self._records.get(key)
            if existing is not None:
                if existing.request_hash != payload_hash:
                    raise IdempotencyConflictError(key)
                return
            self._records[key] = IdempotencyRecord(
                request_hash=payload_hash,
                response=response,
                created_at=current_time,
                expires_at=current_time + self.ttl_seconds,
            )

    # Atomic request processing
    def execute(
        self,
        *,
        key: str,
        payload: Any,
        nonce: str,
        timestamp: int,
        operation,
    ) -> Any:
        """
        Execute an idempotent operation.

        Behavior:

        First request:
            validate → execute → cache result

        Same request again:
            return cached result

        Same key + different payload:
            reject

        Reused nonce:
            reject

        `operation` must be a callable accepting no arguments.
        """
        current_time = int(time.time())

        with self._lock:
            self._cleanup_expired(current_time)
            payload_hash = self.request_hash(payload)

            # Existing idempotency key
            existing = self._records.get(key)
            if existing is not None:
                if existing.request_hash != payload_hash:
                    raise IdempotencyConflictError(key)
                return existing.response

            # Replay protection
            if nonce in self._used_nonces:
                raise ReplayDetectedError(nonce)

            # Consume nonce before executing the operation.
            # This is important: concurrent retries must not both
            # reach the payment provider.
            self._used_nonces[nonce] = (
                current_time + self.ttl_seconds
            )

        # Execute outside the lock.
        response = operation()

        # Cache successful result.
        self.store(
            key=key,
            payload=payload,
            response=response,
            now=current_time,
        )

        return response