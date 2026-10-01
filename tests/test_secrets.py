from __future__ import annotations

import pytest

from local_ai_lab.security.secrets import PassphraseProtector, SecretProtectionUnavailable


def test_linux_passphrase_protector_round_trip_and_tamper_rejection() -> None:
    protector = PassphraseProtector("long unique test passphrase 2026")
    encrypted = protector.protect("node-token-for-test")
    assert b"node-token-for-test" not in encrypted
    assert protector.unprotect(encrypted) == "node-token-for-test"
    assert protector.protect("node-token-for-test") != encrypted
    with pytest.raises(SecretProtectionUnavailable):
        PassphraseProtector("another long passphrase 2026").unprotect(encrypted)
    with pytest.raises(SecretProtectionUnavailable):
        protector.unprotect(encrypted[:-1] + bytes([encrypted[-1] ^ 1]))
