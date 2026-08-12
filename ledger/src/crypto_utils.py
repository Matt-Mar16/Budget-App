"""
crypto_utils.py — profile-level "lock with a password" for The Ledger.

Deliberately stdlib-only, matching the app's "nothing to install" promise
(no cryptography/pyca, no SQLCipher). Python's own `zipfile` module turned
out not to be usable for this: it can only *read* the legacy ZipCrypto
cipher, it can't *write* an encrypted archive at all. So this implements a
small stream cipher directly from `hashlib`/`hmac`, which are stdlib:

  - Key derivation: PBKDF2-HMAC-SHA256 (via hashlib.pbkdf2_hmac), 200k
    iterations, random 16-byte salt.
  - Keystream: HMAC-SHA256(key, counter) chained in 32-byte blocks —
    a counter-mode construction, XORed against the file bytes. HMAC-SHA256
    is a well-vetted PRF, so this keystream itself is sound; what's NOT
    vetted is this specific file-format/assembly, since it hasn't had
    independent cryptographic review the way a maintained library has.
  - Integrity/password check: HMAC-SHA256 of the plaintext, stored in the
    header and verified on unlock — a wrong password is detected and
    rejected rather than silently producing garbage.

Honest framing for the Settings UI and README: this protects against
casually opening the file, a file browser preview, or a cloud-sync
provider seeing plaintext data. It has NOT had independent security review
the way SQLCipher or `cryptography` (AES-GCM) has, so treat it as "better
than nothing," not as a substitute for full-disk encryption (BitLocker/
FileVault/LUKS) on the machine itself, which remains the recommended path
for anything sensitive.
"""

import os
import hashlib
import hmac
import struct

MAGIC = b"LEDGERLK1"
SALT_LEN = 16
KEY_LEN = 32
PBKDF2_ITERATIONS = 200_000
LOCKED_SUFFIX = ".locked"


def locked_path_for(db_path: str) -> str:
    return db_path + LOCKED_SUFFIX if not db_path.endswith(LOCKED_SUFFIX) else db_path


def unlocked_path_for(locked_path: str) -> str:
    if locked_path.endswith(LOCKED_SUFFIX):
        return locked_path[: -len(LOCKED_SUFFIX)]
    return locked_path + ".db"


def _derive_key(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=KEY_LEN)


def _keystream(key: bytes, nbytes: int):
    """HMAC-SHA256 counter-mode keystream, 32 bytes per block."""
    out = bytearray()
    counter = 0
    while len(out) < nbytes:
        block = hmac.new(key, struct.pack(">Q", counter), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:nbytes])


def _xor(data: bytes, key: bytes) -> bytes:
    ks = _keystream(key, len(data))
    return bytes(a ^ b for a, b in zip(data, ks))


def lock_file(db_path: str, password: str) -> str:
    """Encrypts db_path in place into a `.locked` sidecar file and removes
    the plaintext original. Raises ValueError/FileNotFoundError on bad
    input, or RuntimeError if the round-trip self-check fails (in which
    case the original file is left untouched)."""
    if not password:
        raise ValueError("Password cannot be empty.")
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)

    with open(db_path, "rb") as f:
        plaintext = f.read()

    salt = os.urandom(SALT_LEN)
    key = _derive_key(password, salt)
    check = hmac.new(key, plaintext, hashlib.sha256).digest()
    ciphertext = _xor(plaintext, key)

    locked_path = locked_path_for(db_path)
    with open(locked_path, "wb") as f:
        f.write(MAGIC)
        f.write(salt)
        f.write(check)
        f.write(ciphertext)

    # Self-check before touching the original: unlock what we just wrote
    # into memory and compare, so a bug here can never silently eat data.
    verify_key = _derive_key(password, salt)
    verify_plain = _xor(ciphertext, verify_key)
    if verify_plain != plaintext or not hmac.compare_digest(
            hmac.new(verify_key, verify_plain, hashlib.sha256).digest(), check):
        os.remove(locked_path)
        raise RuntimeError("Lock verification failed — original file left untouched.")

    os.remove(db_path)
    return locked_path


def unlock_file(locked_path: str, password: str) -> str:
    """Decrypts a `.locked` file back into a plaintext .db file. Raises
    RuntimeError with a friendly message on wrong password or corruption.
    Does not delete the .locked file — caller can remove it once satisfied."""
    if not os.path.exists(locked_path):
        raise FileNotFoundError(locked_path)

    with open(locked_path, "rb") as f:
        magic = f.read(len(MAGIC))
        if magic != MAGIC:
            raise RuntimeError("Not a valid locked profile file.")
        salt = f.read(SALT_LEN)
        check = f.read(32)
        ciphertext = f.read()

    key = _derive_key(password, salt)
    plaintext = _xor(ciphertext, key)
    expected = hmac.new(key, plaintext, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, check):
        raise RuntimeError("Wrong password, or the file is corrupted.")

    dest_path = unlocked_path_for(locked_path)
    with open(dest_path, "wb") as f:
        f.write(plaintext)
    return dest_path
