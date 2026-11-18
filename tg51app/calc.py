"""Run pylinac TG-51 on a calibration case."""

from __future__ import annotations

import math
from dataclasses import dataclass

import pylinac
from pylinac.calibration import tg51

from .models import CalibrationCase, Chamber, Energy

TEMP_MIN = 17.0
TEMP_MAX = 27.0
PRESS_MIN = 91.0
PRESS_MAX = 111.0


@dataclass
class CalcOutcome:
    errors: list[str]
    warnings: list[str]
    result: dict | None
    pylinac_version: str
    calculator: object | None = None


def temperature_celsius(value: float, unit: str) -> float:
    if str(unit).strip().upper() == "F":
        return float(tg51.fahrenheit2celsius(value))
    return float(value)


def pressure_kpa(value: float, unit: str) -> float:
    key = str(unit).strip().lower()
    if key == "mmhg":
        return float(tg51.mmHg2kPa(value))
    if key == "mbar":
        return float(tg51.mbar2kPa(value))
    return float(value)


def ptp_value(temp_c: float, press_kpa_value: float) -> float:
    return ((273.2 + temp_c) / 295.2) * (101.33 / press_kpa_value)


def ptp_text(temp_c: float, press_kpa_value: float) -> str:
    """Ptp written with the °C and kPa numbers that enter the correction."""
    added = 273.2 + temp_c
    temp_factor = added / 295.2
    press_factor = 101.33 / press_kpa_value
    value = ptp_value(temp_c, press_kpa_value)
    return (
        f"Ptp: {value:.4f}\n"
        f"273.2 + {temp_c:.2f} °C = {added:.2f}\n"
        f"{added:.2f} / 295.2 = {temp_factor:.6f}\n"
        f"101.33 / {press_kpa_value:.4f} kPa = {press_factor:.6f}\n"
        f"{temp_factor:.6f} × {press_factor:.6f} = {value:.4f}"
    )


def _shown(value: float) -> str:
    return format(float(value), ".6g")


def _photon_pddx(pdd: float, energy: int, lead_foil: str | None) -> tuple[float, list[str]]:
    """PDD(10)x and the arithmetic that produced it. Matches pylinac's pddx."""
    foil = (lead_foil or "none").strip().lower()
    if energy < 10:
        return pdd, [f"PDD(10)x = {_shown(pdd)}"]
    if foil in ("", "none"):
        if pdd <= 75:
            return pdd, [f"PDD(10)x = {_shown(pdd)}"]
        quality = 1.267 * pdd - 20
        return quality, [
            f"1.267 × {_shown(pdd)} − 20 = {_shown(quality)}",
            f"PDD(10)x = {_shown(quality)}",
        ]
    if foil == "50cm":
        if pdd < 73:
            return pdd, [f"PDD(10)x = {_shown(pdd)}"]
        factor = 0.8905 + 0.0015 * pdd
        quality = factor * pdd
        return quality, [
            f"0.8905 + 0.0015 × {_shown(pdd)} = {_shown(factor)}",
            f"{_shown(factor)} × {_shown(pdd)} = {_shown(quality)}",
            f"PDD(10)x = {_shown(quality)}",
        ]
    if foil == "30cm":
        if pdd < 71:
            return pdd, [f"PDD(10)x = {_shown(pdd)}"]
        factor = 0.8116 + 0.00264 * pdd
        quality = factor * pdd
        return quality, [
            f"0.8116 + 0.00264 × {_shown(pdd)} = {_shown(factor)}",
            f"{_shown(factor)} × {_shown(pdd)} = {_shown(quality)}",
            f"PDD(10)x = {_shown(quality)}",
        ]
    return pdd, [f"PDD(10)x = {_shown(pdd)}"]


def _sum_line(*parts: float) -> str:
    text = _shown(parts[0])
    for part in parts[1:]:
        text += f" − {_shown(abs(part))}" if part < 0 else f" + {_shown(part)}"
    return text


