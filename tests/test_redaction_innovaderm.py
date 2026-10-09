"""The redactor covers everything InnovaDerm's carátula redactor removed.

InnovaDerm removed, from every carátula: RFC, CURP, Mexican phone numbers,
email addresses (always, by pattern), and every occurrence of the patient's
names and policy number the operator supplied. Its privacy rules add the date
of birth and the address. Each of those is a test here, run through the same
detect → apply → residual-scan path the console uses.
"""

import pytest

from app.services.redaction import (
    Category,
    Confidence,
    clean_supplied_terms,
    redaction_engine,
)

CARATULA = """SEGUROS MONTERREY NEW YORK LIFE
Póliza: GMM-2024-88234
Nombre del asegurado: JUAN PÉREZ LÓPEZ
Fecha de nacimiento: 15/03/1985
Domicilio: Av. Insurgentes Sur 1234, Col. Del Valle
RFC: PEGJ850315HN2
CURP: PEGJ850315HDFRRN09
Teléfono: 55 1234 5678
Correo: juan.perez@gmail.com
Vigencia: 01/01/2026 al 01/01/2027
Deducible: $15,000.00 M.N.   Coaseguro: 10%
CLÁUSULA 3. El asegurado Juan Perez Lopez, titular de la póliza GMM-2024-88234, declara.
Contacto alterno 5598765432 o maria.lopez@hotmail.com, atendido por Mariana Gómez.
Firma: juan pérez lópez
"""


def _redact(text: str, **supplied) -> str:
    spans = [span for span in redaction_engine.detect(text, **supplied) if span.confidence != Confidence.LOW]
    return redaction_engine.apply(text, spans).text


@pytest.mark.parametrize(
    "identifier",
    [
        "PEGJ850315HN2",  # RFC, 13 characters — InnovaDerm's own pattern missed this shape
        "PEGJ850315HDFRRN09",  # CURP
        "55 1234 5678",  # phone, labelled
        "5598765432",  # phone, unlabelled 10 digits
        "juan.perez@gmail.com",  # email, labelled
        "maria.lopez@hotmail.com",  # email, unlabelled
        "15/03/1985",  # date of birth
        "Insurgentes Sur 1234",  # address
    ],
)
def test_pattern_identifiers_are_removed(identifier):
    assert identifier not in _redact(CARATULA)


def test_labelled_name_is_removed_everywhere_it_appears():
    redacted = _redact(CARATULA)
    for variant in ("JUAN PÉREZ LÓPEZ", "Juan Perez Lopez", "juan pérez lópez"):
        assert variant not in redacted
    # One person, one placeholder: coreference survives.
    assert redacted.count("[NOMBRE_1]") == 3


def test_labelled_policy_number_is_removed_everywhere_it_appears():
    redacted = _redact(CARATULA)
    assert "GMM-2024-88234" not in redacted
    assert redacted.count("[NUM_POLIZA_1]") == 2


def test_supplied_names_are_removed_even_unlabelled():
    """InnovaDerm's --names: a name with no label and no title."""
    assert "Mariana Gómez" in _redact(CARATULA)
    assert "Mariana Gómez" not in _redact(CARATULA, names=["Mariana Gomez"])


def test_supplied_policy_number_is_removed_even_unlabelled():
    text = "Referencia de trámite AX-99-12345 registrada en el sistema."
    assert "AX-99-12345" not in _redact(text, policy_numbers=["AX-99-12345"])


def test_money_percentages_and_vigencia_survive():
    redacted = _redact(CARATULA, names=["Juan Pérez López"])
    assert "$15,000.00 M.N." in redacted
    assert "10%" in redacted
    assert "01/01/2026" in redacted


def test_supplied_names_match_whole_words_only():
    spans = redaction_engine.detect("Juanita y Juan firmaron.", names=["Juan"])
    assert [span.text for span in spans if span.category == Category.NOMBRE] == ["Juan"]


def test_product_line_behind_a_policy_label_is_not_propagated():
    """ "Póliza: Gastos Médicos Individual" is a product, not a number to hunt for."""
    text = "Póliza: Gastos Médicos Individual\nEsta cobertura de Gastos Médicos Individual ampara..."
    spans = redaction_engine.detect(text)
    assert len([span for span in spans if span.category == Category.NUM_POLIZA]) == 1


def test_redacted_text_passes_the_gate_and_is_not_re_detected():
    redacted = _redact(CARATULA, names=["Mariana Gómez"])
    assert redaction_engine.residual_scan(redacted) == []
    assert [span for span in redaction_engine.detect(redacted) if span.category == Category.NOMBRE] == []


def test_supplied_terms_are_bounded():
    terms = clean_supplied_terms(["Juan Pérez, juan perez, J", "\n".join(f"Nombre {index}" for index in range(20))])
    assert terms[0] == "Juan Pérez"
    assert "juan perez" not in terms  # same name, folded
    assert "J" not in terms  # too short to search for safely
    assert len(terms) == 10
