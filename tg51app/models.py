"""Catalogs (users, chambers, electrometers, machines) and the calibration cases stored under _cases."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .app_settings import DEFAULT_SETUP, DEFAULT_VALID_RANGES, dose_decimal_places

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def new_id() -> str:
    return uuid.uuid4().hex


def safe_id(value: object) -> str:
    cleaned = _SAFE_ID.sub("", str(value or ""))
    return cleaned or new_id()


def _text(value: object) -> str:
    return str(value or "").strip()


def _optional_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _float_list(value: object) -> list[float]:
    if value is None or value == "":
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    return [float(item) for item in value]


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not number.is_integer():
        raise ValueError(f"expected a whole number, got {value!r}")
    return int(number)


@dataclass
class User:
    id: str
    name: str
    email: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email}

    @classmethod
    def from_dict(cls, data: dict) -> User:
        return cls(id=safe_id(data.get("id")), name=_text(data.get("name")), email=_text(data.get("email")))


@dataclass
class Energy:
    id: str
    modality: str
    nominal: float
    fff: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "modality": self.modality,
            "nominal": self.nominal,
            "fff": bool(self.fff) if self.modality == "photon" else False,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Energy:
        modality = _text(data.get("modality")).lower()
        if modality not in ("photon", "electron"):
            modality = "photon"
        nominal = float(data.get("nominal"))
        fff = bool(data.get("fff")) if modality == "photon" else False
        return cls(id=safe_id(data.get("id")), modality=modality, nominal=nominal, fff=fff)


def energy_label(energy: Energy) -> str:
    number = float(energy.nominal)
    text = str(int(number)) if number.is_integer() else str(number)
    if energy.modality == "electron":
        return f"{text} MeV"
    return f"{text} MV{' FFF' if energy.fff else ''}"


@dataclass
class Machine:
    id: str
    name: str
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    comment: str = ""
    energies: list[Energy] = field(default_factory=list)

    def energy(self, energy_id: str) -> Energy | None:
        return next((item for item in self.energies if item.id == energy_id), None)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "comment": self.comment,
            "energies": [item.to_dict() for item in self.energies],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Machine:
        energies = []
        for item in data.get("energies") or []:
            if isinstance(item, dict):
                energies.append(Energy.from_dict(item))
        return cls(
            id=safe_id(data.get("id")),
            name=_text(data.get("name")),
            manufacturer=_text(data.get("manufacturer")),
            model=_text(data.get("model")),
            serial=_text(data.get("serial")),
            comment=_text(data.get("comment")),
            energies=energies,
        )


def _coeff_block(value: object, keys: tuple[str, ...]) -> dict | None:
    if not isinstance(value, dict):
        return None
    block = {}
    for key in keys:
        item = value.get(key)
        block[key] = None if item is None or item == "" else float(item)
    if all(item is None for item in block.values()):
        return None
    return block


PHOTON_COEFFICIENT_KEYS = ("a", "b", "c", "a_prime", "b_prime", "c_prime", "d_prime")
ELECTRON_COEFFICIENT_KEYS = ("kq_ecal", "a", "b", "c")
CHAMBER_CYLINDER = "cylinder"
CHAMBER_PARALLEL_PLATE = "parallel_plate"
_CALIBRATION_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y")


def parse_calibration_date(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    for fmt in _CALIBRATION_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


@dataclass
class Calibration:
    """One laboratory calibration. ``factor`` is NDw for a chamber and P_elec for an electrometer."""

    date: str = ""
    lab: str = ""
    factor: float | None = None

    def to_dict(self) -> dict:
        return {"date": self.date, "lab": self.lab, "factor": self.factor}

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        return cls(
            date=_text(data.get("date")),
            lab=_text(data.get("lab")),
            factor=_optional_float(data.get("factor")),
        )


def latest_calibration(items: list[Calibration]) -> Calibration | None:
    """Newest dated calibration that has a factor. Undated entries are older than dated ones."""
    usable = [item for item in items if item.factor is not None]
    pool = usable or list(items)
    if not pool:
        return None
    dated = [(parse_calibration_date(item.date), item) for item in pool]
    dated.sort(key=lambda pair: (pair[0] is not None, pair[0] or datetime.min))
    return dated[-1][1]


def _calibration_list(raw: object, date: str, lab: str, factor: float | None) -> list[Calibration]:
    items: list[Calibration] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, Calibration):
                items.append(item)
            elif isinstance(item, dict):
                items.append(Calibration.from_dict(item))
    if items:
        return items
    if factor is not None or date or lab:
        return [Calibration(date=date, lab=lab, factor=factor)]
    return []


@dataclass
class Electrometer:
    id: str
    name: str
    manufacturer: str = ""
    model: str = ""
    serial: str = ""
    calibration_lab: str = ""
    calibration_date: str = ""
    p_elec: float | None = None
    calibrations: list[Calibration] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.calibrations = _calibration_list(
            self.calibrations, self.calibration_date, self.calibration_lab, self.p_elec
        )
        latest = latest_calibration(self.calibrations)
        if latest is not None:
            self.p_elec = latest.factor
            self.calibration_date = latest.date
            self.calibration_lab = latest.lab

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "serial": self.serial,
            "calibration_lab": self.calibration_lab,
            "calibration_date": self.calibration_date,
            "p_elec": self.p_elec,
            "calibrations": [item.to_dict() for item in self.calibrations],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Electrometer:
        return cls(
            id=safe_id(data.get("id")),
            name=_text(data.get("name")),
            manufacturer=_text(data.get("manufacturer")),
            model=_text(data.get("model")),
            serial=_text(data.get("serial")),
            calibration_lab=_text(data.get("calibration_lab")),
            calibration_date=_text(data.get("calibration_date")),
            p_elec=_optional_float(data.get("p_elec")),
            calibrations=_calibration_list(
                data.get("calibrations"),
                _text(data.get("calibration_date")),
                _text(data.get("calibration_lab")),
                _optional_float(data.get("p_elec")),
            ),
        )


def electrometer_label(item: Electrometer) -> str:
    """Text stored on a case and passed to pylinac."""
    bits = []
    for part in (item.manufacturer, item.model):
        if part and part not in bits:
            bits.append(part)
    if not bits and item.name:
        bits.append(item.name)
    text = " ".join(bits)
    if item.serial:
        text = f"{text} ({item.serial})" if text else item.serial
    if item.name and item.name not in text:
        return f"{item.name}  ({text})" if text else item.name
    return text or item.name


def _setup_int(raw: dict, key: str, default: int) -> int:
    try:
        number = float(raw.get(key, default))
    except (TypeError, ValueError):
        return default
    if not number.is_integer():
        return default
    return int(number)


def _setup_float(raw: dict, key: str, default: float) -> float:
    try:
        return float(raw.get(key, default))
    except (TypeError, ValueError):
        return default


def _setup_values(value: object) -> dict:
    raw = value if isinstance(value, dict) else {}
    depth = _setup_float(raw, "measurement_depth_cm", float(DEFAULT_SETUP["measurement_depth_cm"]))
    tissue = _setup_float(raw, "tissue_correction", float(DEFAULT_SETUP["tissue_correction"]))
    field_size = _text(raw.get("field_size")) or str(DEFAULT_SETUP["field_size"])
    if depth <= 0:
        depth = float(DEFAULT_SETUP["measurement_depth_cm"])
    if tissue <= 0:
        tissue = float(DEFAULT_SETUP["tissue_correction"])
    return {
        "voltage_reference": _setup_int(raw, "voltage_reference", int(DEFAULT_SETUP["voltage_reference"])),
        "voltage_reduced": _setup_int(raw, "voltage_reduced", int(DEFAULT_SETUP["voltage_reduced"])),
        "mu": _setup_int(raw, "mu", int(DEFAULT_SETUP["mu"])),
        "tissue_correction": tissue,
        "field_size": field_size,
        "measurement_depth_cm": depth,
    }


def _link_legacy_electrometers(chambers: list[Chamber], electrometers: list[Electrometer]) -> None:
    """Turn a chamber's old electrometer string into a catalog record."""
    for chamber in chambers:
        if chamber.electrometer_id:
            linked = next((item for item in electrometers if item.id == chamber.electrometer_id), None)
            if linked is not None:
                if linked.p_elec is None and chamber.p_elec is not None:
                    linked.p_elec = chamber.p_elec
                continue
        text = chamber.electrometer.strip()
        if not text:
            continue
        match = next(
            (item for item in electrometers if item.name == text or electrometer_label(item) == text),
            None,
        )
        if match is None:
            match = Electrometer(id=new_id(), name=text, p_elec=chamber.p_elec)
            electrometers.append(match)
        elif match.p_elec is None and chamber.p_elec is not None:
            match.p_elec = chamber.p_elec
        chamber.electrometer_id = match.id