def kq_text(*, pdd: float, energy: int, lead_foil: str | None, a: float, b: float, c: float) -> str:
    """kQ written with the PDD(10)x and chamber coefficients that enter it."""
    quality, steps = _photon_pddx(pdd, energy, lead_foil)
    b_term = b * 10**-3 * quality
    c_term = c * 10**-5 * quality**2
    value = a + b_term + c_term
    lines = [
        f"kQ: {value:.5f}",
        *steps,
        f"{_shown(b)} × 0.001 × {_shown(quality)} = {_shown(b_term)}",
        f"{_shown(c)} × 0.00001 × {_shown(quality**2)} = {_shown(c_term)}",
        f"{_sum_line(a, b_term, c_term)} = {value:.5f}",
    ]
    return "\n".join(lines)


def photon_kq_text(chamber: Chamber, *, pdd: float, energy: int, lead_foil: str | None) -> str | None:
    try:
        resolved = resolve_chamber(chamber)
    except ValueError:
        return None
    coef = resolved.photon_coefficients
    if coef is None:
        return None
    return kq_text(
        pdd=pdd,
        energy=energy,
        lead_foil=lead_foil,
        a=float(coef.a),
        b=float(coef.b),
        c=float(coef.c),
    )


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def readings_correction_text(
    *,
    m_reference: list[float],
    m_opposite: list[float],
    m_reduced: list[float],
    voltage_reference: float,
    voltage_reduced: float,
    p_tp: float | None,
    p_elec: float | None,
) -> str:
    """Pion, Ppol, and M corrected written with the averages and voltages used."""
    mref = _mean(m_reference)
    mopp = _mean(m_opposite)
    mred = _mean(m_reduced)
    sections: list[str] = []

    pion = None
    if mref is not None and mred not in (None, 0) and voltage_reduced != 0:
        voltage_ratio = voltage_reference / voltage_reduced
        reading_ratio = mref / mred
        denominator = reading_ratio - voltage_ratio
        if denominator != 0:
            pion = (1 - voltage_ratio) / denominator
            sections.append(
                "\n".join(
                    [
                        f"Pion: {pion:.4f}",
                        f"{_shown(voltage_reference)} / {_shown(voltage_reduced)} = {_shown(voltage_ratio)}",
                        f"{_shown(mref)} / {_shown(mred)} = {_shown(reading_ratio)}",
                        (
                            f"(1 − {_shown(voltage_ratio)}) / "
                            f"({_shown(reading_ratio)} − {_shown(voltage_ratio)}) = {pion:.4f}"
                        ),
                    ]
                )
            )
    if pion is None:
        sections.append("Pion")

    ppol = None
    if mref not in (None, 0) and mopp is not None:
        numerator = abs(mref) + abs(mopp)
        denominator = abs(2 * mref)
        ppol = numerator / denominator
        lines = [f"Ppol: {ppol:.4f}"]
        if mref < 0 or mopp < 0:
            lines.append(f"|{_shown(mref)}| = {_shown(abs(mref))}")
            lines.append(f"|{_shown(mopp)}| = {_shown(abs(mopp))}")
        lines.append(f"{_shown(abs(mref))} + {_shown(abs(mopp))} = {_shown(numerator)}")
        lines.append(f"|2 × {_shown(mref)}| = {_shown(denominator)}")
        lines.append(f"{_shown(numerator)} / {_shown(denominator)} = {ppol:.4f}")
        sections.append("\n".join(lines))
    else:
        sections.append("Ppol")

    if None not in (pion, ppol, p_tp, p_elec, mref):
        corrected = pion * p_tp * p_elec * ppol * mref
        sections.append(
            "\n".join(
                [
                    f"M corrected: {corrected:.3f} [nC]",
                    (
                        f"Pion {_shown(pion)} × Ptp {_shown(p_tp)} × P_elec {_shown(p_elec)} × "
                        f"Ppol {_shown(ppol)} × {_shown(mref)} = {corrected:.3f}"
                    ),
                ]
            )
        )
    else:
        sections.append("M corrected")
    return "\n\n".join(sections)


