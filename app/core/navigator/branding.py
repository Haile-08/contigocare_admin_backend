"""Who the generated documents say produced them.

The handover printed InnovaSalud's name, tagline, privacy-notice URL and ARCO
mailbox on every letter, report and cover sheet. Those lines are statements
about who processed the patient's data and where to exercise ARCO rights, so on
documents this console generates they have to name the organisation running
it. Everything else about the documents — sections, wording, colours — is the
handover's.

A value left empty is omitted from the document rather than printed blank.
"""

PRODUCT_NAME = "InnovaDerm Navigator"
ORGANIZATION = "karai.health"
TAGLINE = ""
PRIVACY_NOTICE_URL = ""
ARCO_EMAIL = ""
CONTACT_EMAIL = ""

# The report file name: ``InnovaDerm-PAC-2026-0001-MetLife-<run>.pdf``.
FILE_PREFIX = "InnovaDerm"


def generated_by() -> str:
    """``InnovaDerm Navigator — karai.health``.

    Returns:
        str: The product and the organisation.
    """
    return f"{PRODUCT_NAME} — {ORGANIZATION}"
