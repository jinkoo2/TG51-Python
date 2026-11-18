"""Range checks and comparison with earlier calibrations for the same energy."""

from __future__ import annotations

from .calc import pressure_kpa, temperature_celsius
from .models import CalibrationCase

FIELD_LABELS = {
    "temperature_c": "Temperature (Water)",
    "pressure_kpa": "Pressure",
    "n_dw": "NDw",
    "p_elec": "P_elec",
    "voltage_reference": "Vref",
    "voltage_reduced": "Vreduced",
    "mu": "MU",
    "tissue_correction": "Tissue correction",
    "m_reference": "M at Vref",
    "m_opposite": "M at opposite polarity",
    "m_reduced": "M at Vreduced",
    "m_reference_adjusted": "M adjusted",
    "m_gradient": "Gradient reading",
    "measured_pdd10": "PDD(10)x",
    "clinical_pdd10": "Clinical PDD(10)",
    "clinical_pdd": "Clinical PDD",
    "i_50": "I50",
    "k_ecal": "k_ecal",
}

FIELD_UNITS = {
    "temperature_c": "°C",
    "pressure_kpa": "kPa",
    "n_dw": "Gy/nC",
    "voltage_reference": "V",
    "voltage_reduced": "V",
    "mu": "MU",
    "m_reference": "nC",
    "m_opposite": "nC",
    "m_reduced": "nC",
    "m_reference_adjusted": "nC",
    "m_gradient": "nC",
    "measured_pdd10": "%",
    "clinical_pdd10": "%",
    "clinical_pdd": "%",
    "i_50": "cm",
}

READING_FIELDS = (
    "m_reference",
    "m_opposite",
    "m_reduced",
    "m_reference_adjusted",
    "m_gradient",
)

# Reading groups are checked against this one settings range.
READING_RANGE_KEY = "m_reading"


def outside_range(value: float, bounds: dict | None) -> bool:
    if not bounds:
        return False
    low = bounds.get("min")
    high = bounds.get("max")
    if low is not None and value < low:
        return True
    if high is not None and value > high:
        return True
    return False


def _quantity(value: float, unit: str) -> str:
    text = f"{value:.4g}"
    return f"{text} [{unit}]" if unit else text


def range_message(label: str, value: float, bounds: dict | None, unit: str = "") -> str | None:
    if not outside_range(value, bounds):
        return None
    low = bounds.get("min") if bounds else None
    high = bounds.get("max") if bounds else None
    if low is not None and high is not None:
        limit = f"{low:g}–{high:g}"
    elif low is not None:
        limit = f"at least {low:g}"
    else:
        limit = f"at most {high:g}"
    if unit:
        limit = f"{limit} [{unit}]"
    return f"{label} {_quantity(value, unit)} is outside {limit}."


def canonical_values(case: CalibrationCase) -> dict[str, float]:
    """Numbers compared across calibrations, in °C, kPa, and voltage magnitude."""
    values: dict[str, float] = {}
    if case.temp_value is not None:
        values["temperature_c"] = temperature_celsius(case.temp_value, case.temp_unit)
    if case.press_value is not None:
        values["pressure_kpa"] = pressure_kpa(case.press_value, case.press_unit)
    for key in (
        "n_dw",
        "p_elec",
        "mu",
        "tissue_correction",
        "measured_pdd10",
        "clinical_pdd10",
        "clinical_pdd",
        "i_50",
        "k_ecal",
    ):
        item = getattr(case, key)
        if item is not None:
            values[key] = float(item)
    if case.voltage_reference is not None:
        values["voltage_reference"] = abs(float(case.voltage_reference))
    if case.voltage_reduced is not None:
        values["voltage_reduced"] = abs(float(case.voltage_reduced))
    for key in READING_FIELDS:
        readings = [float(item) for item in getattr(case, key)]
        if readings:
            values[key] = sum(readings) / len(readings)
    return values


def history_messages(
    case: CalibrationCase,
    previous: list[CalibrationCase],
    percent: float,
) -> list[tuple[str, str]]:
    """Fields more than `percent` away from the mean of earlier calculated cases."""
    if percent <= 0:
        return []
    current = canonical_values(case)
    priors = [
        canonical_values(item)
        for item in previous
        if item.id != case.id and item.status == "calculated"
    ]
    messages: list[tuple[str, str]] = []
    for key, value in current.items():
        samples = [item[key] for item in priors if key in item]
        if not samples:
            continue
        mean = sum(samples) / len(samples)
        if abs(value - mean) <= abs(mean) * percent / 100.0:
            continue
        unit = FIELD_UNITS.get(key, "")
        if mean == 0:
            amount = "from a previous mean of 0"
        else:
            amount = (
                f"{abs(value - mean) / abs(mean) * 100:.1f}% from the previous mean "
                f"({_quantity(mean, unit)})"
            )
        label = FIELD_LABELS.get(key, key)
        messages.append((key, f"{label} {_quantity(value, unit)} is {amount}."))
    return messages