def chamber_type_label(value: str) -> str:
    if value == CHAMBER_PARALLEL_PLATE:
        return "Parallel plate"
    return "Cylinder"


def _chamber_type(value: object) -> str:
    text = _text(value).lower().replace("-", " ").replace("_", " ")
    if text in ("parallel plate", "parallel", "pp"):
        return CHAMBER_PARALLEL_PLATE
    return CHAMBER_CYLINDER


@dataclass
class Chamber:
    id: str
    name: str
    serial: str = ""
    model: str = ""
    chamber_type: str = CHAMBER_CYLINDER
    rcav_cm: float | None = None
    n_dw: float | None = None
    p_elec: float | None = None
    k_ecal: float | None = None
    electrometer_id: str = ""
    electrometer: str = ""
    calibration_lab: str = ""
    calibration_date: str = ""
    calibrations: list[Calibration] = field(default_factory=list)
    photon_coefficients: dict | None = None
    electron_coefficients: dict | None = None

    def __post_init__(self) -> None:
        self.calibrations = _calibration_list(
            self.calibrations, self.calibration_date, self.calibration_lab, self.n_dw
        )
        latest = latest_calibration(self.calibrations)
        if latest is not None:
            self.n_dw = latest.factor
            self.calibration_date = latest.date
            self.calibration_lab = latest.lab

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "serial": self.serial,
            "model": self.model,
            "chamber_type": self.chamber_type,
            "rcav_cm": self.rcav_cm if self.chamber_type == CHAMBER_CYLINDER else None,
            "n_dw": self.n_dw,
            "p_elec": self.p_elec,
            "k_ecal": self.k_ecal,
            "electrometer_id": self.electrometer_id,
            "electrometer": self.electrometer,
            "calibration_lab": self.calibration_lab,
            "calibration_date": self.calibration_date,
            "calibrations": [item.to_dict() for item in self.calibrations],
            "photon_coefficients": self.photon_coefficients,
            "electron_coefficients": self.electron_coefficients,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Chamber:
        model = _text(data.get("model"))
        chamber_type = _chamber_type(data.get("chamber_type"))
        rcav = _optional_float(data.get("rcav_cm")) if chamber_type == CHAMBER_CYLINDER else None
        return cls(
            id=safe_id(data.get("id")),
            name=_text(data.get("name")),
            serial=_text(data.get("serial")),
            model=model,
            chamber_type=chamber_type,
            rcav_cm=rcav,
            n_dw=_optional_float(data.get("n_dw")),
            p_elec=_optional_float(data.get("p_elec")),
            k_ecal=_optional_float(data.get("k_ecal")),
            electrometer_id=_text(data.get("electrometer_id")),
            electrometer=_text(data.get("electrometer")),
            calibration_lab=_text(data.get("calibration_lab")),
            calibration_date=_text(data.get("calibration_date")),
            calibrations=_calibration_list(
                data.get("calibrations"),
                _text(data.get("calibration_date")),
                _text(data.get("calibration_lab")),
                _optional_float(data.get("n_dw")),
            ),
            photon_coefficients=_coeff_block(data.get("photon_coefficients"), PHOTON_COEFFICIENT_KEYS),
            electron_coefficients=_coeff_block(data.get("electron_coefficients"), ELECTRON_COEFFICIENT_KEYS),
        )


