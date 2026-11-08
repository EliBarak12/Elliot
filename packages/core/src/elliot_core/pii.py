"""Recognise fields that hold secrets or personal data, by name.

One classifier for discovery (which columns of a new source are personal),
the linter (which tools hand them to agents) and the builders that draft
tools (which never project them by default). Names are normalised first, so
``reviewerEmail``, ``reviewer_email`` and ``revieweremail`` all match.

Two kinds:

- ``secret`` — credentials and financial or government identifiers
  (password, token, SSN, card number, IBAN, wallet). A connector should never
  return these.
- ``personal`` — contact and identity data about a person (email, phone,
  street address, birth date, IP address). Sometimes a tool needs one; it
  should be a deliberate choice.
"""

from __future__ import annotations

import re
from typing import Literal

PiiKind = Literal["secret", "personal"]

_SECRET = re.compile(
    r"(password|passwd|passcode|secret|accesstoken|refreshtoken|authtoken|apitoken|"
    r"sessiontoken|bearertoken|^token$|apikey|privatekey|ssn|socialsecurity|iban|"
    r"cardnumber|creditcard|cvv|cvc|cryptowallet|walletaddress|routingnumber|"
    r"accountnumber|taxid|passport|nationalid|licensenumber|^ein$)"
)
_PERSONAL = re.compile(
    r"(email|phone|mobile|telephone|birthdate|dateofbirth|^dob$|birthday|"
    r"ipaddress|^ip$|macaddress|streetaddress|^address$|homeaddress|postalcode|"
    r"zipcode|^zip$|maidenname|^ssn)"
)


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.split(".")[-1].lower())


def classify_field(name: str) -> PiiKind | None:
    """``"secret"``, ``"personal"`` or None for a field name."""
    key = _normalise(name)
    if not key:
        return None
    if _SECRET.search(key):
        return "secret"
    if _PERSONAL.search(key):
        return "personal"
    return None


def sensitive_fields(names: list[str]) -> list[dict[str, str]]:
    """The fields among ``names`` that hold secrets or personal data."""
    out: list[dict[str, str]] = []
    for name in names:
        kind = classify_field(name)
        if kind is not None:
            out.append({"name": name, "kind": kind})
    return out
