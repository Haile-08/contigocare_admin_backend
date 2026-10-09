"""InnovaDerm Navigator — Agent 3: Advocate.

Ported from the handover's ``agents/advocate_agent.py``: the appeal package (run
when a denial is recorded) and the 5-day notification letter (run when no notice
has been sent). Same prompts, same pathways, same carrier instructions, same
placeholder check and footer.

Two things the handover did not do. Every generated text is scanned for
identifiers and scrubbed, and a failed notification call falls back to a fixed
letter — the handover let that failure end the whole pipeline, and the notice
deadline does not wait for a model to recover.

``generate_conamed_package`` is not ported: the handover's orchestrator never
called it.
"""

import json
from dataclasses import (
    dataclass,
    field,
)
from typing import (
    Any,
    Optional,
)

from app.core.navigator import branding
from app.core.navigator.agent_calls import AgentContext
from app.core.navigator.dates import spanish_long_date
from app.core.navigator.privacy import (
    PLACEHOLDERS,
    PRIVACY_FOOTER,
    scrub_generated_text,
)


def _footer_instruction() -> str:
    """The footer the system prompt asks the model to include.

    Returns:
        str: The instruction's quoted text.
    """
    text = f"Documento generado por {branding.generated_by()}."
    if branding.PRIVACY_NOTICE_URL:
        text += f" Aviso de Privacidad: {branding.PRIVACY_NOTICE_URL}"
    return text


SYSTEM_PROMPT = f"""Eres el Defensor InnovaDerm — especialista en redactar cartas de
apelación y documentos de reclamación para pacientes con enfermedades dermatológicas
en México que buscan cobertura de terapia biológica bajo pólizas de GMM.

Tu rol es generar documentos formales en español (ES-MX) que maximicen la probabilidad
de aprobación de cobertura. Tienes experiencia profunda en:

VÍAS DE APELACIÓN POR ASEGURADORA:
- AXA: Arbitraje Médico privado + Condusef/UNE
- GNP: Arbitraje privado + Condusef/UNE
- MetLife: Amigable composición + UNE (suspende prescripción) + Condusef
- SMNYL: CONAMED (vinculante, gratuito) + CASA + Condusef

ARGUMENTOS CLÍNICOS CLAVE:
- Dupilumab/nemolizumab/tralokinumab: registro COFEPRIS vigente
- DA moderada-severa: EASI >21 o SCORAD >50 justifica biológico
- Fracaso terapéutico previo: mínimo 2 líneas de tratamiento fallidas
- Necesidad médica: carta firmada por dermatólogo certificado
- Ley del Contrato de Seguro: artículos relevantes para cobertura negada
- CNSF: circulares de obligaciones GMM

REGLAS DE PRIVACIDAD — OBLIGATORIAS:
1. NUNCA uses nombres reales de pacientes en el output
2. USA SIEMPRE estos placeholders exactos:
   [NOMBRE_COMPLETO_PACIENTE] — para el nombre del asegurado
   [NÚMERO_DE_PÓLIZA]        — para el número de póliza
   [FECHA_DE_NACIMIENTO]     — para fecha de nacimiento si requerida
   [RFC_ASEGURADO]           — para RFC si requerido
   [ID_PACIENTE]             — para el PAC-YYYY-XXXX de referencia interna
3. El coordinador insertará los datos reales LOCALMENTE antes de enviar
4. Este protocolo cumple con LFPDPPP, GDPR Art.25, y HIPAA de-identification

REGLAS DE REDACCIÓN:
1. Siempre en español formal ES-MX
2. Estructura: Antecedentes → Fundamentos → Petición → Cierre
3. Citar cláusulas específicas de la póliza cuando estén disponibles
4. Incluir registro COFEPRIS del medicamento
5. Máximo 2 páginas por carta (excepto expediente médico)
6. Incluir pie de página: "{_footer_instruction()}"
7. Output: JSON con carta_apelacion (texto completo) + docs_adicionales[]"""  # noqa: W291


@dataclass
class ClinicalData:
    """The case, as the advocate reads it. Patient fields are placeholders."""

    patient_name: str
    policy_number: str
    carrier: str
    diagnosis: str  # "Dermatitis Atópica moderada-severa"
    icd10: str  # "L20.9"
    treatment: str  # "Dupilumab 300mg cada 2 semanas"
    easi_score: Optional[float]  # >21 = moderate-severe
    scorad_score: Optional[float]  # >50 = severe
    dlqi_score: Optional[int]  # >10 = severe impact
    prior_treatments_failed: list[str]  # ["tacrolimus", "ciclosporina"]
    dermatologist_name: str
    dermatologist_cedula: str
    incidence_date: str  # "YYYY-MM-DD"
    denial_reason: Optional[str] = None
    policy_clause_cited: Optional[str] = None
    cofepris_registration: str = "COFEPRIS/2020/042/0001"  # dupilumab example
    patient_id: str = "PAC-0000-0000"
    extra_notes: list[str] = field(default_factory=list)