def _correction_factor(
    *,
    m_reference: list[float],
    m_opposite: list[float],
    m_reduced: list[float],
    voltage_reference: float,
    voltage_reduced: float,
    p_tp: float | None,
    p_elec: float | None,
) -> float | None:
    """Pion × Ptp × P_elec × Ppol. Polarity and ion recombination stay on the pre-calibration readings."""
    mref = _mean(m_reference)
    mopp = _mean(m_opposite)
    mred = _mean(m_reduced)
    pion = None
    if mref is not None and mred not in (None, 0) and voltage_reduced != 0:
        voltage_ratio = voltage_reference / voltage_reduced
        denominator = mref / mred - voltage_ratio
        if denominator != 0:
            pion = (1 - voltage_ratio) / denominator
    ppol = None
    if mref not in (None, 0) and mopp is not None:
        ppol = (abs(mref) + abs(mopp)) / abs(2 * mref)
    if None in (pion, ppol, p_tp, p_elec):
        return None
    return pion * p_tp * p_elec * ppol


def m_corrected_value(
    *,
    m_reference: list[float],
    m_opposite: list[float],
    m_reduced: list[float],
    voltage_reference: float,
    voltage_reduced: float,
    p_tp: float | None,
    p_elec: float | None,
) -> float | None:
    factor = _correction_factor(
        m_reference=m_reference,
        m_opposite=m_opposite,
        m_reduced=m_reduced,
        voltage_reference=voltage_reference,
        voltage_reduced=voltage_reduced,
        p_tp=p_tp,
        p_elec=p_elec,
    )
    mref = _mean(m_reference)
    if factor is None or mref is None:
        return None
    return factor * mref


def m_adjusted_corrected_value(
    *,
    m_reference: list[float],
    m_opposite: list[float],
    m_reduced: list[float],
    m_adjusted: list[float],
    voltage_reference: float,
    voltage_reduced: float,
    p_tp: float | None,
    p_elec: float | None,
) -> float | None:
    """Corrected post-calibration reading. Pion and Ppol still come from the pre-calibration readings."""
    factor = _correction_factor(
        m_reference=m_reference,
        m_opposite=m_opposite,
        m_reduced=m_reduced,
        voltage_reference=voltage_reference,
        voltage_reduced=voltage_reduced,
        p_tp=p_tp,
        p_elec=p_elec,
    )
    adjusted = _mean(m_adjusted)
    if factor is None or adjusted is None:
        return None
    return factor * adjusted


def photon_kq_value(chamber: Chamber, *, pdd: float, energy: int, lead_foil: str | None) -> float | None:
    try:
        resolved = resolve_chamber(chamber)
    except ValueError:
        return None
    coef = resolved.photon_coefficients
    if coef is None:
        return None
    quality, _steps = _photon_pddx(pdd, energy, lead_foil)
    return float(coef.a) + float(coef.b) * 10**-3 * quality + float(coef.c) * 10**-5 * quality**2


def photon_dose_text(
    *,
    tissue: float,
    m_corrected: float,
    kq: float,
    n_dw: float,
    mu: float,
    clinical_pdd10: float,
    adjusted: bool = False,
) -> str:
    """Dose at 10 cm and at dmax for the measurement MU, written with the numbers that enter them."""
    suffix = ", adjusted" if adjusted else ""
    depth_name = f"Dose at 10 [cm]{suffix}"
    dmax_name = f"Dose at dmax{suffix}"
    if mu == 0 or clinical_pdd10 == 0:
        return f"{depth_name}\n\n{dmax_name}"
    dose_10 = tissue * m_corrected * kq * n_dw
    fraction = clinical_pdd10 / 100
    dose_dmax = dose_10 / fraction
    reading_name = "M adjusted" if adjusted else "M corrected"
    return "\n\n".join(
        [
            "\n".join(
                [
                    f"{depth_name}: {dose_10:.4f} [cGy]",
                    (
                        f"tissue {_shown(tissue)} × {reading_name} {_shown(m_corrected)} × "
                        f"kQ {_shown(kq)} × NDw {_shown(n_dw)} = {dose_10:.4f}"
                    ),
                ]
            ),
            "\n".join(
                [
                    f"{dmax_name}: {dose_dmax:.4f} [cGy]",
                    f"{_shown(clinical_pdd10)} / 100 = {_shown(fraction)}",
                    f"{_shown(dose_10)} / {_shown(fraction)} = {dose_dmax:.4f}",
                ]
            ),
        ]
    )