@dataclass
class Catalog:
    institution: str = ""
    font_family: str = ""
    font_size: int = 0
    users: list[User] = field(default_factory=list)
    chambers: list[Chamber] = field(default_factory=list)
    electrometers: list[Electrometer] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=list)
    valid_ranges: dict | None = None
    history_warn_percent: float = 5.0
    dose_decimal_places: int = 2
    voltage_reference: int = 300
    voltage_reduced: int = 150
    mu: int = 100
    tissue_correction: float = 1.0
    field_size: str = "10x10"
    measurement_depth_cm: float = 10.0

    def user(self, user_id: str) -> User | None:
        return next((item for item in self.users if item.id == user_id), None)

    def chamber(self, chamber_id: str) -> Chamber | None:
        return next((item for item in self.chambers if item.id == chamber_id), None)

    def electrometer(self, electrometer_id: str) -> Electrometer | None:
        return next((item for item in self.electrometers if item.id == electrometer_id), None)

    def machine(self, machine_id: str) -> Machine | None:
        return next((item for item in self.machines if item.id == machine_id), None)

    def to_settings(self) -> dict:
        return {
            "Institution": self.institution,
            "Font": {"family": self.font_family, "size": self.font_size},
            "PreviousCalibrationWarnPercent": self.history_warn_percent,
            "DoseDecimalPlaces": self.dose_decimal_places,
            "Setup": {
                "voltage_reference": self.voltage_reference,
                "voltage_reduced": self.voltage_reduced,
                "mu": self.mu,
                "tissue_correction": self.tissue_correction,
                "field_size": self.field_size,
                "measurement_depth_cm": self.measurement_depth_cm,
            },
            "ValidRanges": self.valid_ranges
            if self.valid_ranges is not None
            else {key: dict(bounds) for key, bounds in DEFAULT_VALID_RANGES.items()},
            "Users": [item.to_dict() for item in self.users],
            "IonChambers": [item.to_dict() for item in self.chambers],
            "Electrometers": [item.to_dict() for item in self.electrometers],
            "Machines": [item.to_dict() for item in self.machines],
        }

    @classmethod
    def from_settings(cls, data: dict | None) -> Catalog:
        data = data if isinstance(data, dict) else {}
        font = data.get("Font") if isinstance(data.get("Font"), dict) else {}
        try:
            size = int(font.get("size") or 0)
        except (TypeError, ValueError):
            size = 0
        users = [User.from_dict(item) for item in data.get("Users") or [] if isinstance(item, dict)]
        chambers = [Chamber.from_dict(item) for item in data.get("IonChambers") or [] if isinstance(item, dict)]
        electrometers = [
            Electrometer.from_dict(item) for item in data.get("Electrometers") or [] if isinstance(item, dict)
        ]
        _link_legacy_electrometers(chambers, electrometers)
        machines = [Machine.from_dict(item) for item in data.get("Machines") or [] if isinstance(item, dict)]
        ranges = data.get("ValidRanges") if isinstance(data.get("ValidRanges"), dict) else None
        try:
            percent = float(data.get("PreviousCalibrationWarnPercent", 5))
        except (TypeError, ValueError):
            percent = 5.0
        if percent < 0:
            percent = 5.0
        places = dose_decimal_places(data.get("DoseDecimalPlaces", 2))
        setup = _setup_values(data.get("Setup"))
        return cls(
            institution=_text(data.get("Institution")),
            font_family=_text(font.get("family")),
            font_size=max(size, 0),
            users=users,
            chambers=chambers,
            electrometers=electrometers,
            machines=machines,
            valid_ranges=ranges,
            history_warn_percent=percent,
            dose_decimal_places=places,
            voltage_reference=setup["voltage_reference"],
            voltage_reduced=setup["voltage_reduced"],
            mu=setup["mu"],
            tissue_correction=setup["tissue_correction"],
            field_size=setup["field_size"],
            measurement_depth_cm=setup["measurement_depth_cm"],
        )


