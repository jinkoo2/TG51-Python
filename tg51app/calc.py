"""Run pylinac TG-51 on a calibration case."""

from __future__ import annotations

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


def range_warnings(temp_c: float, press_kpa_value: float) -> list[str]:
    warnings = []
    if temp_c < TEMP_MIN or temp_c > TEMP_MAX:
        warnings.append(f"Temperature {temp_c:.2f} °C is outside 17–27 °C.")
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

    if energy.modality == "photon":
        _require(errors, case.measured_pdd10 is not None, "Enter measured PDD(10).")
        _require(errors, case.clinical_pdd10 is not None, "Enter clinical PDD(10).")
        if case.clinical_pdd10 is not None and case.clinical_pdd10 <= 0:
            errors.append("Clinical PDD(10) must be greater than zero.")
        try:
            _lead_foil(case.lead_foil)
        except ValueError as exc:
            errors.append(str(exc))
    else:
        _require(errors, case.clinical_pdd is not None, "Enter clinical PDD.")
        if case.clinical_pdd is not None and case.clinical_pdd <= 0:
            errors.append("Clinical PDD must be greater than zero.")
        _require(errors, bool(case.cone.strip()), "Enter the cone.")
        _require(errors, case.i_50 is not None, "Enter I50.")
        if case.electron_method == "legacy":
            _require(errors, case.k_ecal is not None, "Enter k_ecal.")
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


def _build(case, *, institution, physicist, unit, energy, chamber, temp_c, press):
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
        cone=case.cone,
        i_50=case.i_50,
    )
    if case.electron_method == "modern":
        return tg51.TG51ElectronModern(**electron)
    return tg51.TG51ElectronLegacy(**electron, k_ecal=case.k_ecal, m_gradient=list(case.m_gradient))


def _maybe(obj, name: str) -> float | None:
    try:
        value = getattr(obj, name)
    except Exception:
        return None
    if value is None:
        return None
    return float(value)


def _read_result(calculator, modality: str, electron_method: str) -> dict:
    result = {
        "kq": _maybe(calculator, "kq"),
        "p_tp": _maybe(calculator, "p_tp"),
        "p_ion": _maybe(calculator, "p_ion"),
        "p_pol": _maybe(calculator, "p_pol"),
        "m_corrected": _maybe(calculator, "m_corrected"),
        "dose_mu_dmax": _maybe(calculator, "dose_mu_dmax"),
    }
    if modality == "photon":
        result["pddx"] = _maybe(calculator, "pddx")
        result["dose_mu_10"] = _maybe(calculator, "dose_mu_10")
    else:
        result["r_50"] = _maybe(calculator, "r_50")
        result["dref"] = _maybe(calculator, "dref")
        result["dose_mu_dref"] = _maybe(calculator, "dose_mu_dref")
        if electron_method == "legacy":
            result["pq_gr"] = _maybe(calculator, "pq_gr")
    if getattr(calculator, "output_was_adjusted", False):
        if modality == "photon":
            result["dose_mu_10_adjusted"] = _maybe(calculator, "dose_mu_10_adjusted")
        else:
            result["dose_mu_dref_adjusted"] = _maybe(calculator, "dose_mu_dref_adjusted")
        result["dose_mu_dmax_adjusted"] = _maybe(calculator, "dose_mu_dmax_adjusted")
    return result


def write_pdf(calculator, path: str, warnings: list[str] | None = None) -> None:
    notes = [item for item in (warnings or []) if item]
    calculator.publish_pdf(str(path), notes=notes or None, open_file=False)
