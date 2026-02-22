"""
Credential Manager for IDME Module

Handles Fernet symmetric encryption for teacher passwords.
Passwords are encrypted before storing in the database and
decrypted on-demand during IDME login automation.

Ported from: idme-attendance-automation/automation/credential_manager.py
Simplified: Removed .env loading (teachers now in database via Web UI).
"""

import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken


class CredentialManagerError(Exception):
    """Base exception for credential manager errors."""
    pass


class EncryptionKeyNotFoundError(CredentialManagerError):
    """Raised when encryption key is not configured."""
    pass


class DecryptionError(CredentialManagerError):
    """Raised when password decryption fails."""
    pass


class CredentialManager:
    """
    Manages encryption and decryption of teacher passwords.

    Uses Fernet symmetric encryption (AES-128 in CBC mode).
    The encryption key comes from IDME_ENCRYPTION_KEY env var.
    """

    def __init__(self, encryption_key: Optional[str] = None):
        """
        Initialize credential manager.

        Args:
            encryption_key: Fernet encryption key string.
                If not provided, reads from IDME_ENCRYPTION_KEY env var.

        Raises:
            EncryptionKeyNotFoundError: If no encryption key found.
        """
        self.logger = logging.getLogger(__name__)

        if not encryption_key:
            import os
            encryption_key = os.getenv('IDME_ENCRYPTION_KEY', '')

        if not encryption_key:
            raise EncryptionKeyNotFoundError(
                "IDME_ENCRYPTION_KEY not found. "
                "Generate one: python -c \"from cryptography.fernet import Fernet; "
                "print(Fernet.generate_key().decode())\""
            )

        try:
            key_bytes = encryption_key.encode() if isinstance(encryption_key, str) else encryption_key
            self.cipher = Fernet(key_bytes)
            self.logger.info("Credential manager initialized")
        except Exception as e:
            raise CredentialManagerError(f"Failed to initialize cipher: {e}")

    def encrypt_password(self, plaintext_password: str) -> str:
        """
        Encrypt a plaintext password.

        Args:
            plaintext_password: The password to encrypt.

        Returns:
            Encrypted password as base64-encoded string (gAAAAAB...).
        """
        try:
            encrypted = self.cipher.encrypt(plaintext_password.encode())
            return encrypted.decode()
        except Exception as e:
            raise CredentialManagerError(f"Encryption failed: {e}")

    def decrypt_password(self, encrypted_password: str) -> str:
        """
        Decrypt an encrypted password.

        Args:
            encrypted_password: The Fernet-encrypted password string.

        Returns:
            Decrypted plaintext password.

        Raises:
            DecryptionError: If decryption fails (wrong key or corrupted data).
        """
        try:
            decrypted = self.cipher.decrypt(encrypted_password.encode())
            return decrypted.decode()
        except InvalidToken:
            raise DecryptionError(
                "Decryption failed: invalid token or wrong encryption key."
            )
        except Exception as e:
            raise DecryptionError(f"Decryption failed: {e}")

    @staticmethod
    def generate_encryption_key() -> str:
        """
        Generate a new Fernet encryption key.

        Returns:
            New encryption key as string.
        """
        return Fernet.generate_key().decode()