def _r50(i_50: float) -> float:
    if i_50 < 10:
        return 1.029 * i_50 - 0.06
    return 1.59 * i_50 - 0.37


def electron_dref(i_50: float) -> float | None:
    """Reference depth in cm, 0.6 R50 − 0.1."""
    r50 = electron_r50(i_50)
    if r50 is None:
        return None
    return 0.6 * r50 - 0.1


def electron_r50(i_50: float) -> float | None:
    """R50 in cm from I50. The fit changes at 10 cm."""
    if i_50 <= 0:
        return None
    return _r50(i_50)


def electron_quality_text(i_50: float) -> str | None:
    """R50 from I50 and dref from R50, with the arithmetic."""
    r50 = electron_r50(i_50)
    dref = electron_dref(i_50)
    if r50 is None or dref is None:
        return None
    if i_50 < 10:
        r50_step = f"1.029 × {_shown(i_50)} − 0.06 = {_shown(r50)}"
    else:
        r50_step = f"1.59 × {_shown(i_50)} − 0.37 = {_shown(r50)}"
    lines = [
        f"R50: {_shown(r50)} [cm]",
        r50_step,
        "",
        f"dref: {_shown(dref)} [cm]",
        f"0.6 × {_shown(r50)} − 0.1 = {_shown(dref)}",
    ]
    return "\n".join(lines)


def electron_kq_value(
    chamber: Chamber | None,
    *,
    method: str,
    i_50: float,
    k_ecal: float | None,
) -> float | None:
    if i_50 <= 0:
        return None
    r50 = _r50(i_50)
    if method == "legacy":
        if k_ecal is None:
            return None
        return k_ecal * (0.9905 + 0.071 * math.exp(-r50 / 3.67))
    if chamber is None or r50 <= 0:
        return None
    try:
        resolved = resolve_chamber(chamber)
    except ValueError:
        return None
    coef = resolved.electron_coefficients
    if coef is None:
        return None
    return (float(coef.a) + float(coef.b) * r50 ** -float(coef.c)) * float(coef.kq_ecal)


def electron_dose_text(
    *,
    tissue: float,
    m_corrected: float,
    kq: float,
    n_dw: float,
    mu: float,
    clinical_pdd: float,
    pgr: float | None = None,
    adjusted: bool = False,
) -> str:
    """Dose at dref and at dmax for the measurement MU. Legacy passes Pgr; modern leaves it out."""
    suffix = ", adjusted" if adjusted else ""
    depth_name = f"Dose at dref{suffix}"
    dmax_name = f"Dose at dmax{suffix}"
    if mu == 0 or clinical_pdd == 0 or (pgr is not None and pgr == 0):
        return f"{depth_name}\n\n{dmax_name}"
    dose_ref = tissue * m_corrected * kq * n_dw
    reading_name = "M adjusted" if adjusted else "M corrected"
    product = (
        f"tissue {_shown(tissue)} × {reading_name} {_shown(m_corrected)} × "
        f"kQ {_shown(kq)} × NDw {_shown(n_dw)}"
    )
    if pgr is not None:
        dose_ref *= pgr
        product += f" × Pgr {_shown(pgr)}"
    product += f" = {dose_ref:.4f}"
    fraction = clinical_pdd / 100
    dose_dmax = dose_ref / fraction
    return "\n\n".join(
        [
            "\n".join(
                [
                    f"{depth_name}: {dose_ref:.4f} [cGy]",
                    product,
                ]
            ),
            "\n".join(
                [
                    f"{dmax_name}: {dose_dmax:.4f} [cGy]",
                    f"{_shown(clinical_pdd)} / 100 = {_shown(fraction)}",
                    f"{_shown(dose_ref)} / {_shown(fraction)} = {dose_dmax:.4f}",
                ]
            ),
        ]
    )


def range_warnings(temp_c: float, press_kpa_value: float) -> list[str]:
    warnings = []
    if temp_c < TEMP_MIN or temp_c > TEMP_MAX:
        warnings.append(f"Temperature (Water) {temp_c:.2f} °C is outside 17–27 °C.")
    if press_kpa_value < PRESS_MIN or press_kpa_value > PRESS_MAX:
        warnings.append(f"Pressure {press_kpa_value:.2f} kPa is outside 91–111 kPa.")
    return warnings


