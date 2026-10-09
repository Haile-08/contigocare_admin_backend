"""Calendar helpers the agents share.

FIX (30-day months): the handover stepped through the year in 30-day blocks —
``start + timedelta(days=30 * m)`` — so twelve "months" ended five days short of
a year and two consecutive months could carry the same label. Months here are
calendar months.
"""

import calendar
from datetime import date

_SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def add_months(start: date, months: int) -> date:
    """Add calendar months, clamping to the last day of a short month.

    Args:
        start: The anchor date.
        months: Months to add.

    Returns:
        date: The resulting date.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def spanish_long_date(day: date) -> str:
    """``22 de mayo de 2026``.

    The handover wrote ``strftime("%d de %B de %Y")``, which prints the month in
    English on a server without a Spanish locale.

    Args:
        day: The date.

    Returns:
        str: The date in Spanish.
    """
    return f"{day.day:02d} de {_SPANISH_MONTHS[day.month - 1]} de {day.year}"
