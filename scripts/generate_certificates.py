"""Generate self-signed TLS certificates for development use."""
from __future__ import annotations

import datetime
import logging
import os
import pathlib

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CERT_DIR = pathlib.Path(os.getenv("CERT_DIR", "certs"))


def generate_self_signed(
    hostname: str = "localhost",
    days_valid: int = 365,
    key_size: int = 2048,
) -> tuple[pathlib.Path, pathlib.Path]:
    """Generate a self-signed certificate and private key."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        CERT_DIR.mkdir(parents=True, exist_ok=True)
        key_path = CERT_DIR / "server.key"
        cert_path = CERT_DIR / "server.crt"

        # Generate private key
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_size)
        key_path.write_bytes(private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        ))

        # Generate certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Vela VPP"),
        ])
        now = datetime.datetime.utcnow()
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(private_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=days_valid))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname), x509.DNSName("localhost")]), critical=False)
            .sign(private_key, hashes.SHA256())
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        logger.info("Certificate generated: %s (valid %d days)", cert_path, days_valid)
        logger.info("Private key: %s", key_path)
        return cert_path, key_path

    except ImportError:
        logger.error("cryptography package not installed: pip install cryptography")
        raise


if __name__ == "__main__":
    cert, key = generate_self_signed(hostname="localhost", days_valid=365)
    print(f"Certificate: {cert}")
    print(f"Key: {key}")
    print(f"\nUsage: uvicorn vela.api.app:app --ssl-keyfile {key} --ssl-certfile {cert}")