def pylinac_model_choices() -> list[tuple[str, str]]:
    """(model name for IonChambers.from_name, label for the combo)."""
    choices = []
    for attr, chamber in vars(tg51.IonChambers).items():
        if isinstance(chamber, tg51.IonChamber):
            choices.append((chamber.name, f"{attr.replace('_', ' ')} ({chamber.name})"))
    choices.sort(key=lambda item: item[1].lower())
    return choices


def model_label(model: str) -> str:
    if model == "custom":
        return "Custom"
    for name, label in pylinac_model_choices():
        if name == model:
            return label
    return model or ""


def find_pylinac_chamber(model: str) -> tg51.IonChamber:
    try:
        return tg51.IonChambers.from_name(model)
    except ValueError:
        pass
    wanted = model.strip().lower()
    for attr, chamber in vars(tg51.IonChambers).items():
        if not isinstance(chamber, tg51.IonChamber):
            continue
        label = attr.replace("_", " ").lower()
        if wanted in (chamber.name.lower(), label, f"{label} ({chamber.name.lower()})"):
            return chamber
    raise ValueError(f"Unknown chamber model {model!r}.")


def _photon_coefficients(block: dict | None) -> tg51.PhotonChamberCoefficients | None:
    if not block or any(block.get(key) is None for key in ("a", "b", "c")):
        return None
    kwargs = {"a": block["a"], "b": block["b"], "c": block["c"]}
    for key in ("a_prime", "b_prime", "c_prime", "d_prime"):
        if block.get(key) is not None:
            kwargs[key] = block[key]
    return tg51.PhotonChamberCoefficients(**kwargs)


def _electron_coefficients(block: dict | None) -> tg51.ElectronChamberCoefficients | None:
    if not block or any(block.get(key) is None for key in ("kq_ecal", "a", "b", "c")):
        return None
    return tg51.ElectronChamberCoefficients(
        kq_ecal=block["kq_ecal"],
        a=block["a"],
        b=block["b"],
        c=block["c"],
    )


def resolve_chamber(chamber: Chamber) -> tg51.IonChamber:
    if chamber.model == "custom":
        return tg51.IonChamber(
            name=chamber.name or "custom",
            photon_coefficients=_photon_coefficients(chamber.photon_coefficients),
            electron_coefficients=_electron_coefficients(chamber.electron_coefficients),
        )
    return find_pylinac_chamber(chamber.model)


def chamber_kecal(chamber: Chamber | None) -> float | None:
    """Legacy k_ecal for this chamber. A stored value wins; otherwise the model table is used."""
    if chamber is None:
        return None
    if chamber.k_ecal is not None:
        return float(chamber.k_ecal)
    return kecal_hint(chamber)


def kecal_hint(chamber: Chamber) -> float | None:
    if chamber.model == "custom":
        block = chamber.electron_coefficients or {}
        value = block.get("kq_ecal")
        return None if value is None else float(value)
    try:
        resolved = find_pylinac_chamber(chamber.model)
    except ValueError:
        return None
    if resolved.electron_coefficients is None:
        return None
    return float(resolved.electron_coefficients.kq_ecal)


def _lead_foil(value: str):
    key = (value or "none").strip().lower()
    if key in ("", "none"):
        return None
    if key in ("30cm", "50cm"):
        return key
    raise ValueError(f"Unknown lead foil position {value!r}.")


def _require(errors: list[str], ok: bool, message: str) -> None:
    if not ok:
        errors.append(message)


