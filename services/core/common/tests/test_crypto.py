import pytest
from django.core.exceptions import ImproperlyConfigured

from common.crypto import (
    DecryptionError,
    blind_index,
    decrypt,
    encrypt,
    mask,
    normalize_account,
)

IBAN = "PK36MEZN0102003300441201"


def test_round_trip_and_random_nonce() -> None:
    first = encrypt(IBAN, org_id="org_a")
    second = encrypt(IBAN, org_id="org_a")
    assert first.startswith("v1:") and first != second
    assert IBAN not in first
    assert decrypt(first, org_id="org_a") == IBAN


def test_value_is_bound_to_its_org() -> None:
    token = encrypt(IBAN, org_id="org_a")
    with pytest.raises(DecryptionError):
        decrypt(token, org_id="org_b")


@pytest.mark.parametrize("token", ["v2:abc", "v1:not-base64!", "v1:" + "A" * 40])
def test_tampered_or_unknown_values_are_rejected(token: str) -> None:
    with pytest.raises(DecryptionError):
        decrypt(token, org_id="org_a")


def test_blind_index_matches_formatting_variants_only_within_an_org() -> None:
    spaced = "pk36 mezn 0102-0033-0044-1201"
    assert normalize_account(spaced) == IBAN
    assert blind_index(spaced, org_id="org_a") == blind_index(IBAN, org_id="org_a")
    assert blind_index(IBAN, org_id="org_a") != blind_index(IBAN, org_id="org_b")
    assert blind_index(IBAN, org_id="org_a") != blind_index(IBAN[:-1] + "2", org_id="org_a")


def test_mask() -> None:
    assert mask(IBAN) == "PK36 **** **** 1201"
    assert mask("0071190045213309") == "**** **** 3309"
    assert mask("123") == "***"


@pytest.mark.parametrize("key", ["", "not base64", "c2hvcnQ="])
def test_bad_key_is_a_configuration_error(settings, key: str) -> None:
    settings.FIELD_ENCRYPTION_KEY = key
    with pytest.raises(ImproperlyConfigured):
        encrypt(IBAN, org_id="org_a")