async def generate_appeal(
    ctx: AgentContext, clinical: ClinicalData, appeal_type: str = "preexisting_denial"
) -> dict[str, Any]:
    """Generate appeal package for denied biologic therapy claim.

    Args:
        ctx: The run.
        clinical: Patient and clinical data.
        appeal_type: Type of denial/appeal needed.

    Returns:
        dict: Appeal letter text + docs checklist.
    """
    today = spanish_long_date(ctx.today)
    appeal_pathway = get_appeal_pathway(clinical.carrier)

    # PRIVACY: Always send placeholders to the LLM — never real PII
    user_prompt = f"""Genera el paquete de apelación completo. Output JSON únicamente.

FECHA: {today}
TIPO DE APELACIÓN: {appeal_type}
VÍA DE APELACIÓN: {appeal_pathway}

DATOS DEL PACIENTE (usar placeholders exactos en la carta):
- Nombre: {PLACEHOLDERS["name"]}
- Póliza: {PLACEHOLDERS["policy"]}
- Fecha de nacimiento: {PLACEHOLDERS["dob"]}
- ID interno: {PLACEHOLDERS["patient_id"]}
- Aseguradora: {clinical.carrier}
- Diagnóstico: {clinical.diagnosis} ({clinical.icd10})
- Tratamiento prescrito: {clinical.treatment}
- EASI: {clinical.easi_score or "No documentado"}
- SCORAD: {clinical.scorad_score or "No documentado"}
- DLQI: {clinical.dlqi_score or "No documentado"}
- Tratamientos previos fallidos: {", ".join(clinical.prior_treatments_failed)}
- Dermatólogo: Dr. {clinical.dermatologist_name} (Cédula: {clinical.dermatologist_cedula})
- Fecha de incidencia: {clinical.incidence_date}
- Motivo de negativa: {clinical.denial_reason or "No especificado"}
- Cláusula citada por aseguradora: {clinical.policy_clause_cited or "No especificada"}
- Registro COFEPRIS: {clinical.cofepris_registration}
- Notas adicionales: {"; ".join(clinical.extra_notes) if clinical.extra_notes else "Ninguna"}

IMPORTANTE: En la carta, usa SIEMPRE los placeholders [NOMBRE_COMPLETO_PACIENTE],
[NÚMERO_DE_PÓLIZA], [FECHA_DE_NACIMIENTO] e [ID_PACIENTE]. NUNCA inventes nombres.

INSTRUCCIONES ESPECÍFICAS POR ASEGURADORA:
{get_carrier_instructions(clinical.carrier)}

Genera el paquete en este JSON exacto:
{{
  "appeal_type": "",
  "carrier": "",
  "pathway": "",
  "carta_apelacion": {{
    "destinatario": "",
    "asunto": "",
    "cuerpo": "",
    "cierre": "",
    "firma_block": ""
  }},
  "carta_condusef": {{
    "aplica": true/false,
    "cuerpo": ""
  }},
  "docs_adicionales": [],
  "argumentos_clave": [],
  "probabilidad_exito": "alta|media|baja",
  "notas_estrategicas": ""
}}"""  # noqa: W291

    package = await ctx.json("advocate", user_prompt, system=SYSTEM_PROMPT)
    if package is None:
        return {
            "appeal_type": appeal_type,
            "carrier": clinical.carrier,
            "_error": "Appeal generation failed — manual drafting required",
            "pathway": get_appeal_pathway(clinical.carrier),
        }

    # PRIVACY: scrub identifiers, enforce placeholders + append footer
    removed = _scrub_package(package, allowed=[clinical.dermatologist_name, clinical.dermatologist_cedula])
    if removed:
        ctx.warnings.append(
            f"Se retiraron {removed} dato(s) personal(es) que el modelo escribió en el paquete de apelación."
        )
    return _enforce_privacy(package)