def calculate(
    case: CalibrationCase,
    *,
    institution: str,
    physicist: str,
    unit: str,
    energy: Energy,
    chamber: Chamber,
) -> CalcOutcome:
    errors: list[str] = []
    _require(errors, case.temp_value is not None, "Enter a temperature.")
    _require(errors, case.press_value is not None, "Enter a pressure.")
    _require(errors, case.voltage_reference is not None, "Enter the reference voltage.")
    _require(errors, case.voltage_reduced is not None, "Enter the reduced voltage.")
    _require(errors, case.mu is not None, "Enter the monitor units.")
    _require(errors, case.n_dw is not None, "Enter NDw.")
    _require(errors, case.p_elec is not None, "Enter P_elec.")
    _require(errors, case.tissue_correction is not None, "Enter the tissue correction.")
    _require(errors, bool(case.m_reference), "Enter at least one reference reading.")
    _require(errors, bool(case.m_opposite), "Enter at least one opposite-polarity reading.")
    _require(errors, bool(case.m_reduced), "Enter at least one reduced-voltage reading.")
    _require(errors, bool(chamber and chamber.id), "Select an ion chamber.")

    if case.mu is not None and case.mu <= 0:
        errors.append("Monitor units must be greater than zero.")
    if case.n_dw is not None and case.n_dw <= 0:
        errors.append("NDw must be greater than zero.")
    if case.tissue_correction is not None and case.tissue_correction <= 0:
        errors.append("Tissue correction must be greater than zero.")

    # The worked example uses −300 V and −150 V. "Reduced" is the smaller magnitude;
    # comparing the signed numbers would reject that pair because −150 > −300.
    if case.voltage_reference is not None and case.voltage_reduced is not None:
        if case.voltage_reference == 0 or case.voltage_reduced == 0:
            errors.append("Enter a non-zero reference voltage and reduced voltage.")
        elif (case.voltage_reference > 0) != (case.voltage_reduced > 0):
            errors.append("Reference and reduced voltages must have the same sign.")
        elif abs(case.voltage_reduced) >= abs(case.voltage_reference):
            errors.append("Reduced voltage must be lower in magnitude than the reference voltage.")

    if not float(energy.nominal).is_integer():
        errors.append("Nominal energy must be a whole number of MV or MeV.")

    kecal = None
    if energy.modality == "photon":
        _require(errors, case.measured_pdd10 is not None, "Enter PDD(10)x.")
        _require(errors, case.clinical_pdd10 is not None, "Enter clinical PDD(10).")
        if case.clinical_pdd10 is not None and case.clinical_pdd10 <= 0:
            errors.append("Clinical PDD(10) must be greater than zero.")
        if case.measured_pdd10 is not None and 0 < case.measured_pdd10 < 20:
            errors.append("Enter PDD(10)x as a percent, such as 66.4.")
        if case.clinical_pdd10 is not None and 0 < case.clinical_pdd10 < 20:
            errors.append("Enter clinical PDD(10) as a percent, such as 66.4.")
        try:
            _lead_foil(case.lead_foil)
        except ValueError as exc:
            errors.append(str(exc))
    else:
        _require(errors, case.clinical_pdd is not None, "Enter clinical PDD.")
        if case.clinical_pdd is not None and case.clinical_pdd <= 0:
            errors.append("Clinical PDD must be greater than zero.")
        if case.clinical_pdd is not None and 0 < case.clinical_pdd < 20:
            errors.append("Enter clinical PDD as a percent, such as 98.5.")
        _require(errors, case.i_50 is not None, "Enter I50.")
        kecal = case.k_ecal if case.k_ecal is not None else chamber_kecal(chamber)
        if case.electron_method == "legacy":
            _require(errors, kecal is not None, "Enter k_ecal on the ion chamber.")
            _require(errors, bool(case.m_gradient), "Enter the gradient reading at dref + 0.5 rcav.")
        elif case.electron_method != "modern":
            errors.append("Choose the legacy or modern electron method.")

    resolved = None
    if chamber and chamber.id:
        if chamber.model == "custom":
            if energy.modality == "photon" and _photon_coefficients(chamber.photon_coefficients) is None:
                errors.append("Enter photon coefficients a, b, and c for this custom chamber.")
            if energy.modality == "electron" and _electron_coefficients(chamber.electron_coefficients) is None:
                errors.append("Enter electron coefficients kq_ecal, a, b, and c for this custom chamber.")
        try:
            resolved = resolve_chamber(chamber)
        except ValueError as exc:
            errors.append(str(exc))
        if resolved is not None and chamber.model != "custom":
            if energy.modality == "photon" and resolved.photon_coefficients is None:
                errors.append("This chamber has no photon kQ fit.")
            if energy.modality == "electron" and resolved.electron_coefficients is None:
                errors.append("This chamber has no electron kQ fit.")

    if errors:
        return CalcOutcome(errors=errors, warnings=[], result=None, pylinac_version="", calculator=None)

    temp_c = temperature_celsius(case.temp_value, case.temp_unit)
    press = pressure_kpa(case.press_value, case.press_unit)
    warnings = range_warnings(temp_c, press)
    try:
        calculator = _build(
            case,
            institution=institution,
            physicist=physicist,
            unit=unit,
            energy=energy,
            chamber=resolved,
            temp_c=temp_c,
            press=press,
            kecal=kecal,
        )
        result = _read_result(calculator, energy.modality, case.electron_method)
    except Exception as exc:
        return CalcOutcome(
            errors=[str(exc)],
            warnings=warnings,
            result=None,
            pylinac_version="",
            calculator=None,
        )
    return CalcOutcome(
        errors=[],
        warnings=warnings,
        result=result,
        pylinac_version=pylinac.__version__,
        calculator=calculator,
    )


