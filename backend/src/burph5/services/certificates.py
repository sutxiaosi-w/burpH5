from __future__ import annotations

import hashlib
import ipaddress
import shutil
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


ROOT_CA_COMMON_NAME = "burph5 Root CA"


@dataclass(slots=True)
class CertificateAuthorityStatus:
    ready: bool
    installed: bool | None
    subject: str | None
    thumbprint: str | None
    cert_path: str | None
    leaf_cert_count: int
    last_error: str | None = None


@dataclass(slots=True)
class IssuedLeafCertificate:
    hostname: str
    cert_path: Path
    key_path: Path


class CertificateAuthority:
    def __init__(self, certs_dir: Path) -> None:
        self._certs_dir = certs_dir
        self._leaf_dir = certs_dir / "leaf"
        self._ca_cert_path = certs_dir / "burph5-root-ca.cer"
        self._ca_key_path = certs_dir / "burph5-root-ca-key.pem"
        self._last_error: str | None = None

    @property
    def ca_cert_path(self) -> Path:
        self.ensure_ca()
        return self._ca_cert_path

    def ensure_ca(self) -> CertificateAuthorityStatus:
        try:
            self._certs_dir.mkdir(parents=True, exist_ok=True)
            self._leaf_dir.mkdir(parents=True, exist_ok=True)
            if not self._ca_cert_path.exists() or not self._ca_key_path.exists():
                self._generate_ca()
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
            raise
        return self.get_status()

    def get_status(self) -> CertificateAuthorityStatus:
        cert = self._load_certificate(self._ca_cert_path)
        thumbprint = self._fingerprint(cert) if cert else None
        installed = self._is_installed_in_windows_store(thumbprint) if cert else None
        return CertificateAuthorityStatus(
            ready=cert is not None and self._ca_key_path.exists(),
            installed=installed,
            subject=cert.subject.rfc4514_string() if cert else None,
            thumbprint=thumbprint,
            cert_path=str(self._ca_cert_path) if cert and self._ca_cert_path.exists() else None,
            leaf_cert_count=len(list(self._leaf_dir.glob("*.crt.pem"))) if self._leaf_dir.exists() else 0,
            last_error=self._last_error,
        )

    def issue_leaf_certificate(self, hostname: str) -> IssuedLeafCertificate:
        normalized_host = self._normalize_host(hostname)
        self.ensure_ca()
        digest = hashlib.sha1(normalized_host.encode("utf-8")).hexdigest()
        cert_path = self._leaf_dir / f"{digest}.crt.pem"
        key_path = self._leaf_dir / f"{digest}.key.pem"
        if cert_path.exists() and key_path.exists():
            return IssuedLeafCertificate(hostname=normalized_host, cert_path=cert_path, key_path=key_path)

        ca_cert = self._load_certificate(self._ca_cert_path)
        ca_key = self._load_private_key(self._ca_key_path)
        if ca_cert is None or ca_key is None:
            raise RuntimeError("Root CA is not available.")

        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, normalized_host),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "burph5"),
            ]
        )
        builder = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(leaf_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=True,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=False,
                    crl_sign=False,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName(self._build_subject_alternative_names(normalized_host)),
                critical=False,
            )
            .add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
                critical=False,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(leaf_key.public_key()),
                critical=False,
            )
        )
        certificate = builder.sign(private_key=ca_key, algorithm=hashes.SHA256())
        cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(
            leaf_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self._last_error = None
        return IssuedLeafCertificate(hostname=normalized_host, cert_path=cert_path, key_path=key_path)

    def create_server_context(self, hostname: str) -> ssl.SSLContext:
        leaf = self.issue_leaf_certificate(hostname)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.set_alpn_protocols(["http/1.1"])
        context.load_cert_chain(str(leaf.cert_path), str(leaf.key_path))
        return context

    def install_to_windows(self) -> CertificateAuthorityStatus:
        self.ensure_ca()
        if not self._is_windows():
            raise RuntimeError("Automatic certificate installation is only supported on Windows.")
        script = (
            f"$null = Import-Certificate -FilePath '{self._ca_cert_path}' "
            " -CertStoreLocation 'Cert:\\CurrentUser\\Root';"
        )
        self._run_powershell(script)
        self._last_error = None
        return self.get_status()

    def clear_leaf_certificates(self) -> CertificateAuthorityStatus:
        self.ensure_ca()
        if self._leaf_dir.exists():
            for path in self._leaf_dir.iterdir():
                if path.is_file():
                    path.unlink()
        self._last_error = None
        return self.get_status()

    def delete_all(self) -> CertificateAuthorityStatus:
        previous_status = self.get_status()
        if previous_status.thumbprint and self._is_windows():
            try:
                self._uninstall_from_windows(previous_status.thumbprint)
            except Exception:
                pass
        if self._certs_dir.exists():
            shutil.rmtree(self._certs_dir)
        self._last_error = None
        return self.get_status()

    def reset(self) -> CertificateAuthorityStatus:
        previous_status = self.get_status()
        if previous_status.thumbprint and self._is_windows():
            try:
                self._uninstall_from_windows(previous_status.thumbprint)
            except Exception:
                # Keep resetting local files even if the old Windows trust entry is already gone.
                pass

        if self._certs_dir.exists():
            shutil.rmtree(self._certs_dir)
        self._certs_dir.mkdir(parents=True, exist_ok=True)
        self._leaf_dir.mkdir(parents=True, exist_ok=True)
        self._generate_ca()
        self._last_error = None
        return self.get_status()

    def _generate_ca(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        now = datetime.now(UTC)
        subject = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, ROOT_CA_COMMON_NAME),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "burph5"),
            ]
        )
        certificate = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True,
                    content_commitment=False,
                    key_encipherment=False,
                    data_encipherment=False,
                    key_agreement=False,
                    key_cert_sign=True,
                    crl_sign=True,
                    encipher_only=False,
                    decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()),
                critical=False,
            )
            .sign(private_key=key, algorithm=hashes.SHA256())
        )

        self._ca_cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
        self._ca_key_path.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    def _load_certificate(self, path: Path) -> x509.Certificate | None:
        if not path.exists():
            return None
        return x509.load_pem_x509_certificate(path.read_bytes())

    def _load_private_key(self, path: Path):
        if not path.exists():
            return None
        return serialization.load_pem_private_key(path.read_bytes(), password=None)

    def _fingerprint(self, certificate: x509.Certificate | None) -> str | None:
        if certificate is None:
            return None
        return certificate.fingerprint(hashes.SHA1()).hex().upper()

    def _build_subject_alternative_names(self, hostname: str) -> list[x509.GeneralName]:
        try:
            return [x509.IPAddress(ipaddress.ip_address(hostname))]
        except ValueError:
            return [x509.DNSName(hostname)]

    def _normalize_host(self, host: str) -> str:
        normalized = host.strip().lower()
        if normalized.startswith("[") and normalized.endswith("]"):
            normalized = normalized[1:-1]
        return normalized.rstrip(".")

    def _is_installed_in_windows_store(self, thumbprint: str | None) -> bool | None:
        if not self._is_windows() or not thumbprint:
            return None
        try:
            result = subprocess.run(
                ["certutil", "-user", "-store", "Root"],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            self._last_error = (exc.stderr or exc.stdout or str(exc)).strip()
            return None
        normalized_thumbprint = thumbprint.replace(" ", "").upper()
        output = (result.stdout or "").replace(" ", "").upper()
        return normalized_thumbprint in output

    def _uninstall_from_windows(self, thumbprint: str) -> None:
        script = (
            "$cert = Get-ChildItem 'Cert:\\CurrentUser\\Root' "
            f"| Where-Object {{ $_.Thumbprint -eq '{thumbprint}' }} "
            "| Select-Object -First 1;"
            "if ($cert) { Remove-Item -Path $cert.PSPath }"
        )
        self._run_powershell(script, allow_empty=True)

    def _run_powershell(self, script: str, allow_empty: bool = False) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            self._last_error = (exc.stderr or exc.stdout or str(exc)).strip()
            raise RuntimeError(self._last_error) from exc
        if not allow_empty and not result.stdout.strip() and not result.stderr.strip():
            return result
        self._last_error = None
        return result

    def _is_windows(self) -> bool:
        return sys.platform.startswith("win")
