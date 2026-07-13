from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.security import TicketSigner, hash_secret, license_lookup, normalize_license_code, verify_secret


def test_scrypt_and_normalization():
    encoded = hash_secret("XY-ABCDE-12345")
    assert verify_secret("XY-ABCDE-12345", encoded)
    assert not verify_secret("XY-WRONG-12345", encoded)
    assert normalize_license_code("xy-abcd-1234") == "XYABCD1234"
    assert license_lookup("xy-abcd-1234", b"x" * 32) == license_lookup("XYABCD1234", b"x" * 32)


def test_ed25519_ticket_round_trip():
    private = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    signer = TicketSigner(private)
    token = signer.sign({"purpose": "offline", "exp": 4102444800, "device_id": "device-1"})
    payload = signer.verify(token, purpose="offline")
    assert payload["device_id"] == "device-1"
    assert len(signer.public_key_base64()) > 30