@dataclass
class CalibrationCase:
    id: str
    machine_id: str
    energy_id: str
    status: str = "draft"
    user_id: str = ""
    measurement_date: str = ""
    temp_value: float | None = None
    temp_unit: str = "C"
    press_value: float | None = None
    press_unit: str = "mmHg"
    chamber_id: str = ""
    n_dw: float | None = None
    p_elec: float | None = None
    electrometer_id: str = ""
    electrometer: str = ""
    voltage_reference: int | None = None
    voltage_reduced: int | None = None
    m_reference: list[float] = field(default_factory=list)
    m_opposite: list[float] = field(default_factory=list)
    m_reduced: list[float] = field(default_factory=list)
    m_reference_adjusted: list[float] = field(default_factory=list)
    mu: int | None = None
    tissue_correction: float | None = 1.0
    measured_pdd10: float | None = None
    clinical_pdd10: float | None = None
    lead_foil: str = "none"
    electron_method: str = "legacy"
    clinical_pdd: float | None = None
    cone: str = ""
    i_50: float | None = None
    k_ecal: float | None = None
    m_gradient: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    result: dict | None = None
    pylinac_version: str = ""
    pdf_path: str = ""
    comment: str = ""

    @classmethod
    def new(cls, machine_id: str, energy_id: str) -> CalibrationCase:
        from datetime import date

        return cls(
            id=new_id(),
            machine_id=machine_id,
            energy_id=energy_id,
            measurement_date=date.today().isoformat(),
        )

    def copy_shared_setup(self, previous: CalibrationCase) -> None:
        """Date, physicist, temperature, pressure, chamber, and electrometer from another case.

        NDw and P_elec stay empty so the new case uses the latest calibration of the selected devices.
        """
        if previous.measurement_date:
            self.measurement_date = previous.measurement_date
        self.user_id = previous.user_id
        self.temp_value = previous.temp_value
        self.temp_unit = previous.temp_unit or self.temp_unit
        self.press_value = previous.press_value
        self.press_unit = previous.press_unit or self.press_unit
        self.chamber_id = previous.chamber_id
        self.electrometer_id = previous.electrometer_id
        self.electrometer = previous.electrometer

    def clone(self) -> CalibrationCase:
        return CalibrationCase.from_dict(self.to_dict())

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "machine_id": self.machine_id,
            "energy_id": self.energy_id,
            "status": self.status if self.status in ("draft", "calculated") else "draft",
            "user_id": self.user_id,
            "measurement_date": self.measurement_date,
            "temp_value": self.temp_value,
            "temp_unit": self.temp_unit,
            "press_value": self.press_value,
            "press_unit": self.press_unit,
            "chamber_id": self.chamber_id,
            "n_dw": self.n_dw,
            "p_elec": self.p_elec,
            "electrometer_id": self.electrometer_id,
            "electrometer": self.electrometer,
            "voltage_reference": self.voltage_reference,
            "voltage_reduced": self.voltage_reduced,
            "m_reference": list(self.m_reference),
            "m_opposite": list(self.m_opposite),
            "m_reduced": list(self.m_reduced),
            "m_reference_adjusted": list(self.m_reference_adjusted),
            "mu": self.mu,
            "tissue_correction": self.tissue_correction,
            "measured_pdd10": self.measured_pdd10,
            "clinical_pdd10": self.clinical_pdd10,
            "lead_foil": self.lead_foil,
            "electron_method": self.electron_method if self.electron_method in ("legacy", "modern") else "legacy",
            "clinical_pdd": self.clinical_pdd,
            "cone": self.cone,
            "i_50": self.i_50,
            "k_ecal": self.k_ecal,
            "m_gradient": list(self.m_gradient),
            "warnings": list(self.warnings),
            "result": self.result,
            "pylinac_version": self.pylinac_version,
            "pdf_path": self.pdf_path,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> CalibrationCase:
        if not isinstance(data, dict):
            raise ValueError("case must be an object")
        status = _text(data.get("status")).lower()
        method = _text(data.get("electron_method")).lower()
        result = data.get("result")
        return cls(
            id=safe_id(data.get("id")),
            machine_id=safe_id(data.get("machine_id")),
            energy_id=safe_id(data.get("energy_id")),
            status=status if status in ("draft", "calculated") else "draft",
            user_id=_text(data.get("user_id")),
            measurement_date=_text(data.get("measurement_date")),
            temp_value=_optional_float(data.get("temp_value")),
            temp_unit=_text(data.get("temp_unit")) or "C",
            press_value=_optional_float(data.get("press_value")),
            press_unit=_text(data.get("press_unit")) or "mmHg",
            chamber_id=_text(data.get("chamber_id")),
            n_dw=_optional_float(data.get("n_dw")),
            p_elec=_optional_float(data.get("p_elec")),
            electrometer_id=_text(data.get("electrometer_id")),
            electrometer=_text(data.get("electrometer")),
            voltage_reference=_optional_int(data.get("voltage_reference")),
            voltage_reduced=_optional_int(data.get("voltage_reduced")),
            m_reference=_float_list(data.get("m_reference")),
            m_opposite=_float_list(data.get("m_opposite")),
            m_reduced=_float_list(data.get("m_reduced")),
            m_reference_adjusted=_float_list(data.get("m_reference_adjusted")),
            mu=_optional_int(data.get("mu")),
            tissue_correction=_optional_float(data.get("tissue_correction")),
            measured_pdd10=_optional_float(data.get("measured_pdd10")),
            clinical_pdd10=_optional_float(data.get("clinical_pdd10")),
            lead_foil=_text(data.get("lead_foil")) or "none",
            electron_method=method if method in ("legacy", "modern") else "legacy",
            clinical_pdd=_optional_float(data.get("clinical_pdd")),
            cone=_text(data.get("cone")),
            i_50=_optional_float(data.get("i_50")),
            k_ecal=_optional_float(data.get("k_ecal")),
            m_gradient=_float_list(data.get("m_gradient")),
            warnings=[str(item) for item in (data.get("warnings") or [])],
            result=result if isinstance(result, dict) else None,
            pylinac_version=_text(data.get("pylinac_version")),
            pdf_path=_text(data.get("pdf_path")),
            comment=_text(data.get("comment")),
        )


