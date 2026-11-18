"""Compare pylinac results with TG-51 Excel worksheets.

The numbers in tests/data/excel_references.json are the cached results from
clinical workbooks. Re-run this file after a pylinac upgrade.

Ptp, Pion, Ppol, corrected M, %dd(10)x, R50, dref, Pq_gr, and the electron
doses use the same equations as the worksheets, so they must agree.

Photon kQ on older sheets is a Table I value typed to about 3 decimals.
pylinac uses the TG-51 polynomial instead. The dose must still follow that
kQ: changing only kQ has to change the dose by the same fraction. A move of
more than 0.0015 in kQ fails, which is wider than the table rounding seen on
these sheets and tight enough to catch a different kQ fit.
"""

from __future__ import annotations

import json
from pathlib import Path

import pylinac
import pytest

from tg51app.calc import calculate
from tg51app.models import CalibrationCase, Chamber, Energy

REFERENCES = json.loads((Path(__file__).parent / "data" / "excel_references.json").read_text(encoding="utf-8"))

# Wider than the 3-decimal Table I values on the older worksheets.
PHOTON_KQ_ABS = 0.0015
SAME_EQUATION = 1e-9

EXACT_KEYS = (
    "p_tp",
    "p_ion",
    "p_pol",
    "m_corrected",
    "pddx",
    "r_50",
    "dref",
    "pq_gr",
    "dose_mu_dref",
    "dose_mu_dmax",
    "dose_mu_dmax_adjusted",
)
PHOTON_DOSE_KEYS = ("dose_mu_10", "dose_mu_dmax", "dose_mu_dmax_adjusted")


def _run(reference: dict):
    measurement = dict(reference["measurement"])
    measurement.update(id="reference", machine_id="machine", energy_id="energy")
    case = CalibrationCase.from_dict(measurement)
    energy = Energy(
        id="energy",
        modality=reference["modality"],
        nominal=float(reference["nominal"]),
        fff=bool(reference["fff"]),
    )
    chamber = Chamber(
        id="chamber",
        name="PTW 30013",
        model=reference["chamber_model"],
        k_ecal=reference["k_ecal"],
    )
    return calculate(
        case,
        institution="reference",
        physicist="reference",
        unit=reference["name"],
        energy=energy,
        chamber=chamber,
    )


@pytest.mark.parametrize("reference", REFERENCES["cases"], ids=lambda item: item["name"])
def test_app_matches_the_excel_worksheet(reference):
    outcome = _run(reference)
    assert outcome.errors == [], outcome.errors
    result = outcome.result
    excel = reference["excel"]
    where = f"{reference['name']} ({reference['workbook']} {reference['sheet']}, pylinac {pylinac.__version__})"

    if reference["modality"] == "photon":
        assert result["kq"] == pytest.approx(excel["kq"], abs=PHOTON_KQ_ABS), where
        scale = result["kq"] / excel["kq"]
        for key in PHOTON_DOSE_KEYS:
            if key not in excel:
                continue
            assert result[key] == pytest.approx(excel[key] * scale, rel=1e-9, abs=1e-12), f"{where} {key}"
        exact = [key for key in EXACT_KEYS if key in excel and key not in PHOTON_DOSE_KEYS]
    else:
        exact = [key for key in EXACT_KEYS if key in excel]

    for key in exact:
        assert result[key] == pytest.approx(excel[key], abs=SAME_EQUATION), f"{where} {key}"
