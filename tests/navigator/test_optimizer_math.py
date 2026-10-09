"""The optimizer's arithmetic: the handover's projection, with its four defects fixed."""

import asyncio
from datetime import date

from app.core.navigator.optimizer_agent import (
    build_treatment,
    calculate_monthly_projections,
    calculate_no_optimization_cost,
    generate_financial_roadmap,
)
from tests.navigator.helpers import (
    STRATEGY,
    context,
    scripted,
)

START = date(2025, 12, 31)


def test_fix_negative_payments_deducible_is_consumed_by_claims():
    # The handover's saved MetLife run: $86,000 deducible, Nemluvio at $30,000
    # a dose, which produced carrier_pays of −$56,000 in month one.
    treatment = build_treatment("nemolizumab", START)
    rows = calculate_monthly_projections(treatment, 86000, 10, 25300, None, START)

    assert all(row["carrier_pays_mxn"] >= 0 for row in rows)
    assert all(row["coaseguro_mxn"] >= 0 for row in rows)
    assert sum(row["deducible_mxn"] for row in rows) == 86000
    # Month one: a 60 mg loading dose (two units) plus the day-28 dose.
    assert rows[0]["drug_cost_mxn"] == 90000
    assert rows[0]["deducible_mxn"] == 86000
    assert rows[0]["coaseguro_mxn"] == 400  # 10% of the $4,000 left after the deducible


def test_fix_loading_dose_units():
    nemluvio = calculate_monthly_projections(build_treatment("nemolizumab", START), 0, 10, 10**9, None, START)
    dupixent_start = date(2026, 1, 15)
    dupixent = calculate_monthly_projections(
        build_treatment("dupilumab", dupixent_start), 0, 10, 10**9, None, dupixent_start
    )

    # Nemluvio's day-0 administration is 60 mg: two 30 mg units.
    assert nemluvio[0]["doses"] == 2  # loading + day 28
    assert nemluvio[0]["drug_cost_mxn"] == 90000
    # Dupixent: two 300 mg syringes on day 0, then day 14 and day 28 fall inside the calendar month.
    assert dupixent[0]["doses"] == 4
    assert dupixent[0]["drug_cost_mxn"] == 4 * 19000


def test_fix_calendar_months():
    rows = calculate_monthly_projections(build_treatment("dupilumab", START), 15000, 10, 25300, None, START)
    labels = [row["date"] for row in rows]
    assert labels == [
        "2025-12",
        "2026-01",
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
        "2026-10",
        "2026-11",
    ]
    assert len(set(labels)) == 12


def test_tope_caps_cumulative_coaseguro():
    rows = calculate_monthly_projections(build_treatment("dupilumab", START), 15000, 10, 25300, None, START)
    assert max(row["coaseguro_cumulative_mxn"] for row in rows) == 25300
    reached = [row for row in rows if row["tope_reached"]]
    assert reached and all(row["coaseguro_mxn"] == 0 for row in rows[rows.index(reached[0]) + 1 :])


def test_no_optimization_cost_matches_the_projection_at_the_policy_rate():
    treatment = build_treatment("dupilumab", START)
    rows = calculate_monthly_projections(treatment, 15000, 10, 25300, None, START)
    assert calculate_no_optimization_cost(treatment, 10, 25300, 15000, START) == round(
        sum(row["patient_net_mxn"] for row in rows), 2
    )


def test_fix_metlife_zero_coaseguro_only_with_programacion(monkeypatch):
    scripted(monkeypatch, {"optimizer": STRATEGY})
    policy = {"financial": {"tope_coaseguro": None}}

    without = asyncio.run(
        generate_financial_roadmap(
            context(), policy, "PAC-1", "MetLife", "dupilumab", 28, 15000, 10, 25300, START, programacion_done=False
        )
    )
    with_programacion = asyncio.run(
        generate_financial_roadmap(
            context(), policy, "PAC-1", "MetLife", "dupilumab", 28, 15000, 10, 25300, START, programacion_done=True
        )
    )

    assert without["financial_summary"]["coaseguro_pct"] == 10
    assert without["financial_summary"]["savings_from_optimization_mxn"] == 0
    assert with_programacion["financial_summary"]["coaseguro_pct"] == 0
    assert with_programacion["financial_summary"]["patient_cost_annual_mxn"] == 15000
    assert with_programacion["financial_summary"]["savings_from_optimization_mxn"] == 25300


def test_tope_resolution_operator_then_policy_then_carrier_default(monkeypatch):
    scripted(monkeypatch, {"optimizer": STRATEGY})

    def tope(policy, given, carrier):
        roadmap = asyncio.run(
            generate_financial_roadmap(context(), policy, "PAC-1", carrier, "dupilumab", 1, 15000, 10, given, START)
        )
        return roadmap["financial_summary"]["tope_coaseguro"]

    assert tope({"financial": {"tope_coaseguro": 50000}}, 40000, "GNP") == 40000
    assert tope({"financial": {"tope_coaseguro": 50000}}, None, "GNP") == 50000
    assert tope({"financial": {"tope_coaseguro": "ver carátula"}}, None, "SMNYL") == 100000
    assert tope({}, None, "Zurich") == 30000


def test_roadmap_keeps_the_handover_keys_and_the_strategy(monkeypatch):
    model = scripted(monkeypatch, {"optimizer": STRATEGY})
    roadmap = asyncio.run(
        generate_financial_roadmap(context(), {}, "PAC-1", "MetLife", "dupilumab", 28, 15000, 10, 25300, START)
    )
    assert set(roadmap["financial_summary"]) >= {
        "deducible",
        "deducible_paid",
        "coaseguro_pct",
        "coaseguro_pct_without_optimization",
        "tope_coaseguro",
        "tope_reached_month",
        "tope_reached_date",
        "months_remaining_free",
        "drug_cost_annual_mxn",
        "patient_cost_annual_mxn",
        "carrier_cost_annual_mxn",
        "psp_bridge_annual_mxn",
        "cost_without_optimization_mxn",
        "savings_from_optimization_mxn",
    }
    assert roadmap["utilization_score"] == 60
    assert "12-MONTH PROJECTIONS:" in model.calls[0]["prompt"]
    assert '"tope_coaseguro_range": [12650, 63250]' in model.calls[0]["prompt"]


def test_failed_optimizer_uses_the_handover_fallback(monkeypatch):
    scripted(monkeypatch, {"optimizer": None})
    ctx = context()
    roadmap = asyncio.run(
        generate_financial_roadmap(ctx, {}, "PAC-1", "GNP", "dupilumab", 28, 15000, 10, 25300, START)
    )
    assert roadmap["utilization_score"] == 50
    assert ctx.degraded_agents == ["optimizer"]