def input_dict(case: CalibrationCase) -> dict:
    """Fields that define the measurement, without the stored result."""
    data = case.to_dict()
    for key in ("status", "warnings", "result", "pylinac_version", "pdf_path", "comment"):
        data.pop(key, None)
    return data


class CaseStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def path_for(self, case: CalibrationCase) -> Path:
        return self.root / case.machine_id / case.energy_id / f"{case.id}.json"

    def save(self, case: CalibrationCase) -> Path:
        path = self.path_for(case)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(case.to_dict(), indent=2) + "\n", encoding="utf-8")
        return path

    def delete(self, case: CalibrationCase) -> None:
        path = self.path_for(case)
        if path.is_file():
            path.unlink()
        parent = path.parent
        for folder in (parent, parent.parent):
            try:
                folder.rmdir()
            except OSError:
                break

    def load_all(self) -> list[CalibrationCase]:
        if not self.root.is_dir():
            return []
        cases: list[CalibrationCase] = []
        for path in sorted(self.root.rglob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cases.append(CalibrationCase.from_dict(data))
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                continue
        cases.sort(key=lambda item: (item.measurement_date, item.id))
        return cases

    def latest_for_machine(self, machine_id: str) -> CalibrationCase | None:
        """Most recently saved case for this machine, across its energies."""
        folder = self.root / machine_id
        if not folder.is_dir():
            return None
        newest_path = None
        newest_stamp = -1.0
        for path in folder.rglob("*.json"):
            try:
                stamp = path.stat().st_mtime
            except OSError:
                continue
            if stamp >= newest_stamp:
                newest_path = path
                newest_stamp = stamp
        if newest_path is None:
            return None
        try:
            data = json.loads(newest_path.read_text(encoding="utf-8"))
            return CalibrationCase.from_dict(data)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None

    def for_energy(self, machine_id: str, energy_id: str) -> list[CalibrationCase]:
        return [
            case
            for case in self.load_all()
            if case.machine_id == machine_id and case.energy_id == energy_id
        ]


def describe_case(case: CalibrationCase, catalog: Catalog) -> str:
    machine = catalog.machine(case.machine_id)
    energy = machine.energy(case.energy_id) if machine else None
    parts = [case.measurement_date or case.id]
    if machine and machine.name:
        parts.append(machine.name)
    if energy is not None:
        parts.append(energy_label(energy))
    return " ".join(parts)


def _electrometer_aliases(catalog: Catalog, record_id: str) -> set[str]:
    item = catalog.electrometer(record_id)
    if item is None:
        return set()
    return {name for name in (item.name, electrometer_label(item)) if name}


def _uses_electrometer(electrometer_id: str, legacy: str, record_id: str, aliases: set[str]) -> bool:
    if electrometer_id == record_id:
        return True
    return not electrometer_id and bool(legacy) and legacy in aliases


def deletion_block(store: CaseStore, catalog: Catalog, kind: str, record_id: str) -> str | None:
    """Refuse deleting a catalog record that a saved case, or a chamber, still points at."""
    aliases = _electrometer_aliases(catalog, record_id) if kind == "electrometer" else set()
    matches: list[CalibrationCase] = []
    for case in store.load_all():
        if kind == "user" and case.user_id == record_id:
            matches.append(case)
        elif kind == "chamber" and case.chamber_id == record_id:
            matches.append(case)
        elif kind == "machine" and case.machine_id == record_id:
            matches.append(case)
        elif kind == "energy" and case.energy_id == record_id:
            matches.append(case)
        elif kind == "electrometer" and _uses_electrometer(
            case.electrometer_id, case.electrometer, record_id, aliases
        ):
            matches.append(case)
    chamber_names = []
    if kind == "electrometer":
        for chamber in catalog.chambers:
            if _uses_electrometer(chamber.electrometer_id, chamber.electrometer, record_id, aliases):
                chamber_names.append(chamber.name or chamber.id)
    if not matches and not chamber_names:
        return None
    parts = []
    if chamber_names:
        parts.append("ion chamber: " + ", ".join(chamber_names))
    if matches:
        shown = [describe_case(case, catalog) for case in matches[:8]]
        extra = len(matches) - len(shown)
        names = "; ".join(shown)
        if extra:
            names = f"{names}; and {extra} more"
        parts.append(names)
    noun = {
        "user": "user",
        "chamber": "ion chamber",
        "electrometer": "electrometer",
        "machine": "machine",
        "energy": "energy",
    }.get(kind, kind)
    return f"Cannot delete this {noun}. Used by: {'; '.join(parts)}."