def _build(case, *, institution, physicist, unit, energy, chamber, temp_c, press, kecal):
    shared = dict(
        institution=institution,
        physicist=physicist,
        unit=unit,
        measurement_date=case.measurement_date,
        temp=temp_c,
        press=press,
        chamber=chamber,
        n_dw=case.n_dw,
        p_elec=case.p_elec,
        electrometer=case.electrometer,
        voltage_reference=int(case.voltage_reference),
        voltage_reduced=int(case.voltage_reduced),
        m_reference=list(case.m_reference),
        m_opposite=list(case.m_opposite),
        m_reduced=list(case.m_reduced),
        mu=int(case.mu),
        tissue_correction=case.tissue_correction,
        m_reference_adjusted=list(case.m_reference_adjusted) or None,
        energy=int(energy.nominal),
    )
    if energy.modality == "photon":
        return tg51.TG51Photon(
            **shared,
            measured_pdd10=case.measured_pdd10,
            lead_foil=_lead_foil(case.lead_foil),
            clinical_pdd10=case.clinical_pdd10,
            fff=bool(energy.fff),
        )
    electron = dict(
        **shared,
        clinical_pdd=case.clinical_pdd,
        cone=case.cone.strip() or "10x10",
        i_50=case.i_50,
    )
    if case.electron_method == "modern":
        return tg51.TG51ElectronModern(**electron)
    return tg51.TG51ElectronLegacy(**electron, k_ecal=kecal, m_gradient=list(case.m_gradient))


def _num(obj, name: str) -> float:
    return float(getattr(obj, name))


def _read_result(calculator, modality: str, electron_method: str) -> dict:
    result = {
        "kq": _num(calculator, "kq"),
        "p_tp": _num(calculator, "p_tp"),
        "p_ion": _num(calculator, "p_ion"),
        "p_pol": _num(calculator, "p_pol"),
        "m_corrected": _num(calculator, "m_corrected"),
        "dose_mu_dmax": _num(calculator, "dose_mu_dmax"),
    }
    if modality == "photon":
        result["pddx"] = _num(calculator, "pddx")
        result["dose_mu_10"] = _num(calculator, "dose_mu_10")
    else:
        result["r_50"] = _num(calculator, "r_50")
        result["dref"] = _num(calculator, "dref")
        result["dose_mu_dref"] = _num(calculator, "dose_mu_dref")
        if electron_method == "legacy":
            result["pq_gr"] = _num(calculator, "pq_gr")
    if getattr(calculator, "output_was_adjusted", False):
        if modality == "photon":
            result["dose_mu_10_adjusted"] = _num(calculator, "dose_mu_10_adjusted")
        else:
            result["dose_mu_dref_adjusted"] = _num(calculator, "dose_mu_dref_adjusted")
        result["dose_mu_dmax_adjusted"] = _num(calculator, "dose_mu_dmax_adjusted")
    return result


def write_pdf(calculator, path: str, warnings: list[str] | None = None) -> None:
    notes = [item for item in (warnings or []) if item]
    calculator.publish_pdf(str(path), notes=notes or None, open_file=False)