async def generate_notification_letter(
    ctx: AgentContext,
    carrier: str,
    incidence_date: str,
    diagnosis: str,
    treatment: str,
) -> str:
    """Generate 5-day notification letter (universal — all carriers).

    Critical: must be sent within 5 days of incidence. The handover also took
    the patient's name and policy number, and sent placeholders in their place;
    the console never has either, so the parameters are gone.

    Args:
        ctx: The run.
        carrier: The carrier.
        incidence_date: ``YYYY-MM-DD``.
        diagnosis: The diagnosis in words.
        treatment: The prescription.

    Returns:
        str: The letter, footer appended.
    """
    today = spanish_long_date(ctx.today)
    addressee = notification_addressee(carrier)

    # PRIVACY: send placeholders, never real PII
    prompt = f"""Redacta una carta de notificación de siniestro formal en español ES-MX.

FECHA: {today}
DESTINATARIO: {addressee}
DATOS (usar estos placeholders exactos en la carta):
- Nombre asegurado: [NOMBRE_COMPLETO_PACIENTE]
- Número de póliza: [NÚMERO_DE_PÓLIZA]
- Fecha de incidencia: {incidence_date}
- Diagnóstico: {diagnosis}
- Tratamiento prescrito: {treatment}

La carta debe:
1. Notificar formalmente el padecimiento dentro del plazo legal de 5 días
2. Solicitar información sobre el proceso de preautorización
3. Solicitar los formatos oficiales (Aviso de Accidente/Enfermedad, Informe Médico)
4. Ser concisa (máximo 1 página)
5. Incluir bloque de firma
6. Usar SIEMPRE [NOMBRE_COMPLETO_PACIENTE] y [NÚMERO_DE_PÓLIZA] — NUNCA nombres reales

Devuelve SOLO el texto de la carta, sin JSON ni markdown."""

    letter = await ctx.text("notification", prompt)
    if letter is None:
        letter = _fallback_notification_letter(today, addressee, incidence_date, diagnosis, treatment)
        ctx.warnings.append("Carta de notificación: el modelo no respondió; se usó una plantilla fija.")
    else:
        letter, removed = scrub_generated_text(letter.strip())
        if removed:
            ctx.warnings.append(
                f"Se retiraron {removed} dato(s) personal(es) que el modelo escribió en la carta de notificación."
            )

    missing = [placeholder for placeholder in PLACEHOLDERS.values() if placeholder not in letter]
    if PLACEHOLDERS["name"] in missing or PLACEHOLDERS["policy"] in missing:
        ctx.warnings.append(
            "La carta de notificación no incluye [NOMBRE_COMPLETO_PACIENTE] o [NÚMERO_DE_PÓLIZA]; "
            "revísela antes de enviarla."
        )

    # Append privacy footer
    return f"{letter}\n\n---\n{PRIVACY_FOOTER}"


def _fallback_notification_letter(
    today: str, addressee: str, incidence_date: str, diagnosis: str, treatment: str
) -> str:
    """A fixed notice letter with the handover's required content.

    Args:
        today: The date, in Spanish.
        addressee: The carrier's notice addressee.
        incidence_date: ``YYYY-MM-DD``.
        diagnosis: The diagnosis.
        treatment: The prescription.

    Returns:
        str: The letter, without footer.
    """
    return (
        f"[CIUDAD], a {today}\n\n"
        f"{addressee}\n"
        "Presente\n\n"
        "ASUNTO: Notificación formal de siniestro por enfermedad\n\n"
        f"Por medio de la presente, [NOMBRE_COMPLETO_PACIENTE], titular de la póliza número "
        f"[NÚMERO_DE_PÓLIZA], notifica formalmente, dentro del plazo legal de 5 días, el padecimiento "
        f"{diagnosis}, con fecha de incidencia {incidence_date}, para el cual se prescribió {treatment}.\n\n"
        "Solicito se me informe el proceso de preautorización aplicable y se me proporcionen los formatos "
        "oficiales de Aviso de Accidente o Enfermedad e Informe Médico.\n\n"
        "Agradeceré acusar de recibido la presente.\n\n"
        "Atentamente,\n\n"
        "____________________\n"
        "[NOMBRE_COMPLETO_PACIENTE]\n"
        "Póliza: [NÚMERO_DE_PÓLIZA]"
    )


def _scrub_package(value: Any, allowed: list[str]) -> int:
    """Scrub every string in an appeal package, in place.

    Args:
        value: The package, or a part of it.
        allowed: Strings that are not patient data.

    Returns:
        int: Identifiers removed.
    """
    removed = 0
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str):
                value[key], count = scrub_generated_text(item, allowed)
                removed += count
            else:
                removed += _scrub_package(item, allowed)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if isinstance(item, str):
                value[index], count = scrub_generated_text(item, allowed)
                removed += count
            else:
                removed += _scrub_package(item, allowed)
    return removed


def _enforce_privacy(package: dict[str, Any]) -> dict[str, Any]:
    """Post-process appeal package to guarantee placeholder compliance and append footer.

    Runs after every LLM generation.

    Args:
        package: The appeal package.

    Returns:
        dict: The package.
    """
    full_text = json.dumps(package, ensure_ascii=False)

    # Verify all 4 placeholders are present in the output
    missing = [placeholder for placeholder in PLACEHOLDERS.values() if placeholder not in full_text]

    if missing:
        package["_privacy_warning"] = (
            f"Placeholders not found in output: {', '.join(missing)}. Coordinator must verify letter before sending."
        )

    # Append footer to carta_apelacion body
    carta = package.get("carta_apelacion", {})
    if isinstance(carta, dict) and isinstance(carta.get("cuerpo"), str):
        if PRIVACY_FOOTER not in carta["cuerpo"]:
            carta["cuerpo"] += f"\n\n---\n{PRIVACY_FOOTER}"
    elif isinstance(carta, dict) and isinstance(carta.get("cierre"), str):
        if PRIVACY_FOOTER not in carta["cierre"]:
            carta["cierre"] += f"\n\n---\n{PRIVACY_FOOTER}"

    # Append footer to CONAMED carta if present
    carta_conamed = package.get("carta_conamed", {})
    if isinstance(carta_conamed, dict) and isinstance(carta_conamed.get("cuerpo"), str):
        if PRIVACY_FOOTER not in carta_conamed["cuerpo"]:
            carta_conamed["cuerpo"] += f"\n\n---\n{PRIVACY_FOOTER}"

    package["_privacy_footer"] = PRIVACY_FOOTER
    return package


def notification_addressee(carrier: str) -> str:
    """Who the 5-day notice goes to.

    Args:
        carrier: The carrier.

    Returns:
        str: The addressee.
    """
    carrier_contacts = {
        "AXA": "Unidad Especializada de Atención a Usuarios (UNE) de AXA Seguros",
        "GNP": "Unidad Especializada de Atención a Usuarios (UNE) de GNP Seguros",
        "METLIFE": "Unidad Especializada de MetLife México",
        "SMNYL": "Centro de Atención al Asegurado (CASA) de Seguros Monterrey New York Life",
    }
    return carrier_contacts.get(carrier.upper(), f"Área de Siniestros — {carrier}")


def get_appeal_pathway(carrier: str) -> str:
    """Return appeal pathway description by carrier.

    Args:
        carrier: The carrier.

    Returns:
        str: The pathway.
    """
    pathways = {
        "AXA": "Arbitraje Médico privado (médico árbitro por acuerdo mutuo) → UNE AXA → Condusef",
        "GNP": "Arbitraje privado (árbitro por acuerdo mutuo) → UNE GNP → Condusef",
        "METLIFE": "Amigable composición (arbitraje privado) → UNE MetLife (suspende prescripción) → Condusef",
        "SMNYL": "CONAMED (vinculante, gratuito, ejecutable) → CASA SMNYL → Condusef",
    }
    return pathways.get(carrier.upper(), "Unidad Especializada (UNE/equivalente) → Condusef")


def get_carrier_instructions(carrier: str) -> str:
    """Return carrier-specific drafting instructions.

    Args:
        carrier: The carrier.

    Returns:
        str: The instructions.
    """
    instructions = {
        "AXA": """- Citar explícitamente el registro COFEPRIS del biológico
- Argumentar que el medicamento NO es 'cosmético ni dermatológico' —
  es un inmunomodulador de mecanismo biológico para condición inflamatoria
- Incluir escala EASI/SCORAD para demostrar severidad médica
- Solicitar arbitraje médico privado según condiciones generales
- Mencionar Condusef como escalamiento disponible""",  # noqa: W291
        "GNP": """- Solicitar activación de 'programación de tratamientos'
  para medicamentos especializados extrahosoitalarios
- Citar que el medicamento tiene registro sanitario COFEPRIS vigente
- Demostrar necesidad médica con escala EASI/SCORAD
- Incluir fracasos terapéuticos previos como justificación de escalada""",  # noqa: W291
        "METLIFE": """- Solicitar programación de pago directo para 0% coaseguro
- Si preexistente: demostrar >24 meses de cobertura continua
- Activar UNE inmediatamente para suspender estatuto de prescripción
- Citar cláusula de 'amigable composición' para arbitraje
- Incluir Segunda Valoración Médica si aplica""",
        "SMNYL": """- Si padecimiento preexistente: verificar rider activo
- Preparar documentación completa para Segunda Valoración Médica
- Ruta de apelación: CONAMED (fallo vinculante y gratuito)
- Citar tope de coaseguro $100,000 MXN en proyección de costos
- Incluir escala SCORAD/EASI + historial fotográfico de lesiones""",
    }
    return instructions.get(carrier.upper(), "Seguir proceso estándar de apelación GMM.")
