"""PyQt5 window for TG-51 catalogs and calibration cases."""

from __future__ import annotations

import copy
import os
from pathlib import Path

from PyQt5.QtCore import QDate, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import app_settings
from .app_settings import font_settings, load_settings, save_settings
from .calc import (
    CalcOutcome,
    calculate,
    kecal_hint,
    model_label,
    pressure_kpa,
    pylinac_model_choices,
    range_warnings,
    temperature_celsius,
    write_pdf,
)
from .models import (
    CalibrationCase,
    CaseStore,
    Catalog,
    Chamber,
    Energy,
    Machine,
    User,
    deletion_block,
    describe_case,
    energy_label,
    input_dict,
    new_id,
)

HEADING_STYLE = """
QWidget#appHeading { background: #1f3a5f; }
QWidget#appHeading QLabel { color: #f8fafc; background: transparent; }
QWidget#appHeading QPushButton {
    color: #f8fafc;
    background: #34547a;
    border: none;
    padding: 6px 12px;
    border-radius: 4px;
}
QWidget#appHeading QPushButton:hover { background: #456894; }
QWidget#appHeading QPushButton:checked { background: #456894; }
QWidget#appHeading QPushButton:disabled { color: #94a3b8; background: #2a4a6e; }
"""

BAR_STYLE = """
QWidget#actionBar { background: #f3f4f6; }
QWidget#actionBar QPushButton {
    padding: 4px 10px;
    background: #ffffff;
    border: 1px solid #d1d5db;
    border-radius: 4px;
}
"""

HINT_STYLE = "color: #64748b;"
WARN_STYLE = "color: #9a3412;"

RESULT_ROWS = (
    ("pddx", "PDD(10)x", 4),
    ("r_50", "R50 (cm)", 3),
    ("dref", "dref (cm)", 3),
    ("kq", "kQ", 5),
    ("pq_gr", "Pgr", 5),
    ("p_tp", "Ptp", 4),
    ("p_ion", "Pion", 4),
    ("p_pol", "Ppol", 4),
    ("m_corrected", "M corrected", 3),
    ("dose_mu_10", "Dose/MU at 10 cm", 4),
    ("dose_mu_dref", "Dose/MU at dref", 4),
    ("dose_mu_dmax", "Dose/MU at dmax", 4),
    ("dose_mu_10_adjusted", "Dose/MU at 10 cm, adjusted", 4),
    ("dose_mu_dref_adjusted", "Dose/MU at dref, adjusted", 4),
    ("dose_mu_dmax_adjusted", "Dose/MU at dmax, adjusted", 4),
)


def themed_font(font: QFont, settings: dict | None = None) -> QFont:
    """Uses Font.family and Font.size. Empty family and size 0 mean the platform font + 3 pt, 13 pt floor."""
    config = font_settings(settings)
    bumped = QFont(font)
    if config["family"]:
        bumped.setFamily(config["family"])
    bumped.setPointSize(config["size"] or max(font.pointSize() + 3, 13))
    return bumped


def format_input(value) -> str:
    if value is None:
        return ""
    return format(float(value), ".12g")


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(HINT_STYLE)
    return label


def _optional_float(edit: QLineEdit, errors: list[str], label: str) -> float | None:
    text = edit.text().strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        errors.append(f"{label} is not a number.")
        return None


def _optional_int(edit: QLineEdit, errors: list[str], label: str) -> int | None:
    text = edit.text().strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        errors.append(f"{label} is not a whole number.")
        return None
    if not number.is_integer():
        errors.append(f"{label} is not a whole number.")
        return None
    return int(number)


def _result_text(result: dict) -> str:
    lines = []
    for key, label, digits in RESULT_ROWS:
        if key in result and result[key] is not None:
            lines.append(f"{label}: {float(result[key]):.{digits}f}")
    return "\n".join(lines)


def _draft_warnings(case: CalibrationCase) -> list[str]:
    if case.temp_value is None or case.press_value is None:
        return []
    try:
        return range_warnings(
            temperature_celsius(case.temp_value, case.temp_unit),
            pressure_kpa(case.press_value, case.press_unit),
        )
    except Exception:
        return []


class ReadingList(QWidget):
    """One column of chamber readings, with a row per repeat."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel(title))
        self._rows = QVBoxLayout()
        layout.addLayout(self._rows)
        add = QPushButton("Add reading")
        add.clicked.connect(lambda: self._add_row(""))
        layout.addWidget(add)
        layout.addStretch(1)
        self._add_row("")

    def _add_row(self, text: str) -> None:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        edit = QLineEdit(text)
        remove = QPushButton("Remove")

        def _remove() -> None:
            if self._rows.count() <= 1:
                edit.clear()
                return
            self._rows.removeWidget(row)
            row.setParent(None)
            row.deleteLater()

        remove.clicked.connect(_remove)
        layout.addWidget(edit, 1)
        layout.addWidget(remove)
        self._rows.addWidget(row)

    def set_values(self, values: list[float]) -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        if not values:
            self._add_row("")
            return
        for value in values:
            self._add_row(format_input(value))

    def values(self) -> tuple[list[float], str | None]:
        numbers: list[float] = []
        for index in range(self._rows.count()):
            row = self._rows.itemAt(index).widget()
            edit = row.findChild(QLineEdit)
            text = edit.text().strip()
            if not text:
                continue
            try:
                numbers.append(float(text))
            except ValueError:
                return [], f"{text!r} is not a reading"
        return numbers, None


class CaseDialog(QDialog):
    def __init__(self, parent, *, catalog: Catalog, machine: Machine, energy: Energy, case: CalibrationCase, on_save):
        super().__init__(parent)
        self.catalog = catalog
        self.machine = machine
        self.energy = energy
        self.case = case
        self.on_save = on_save
        self._loading = True
        self._snapshot = None
        self._result = None
        self._version = ""
        self._warnings: list[str] = []
        self._pdf_path = case.pdf_path
        self.setWindowTitle(f"TG-51  {machine.name}  {energy_label(energy)}")
        self.resize(780, 720)
        self._build()
        self._load(case)
        self._loading = False
        loaded, errors = self._collect()
        if case.status == "calculated" and case.result and not errors and loaded is not None:
            self._snapshot = input_dict(loaded)
            self._result = copy.deepcopy(case.result)
            self._version = case.pylinac_version
            self._warnings = list(case.warnings)
            self._show(case.warnings, [], case.result)
        else:
            self._show(case.warnings, [], None)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form = QWidget()
        form_layout = QVBoxLayout(form)

        setup = QGroupBox("Setup")
        setup_form = QFormLayout(setup)
        setup_form.addRow("Machine", QLabel(self.machine.name))
        setup_form.addRow("Energy", QLabel(energy_label(self.energy)))
        self.date = QDateEdit()
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        self.user_combo = QComboBox()
        self.user_combo.addItem("", "")
        for user in self.catalog.users:
            label = user.name if not user.email else f"{user.name}  <{user.email}>"
            self.user_combo.addItem(label, user.id)
        self.temp = QLineEdit()
        self.temp_unit = QComboBox()
        self.temp_unit.addItem("°C", "C")
        self.temp_unit.addItem("°F", "F")
        self.press = QLineEdit()
        self.press_unit = QComboBox()
        self.press_unit.addItem("mmHg", "mmHg")
        self.press_unit.addItem("kPa", "kPa")
        self.press_unit.addItem("mbar", "mbar")
        setup_form.addRow("Measurement date", self.date)
        setup_form.addRow("Physicist", self.user_combo)
        setup_form.addRow("Temperature", self._unit_row(self.temp, self.temp_unit))
        setup_form.addRow("Pressure", self._unit_row(self.press, self.press_unit))
        setup_form.addRow(_hint("Pylinac accepts 17–27 °C and 91–111 kPa."))
        form_layout.addWidget(setup)

        chamber = QGroupBox("Ion chamber")
        chamber_form = QFormLayout(chamber)
        self.chamber_combo = QComboBox()
        self.chamber_combo.addItem("", "")
        for item in self.catalog.chambers:
            self.chamber_combo.addItem(f"{item.name}  ({model_label(item.model)})", item.id)
        self.chamber_combo.currentIndexChanged.connect(self._chamber_changed)
        self.n_dw = QLineEdit()
        self.p_elec = QLineEdit()
        self.electrometer = QLineEdit()
        chamber_form.addRow("Chamber", self.chamber_combo)
        chamber_form.addRow("NDw (Gy/nC)", self.n_dw)
        chamber_form.addRow("P_elec", self.p_elec)
        chamber_form.addRow("Electrometer", self.electrometer)
        form_layout.addWidget(chamber)

        readings = QGroupBox("Readings")
        readings_layout = QVBoxLayout(readings)
        reading_row = QHBoxLayout()
        self.m_reference = ReadingList("M at Vref")
        self.m_opposite = ReadingList("M at opposite polarity")
        self.m_reduced = ReadingList("M at Vreduced")
        reading_row.addWidget(self.m_reference)
        reading_row.addWidget(self.m_opposite)
        reading_row.addWidget(self.m_reduced)
        readings_layout.addLayout(reading_row)
        volts = QHBoxLayout()
        self.voltage_reference = QLineEdit()
        self.voltage_reduced = QLineEdit()
        self.mu = QLineEdit()
        self.tissue = QLineEdit()
        for label, edit in (
            ("Vref", self.voltage_reference),
            ("Vreduced", self.voltage_reduced),
            ("MU", self.mu),
            ("Tissue correction", self.tissue),
        ):
            column = QVBoxLayout()
            column.addWidget(QLabel(label))
            column.addWidget(edit)
            volts.addLayout(column)
        readings_layout.addLayout(volts)
        self.m_adjusted = ReadingList("M adjusted (optional)")
        readings_layout.addWidget(self.m_adjusted)
        form_layout.addWidget(readings)

        self.photon_box = QGroupBox("Photon beam quality")
        photon_form = QFormLayout(self.photon_box)
        self.measured_pdd10 = QLineEdit()
        self.clinical_pdd10 = QLineEdit()
        self.lead_foil = QComboBox()
        self.lead_foil.addItem("No lead foil", "none")
        self.lead_foil.addItem("Lead foil at 50 cm", "50cm")
        self.lead_foil.addItem("Lead foil at 30 cm", "30cm")
        photon_form.addRow("Measured PDD(10)", self.measured_pdd10)
        photon_form.addRow("Clinical PDD(10)", self.clinical_pdd10)
        photon_form.addRow("Lead foil", self.lead_foil)
        form_layout.addWidget(self.photon_box)

        self.electron_box = QGroupBox("Electron beam quality")
        electron_form = QFormLayout(self.electron_box)
        self.method = QComboBox()
        self.method.addItem("Legacy TG-51", "legacy")
        self.method.addItem("Modern (Muir & Rogers)", "modern")
        self.method.currentIndexChanged.connect(self._sync_method)
        self.modern_warning = QLabel(
            "These kQ values follow Muir & Rogers and are expected in a future addendum. "
            "They are not official and can differ by up to 1%."
        )
        self.modern_warning.setWordWrap(True)
        self.modern_warning.setStyleSheet(WARN_STYLE)
        self.clinical_pdd = QLineEdit()
        self.cone = QLineEdit()
        self.cone.setPlaceholderText("10x10")
        self.i_50 = QLineEdit()
        self.k_ecal = QLineEdit()
        self.m_gradient = ReadingList("M at dref + 0.5 rcav")
        electron_form.addRow("Method", self.method)
        electron_form.addRow(self.modern_warning)
        electron_form.addRow("Clinical PDD", self.clinical_pdd)
        electron_form.addRow("Cone", self.cone)
        electron_form.addRow("I50 (cm)", self.i_50)
        self.kecal_label = QLabel("k_ecal")
        electron_form.addRow(self.kecal_label, self.k_ecal)
        electron_form.addRow(self.m_gradient)
        form_layout.addWidget(self.electron_box)
        self.photon_box.setVisible(self.energy.modality == "photon")
        self.electron_box.setVisible(self.energy.modality == "electron")

        form_layout.addStretch(1)
        scroll.setWidget(form)
        root.addWidget(scroll, 1)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(WARN_STYLE)
        self.results = QLabel("Draft. Calculate to fill kQ and dose/MU.")
        self.results.setWordWrap(True)
        self.results.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.results.setStyleSheet(HINT_STYLE)
        root.addWidget(self.warning_label)
        root.addWidget(self.results)

        buttons = QHBoxLayout()
        calculate_btn = QPushButton("Calculate")
        save_btn = QPushButton("Save")
        pdf_btn = QPushButton("Save PDF")
        cancel_btn = QPushButton("Cancel")
        calculate_btn.clicked.connect(self._on_calculate)
        save_btn.clicked.connect(lambda: self.save_case(close=True))
        pdf_btn.clicked.connect(self._on_save_pdf)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(calculate_btn)
        buttons.addWidget(save_btn)
        buttons.addWidget(pdf_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _unit_row(self, edit: QLineEdit, unit: QComboBox) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(unit)
        return row

    def _select(self, combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _load(self, case: CalibrationCase) -> None:
        parsed = QDate.fromString(case.measurement_date, "yyyy-MM-dd")
        self.date.setDate(parsed if parsed.isValid() else QDate.currentDate())
        if case.user_id and self.user_combo.findData(case.user_id) < 0:
            self.user_combo.addItem("(missing user)", case.user_id)
        self._select(self.user_combo, case.user_id)
        self.temp.setText(format_input(case.temp_value))
        self._select(self.temp_unit, case.temp_unit if case.temp_unit in ("C", "F") else "C")
        self.press.setText(format_input(case.press_value))
        self._select(self.press_unit, case.press_unit if case.press_unit in ("mmHg", "kPa", "mbar") else "mmHg")
        if case.chamber_id and self.chamber_combo.findData(case.chamber_id) < 0:
            self.chamber_combo.addItem("(missing chamber)", case.chamber_id)
        self._select(self.chamber_combo, case.chamber_id)
        self.n_dw.setText(format_input(case.n_dw))
        self.p_elec.setText(format_input(case.p_elec))
        self.electrometer.setText(case.electrometer)
        self.m_reference.set_values(case.m_reference)
        self.m_opposite.set_values(case.m_opposite)
        self.m_reduced.set_values(case.m_reduced)
        self.m_adjusted.set_values(case.m_reference_adjusted)
        self.voltage_reference.setText("" if case.voltage_reference is None else str(case.voltage_reference))
        self.voltage_reduced.setText("" if case.voltage_reduced is None else str(case.voltage_reduced))
        self.mu.setText("" if case.mu is None else str(case.mu))
        self.tissue.setText(format_input(1.0 if case.tissue_correction is None else case.tissue_correction))
        self.measured_pdd10.setText(format_input(case.measured_pdd10))
        self.clinical_pdd10.setText(format_input(case.clinical_pdd10))
        self._select(self.lead_foil, case.lead_foil or "none")
        self._select(self.method, case.electron_method or "legacy")
        self.clinical_pdd.setText(format_input(case.clinical_pdd))
        self.cone.setText(case.cone)
        self.i_50.setText(format_input(case.i_50))
        self.k_ecal.setText(format_input(case.k_ecal))
        self.m_gradient.set_values(case.m_gradient)
        self._sync_method()

    def _chamber_changed(self) -> None:
        if self._loading:
            return
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        if chamber is None:
            return
        self.n_dw.setText(format_input(chamber.n_dw))
        self.p_elec.setText(format_input(chamber.p_elec))
        self.electrometer.setText(chamber.electrometer)
        if not self.k_ecal.text().strip():
            hint = kecal_hint(chamber)
            if hint is not None:
                self.k_ecal.setText(format_input(hint))

    def _sync_method(self) -> None:
        legacy = self.method.currentData() == "legacy"
        self.kecal_label.setVisible(legacy)
        self.k_ecal.setVisible(legacy)
        self.m_gradient.setVisible(legacy)
        self.modern_warning.setVisible(not legacy)

    def _readings(self, widget: ReadingList, errors: list[str], label: str) -> list[float]:
        values, error = widget.values()
        if error:
            errors.append(f"{label}: {error}.")
        return values

    def _collect(self) -> tuple[CalibrationCase | None, list[str]]:
        errors: list[str] = []
        case = self.case.clone()
        case.measurement_date = self.date.date().toString("yyyy-MM-dd")
        case.user_id = str(self.user_combo.currentData() or "")
        case.temp_value = _optional_float(self.temp, errors, "Temperature")
        case.temp_unit = str(self.temp_unit.currentData() or "C")
        case.press_value = _optional_float(self.press, errors, "Pressure")
        case.press_unit = str(self.press_unit.currentData() or "kPa")
        case.chamber_id = str(self.chamber_combo.currentData() or "")
        case.n_dw = _optional_float(self.n_dw, errors, "NDw")
        case.p_elec = _optional_float(self.p_elec, errors, "P_elec")
        case.electrometer = self.electrometer.text().strip()
        case.m_reference = self._readings(self.m_reference, errors, "M at Vref")
        case.m_opposite = self._readings(self.m_opposite, errors, "M at opposite polarity")
        case.m_reduced = self._readings(self.m_reduced, errors, "M at Vreduced")
        case.m_reference_adjusted = self._readings(self.m_adjusted, errors, "M adjusted")
        case.voltage_reference = _optional_int(self.voltage_reference, errors, "Vref")
        case.voltage_reduced = _optional_int(self.voltage_reduced, errors, "Vreduced")
        case.mu = _optional_int(self.mu, errors, "MU")
        case.tissue_correction = _optional_float(self.tissue, errors, "Tissue correction")
        case.measured_pdd10 = _optional_float(self.measured_pdd10, errors, "Measured PDD(10)")
        case.clinical_pdd10 = _optional_float(self.clinical_pdd10, errors, "Clinical PDD(10)")
        case.lead_foil = str(self.lead_foil.currentData() or "none")
        case.electron_method = str(self.method.currentData() or "legacy")
        case.clinical_pdd = _optional_float(self.clinical_pdd, errors, "Clinical PDD")
        case.cone = self.cone.text().strip()
        case.i_50 = _optional_float(self.i_50, errors, "I50")
        case.k_ecal = _optional_float(self.k_ecal, errors, "k_ecal")
        case.m_gradient = self._readings(self.m_gradient, errors, "Gradient reading")
        if errors:
            return None, errors
        return case, []

    def _show(self, warnings: list[str], errors: list[str], result: dict | None) -> None:
        self.warning_label.setText("\n".join(warnings))
        if errors:
            self.results.setStyleSheet(WARN_STYLE)
            self.results.setText("\n".join(errors))
            return
        if result:
            self.results.setStyleSheet("")
            self.results.setText(_result_text(result))
            return
        self.results.setStyleSheet(HINT_STYLE)
        self.results.setText("Draft. Calculate to fill kQ and dose/MU.")

    def run_calculation(self) -> CalcOutcome:
        case, errors = self._collect()
        if errors or case is None:
            return CalcOutcome(errors=errors, warnings=[], result=None, pylinac_version="", calculator=None)
        user = self.catalog.user(case.user_id)
        chamber = self.catalog.chamber(case.chamber_id) or Chamber(id="", name="")
        return calculate(
            case,
            institution=self.catalog.institution,
            physicist=user.name if user else "",
            unit=self.machine.name,
            energy=self.energy,
            chamber=chamber,
        )

    def apply_outcome(self, outcome: CalcOutcome) -> None:
        self._show(outcome.warnings, outcome.errors, outcome.result)
        if outcome.errors:
            self._snapshot = None
            self._result = None
            self._version = ""
            self._warnings = list(outcome.warnings)
            return
        case, errors = self._collect()
        self._snapshot = None if errors or case is None else input_dict(case)
        self._result = outcome.result
        self._version = outcome.pylinac_version
        self._warnings = list(outcome.warnings)

    def save_case(self, *, close: bool) -> bool:
        case, errors = self._collect()
        if errors or case is None:
            QMessageBox.warning(self, "TG-51 case", "\n".join(errors or ["The case could not be read."]))
            return False
        if self._snapshot == input_dict(case) and self._result is not None:
            case.status = "calculated"
            case.result = self._result
            case.pylinac_version = self._version
            case.warnings = list(self._warnings)
        else:
            case.status = "draft"
            case.result = None
            case.pylinac_version = ""
            case.warnings = _draft_warnings(case)
        case.pdf_path = self._pdf_path
        self.case = case
        self.on_save(case)
        if close:
            self.accept()
        return True

    def _on_calculate(self) -> None:
        outcome = self.run_calculation()
        self.apply_outcome(outcome)
        if outcome.errors:
            QMessageBox.warning(self, "TG-51", "\n".join(outcome.warnings + outcome.errors))

    def _on_save_pdf(self) -> None:
        outcome = self.run_calculation()
        self.apply_outcome(outcome)
        if outcome.errors or outcome.calculator is None:
            QMessageBox.warning(self, "Save PDF", "\n".join(outcome.errors or ["Calculate the case before saving a PDF."]))
            return
        default_name = f"{self.machine.name} {energy_label(self.energy)} {self.date.date().toString('yyyy-MM-dd')} TG-51.pdf"
        path, _selected = QFileDialog.getSaveFileName(self, "Save TG-51 PDF", default_name, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        try:
            write_pdf(outcome.calculator, path, outcome.warnings)
        except Exception as exc:
            QMessageBox.warning(self, "Save PDF", str(exc))
            return
        self._pdf_path = path
        self.save_case(close=False)


class UserDialog(QDialog):
    def __init__(self, user: User | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User")
        self.result_user: User | None = None
        layout = QFormLayout(self)
        self.name = QLineEdit(user.name if user else "")
        self.email = QLineEdit(user.email if user else "")
        self._id = user.id if user else new_id()
        layout.addRow("Name", self.name)
        layout.addRow("Email", self.email)
        layout.addRow(self._buttons())

    def _buttons(self) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        layout.addStretch(1)
        layout.addWidget(ok)
        layout.addWidget(cancel)
        return row

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "User", "Enter a name.")
            return
        self.result_user = User(id=self._id, name=name, email=self.email.text().strip())
        self.accept()


class ChamberDialog(QDialog):
    def __init__(self, chamber: Chamber | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ion chamber")
        self.resize(520, 460)
        self.result_chamber: Chamber | None = None
        self._id = chamber.id if chamber else new_id()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(chamber.name if chamber else "")
        self.serial = QLineEdit(chamber.serial if chamber else "")
        self.model = QComboBox()
        self.model.addItem("Custom", "custom")
        for model_name, label in pylinac_model_choices():
            self.model.addItem(label, model_name)
        current = chamber.model if chamber else "30013"
        if current and self.model.findData(current) < 0:
            self.model.addItem(current, current)
        index = self.model.findData(current)
        self.model.setCurrentIndex(index if index >= 0 else 0)
        self.model.currentIndexChanged.connect(self._sync_custom)
        self.n_dw = QLineEdit(format_input(chamber.n_dw) if chamber else "")
        self.p_elec = QLineEdit(format_input(chamber.p_elec) if chamber else "")
        self.electrometer = QLineEdit(chamber.electrometer if chamber else "")
        self.lab = QLineEdit(chamber.calibration_lab if chamber else "")
        self.cal_date = QLineEdit(chamber.calibration_date if chamber else "")
        self.cal_date.setPlaceholderText("yyyy-mm-dd")
        form.addRow("Name", self.name)
        form.addRow("Serial", self.serial)
        form.addRow("Model", self.model)
        form.addRow("NDw (Gy/nC)", self.n_dw)
        form.addRow("P_elec", self.p_elec)
        form.addRow("Electrometer", self.electrometer)
        form.addRow("Calibration lab", self.lab)
        form.addRow("Calibration date", self.cal_date)
        layout.addLayout(form)

        self.custom = QGroupBox("Custom coefficients")
        custom_form = QFormLayout(self.custom)
        self._photon = {}
        self._electron = {}
        photon = (chamber.photon_coefficients if chamber else None) or {}
        electron = (chamber.electron_coefficients if chamber else None) or {}
        for key in ("a", "b", "c", "a_prime", "b_prime", "c_prime", "d_prime"):
            edit = QLineEdit(format_input(photon.get(key)))
            self._photon[key] = edit
            custom_form.addRow(f"Photon {key}", edit)
        for key in ("kq_ecal", "a", "b", "c"):
            edit = QLineEdit(format_input(electron.get(key)))
            self._electron[key] = edit
            custom_form.addRow(f"Electron {key}", edit)
        layout.addWidget(self.custom)
        self._sync_custom()
        buttons = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch(1)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

    def _sync_custom(self) -> None:
        self.custom.setVisible(self.model.currentData() == "custom")

    def _block(self, edits: dict, keys: tuple[str, ...], errors: list[str], title: str) -> dict | None:
        block = {}
        any_value = False
        for key in keys:
            text = edits[key].text().strip()
            if not text:
                block[key] = None
                continue
            try:
                block[key] = float(text)
            except ValueError:
                errors.append(f"{title} {key} is not a number.")
                continue
            any_value = True
        return block if any_value else None

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Ion chamber", "Enter a name.")
            return
        errors: list[str] = []
        model = str(self.model.currentData() or "")
        photon = electron = None
        if model == "custom":
            photon = self._block(self._photon, ("a", "b", "c", "a_prime", "b_prime", "c_prime", "d_prime"), errors, "Photon")
            electron = self._block(self._electron, ("kq_ecal", "a", "b", "c"), errors, "Electron")
        if errors:
            QMessageBox.warning(self, "Ion chamber", "\n".join(errors))
            return
        self.result_chamber = Chamber(
            id=self._id,
            name=name,
            serial=self.serial.text().strip(),
            model=model,
            n_dw=_optional_float(self.n_dw, errors, "NDw"),
            p_elec=_optional_float(self.p_elec, errors, "P_elec"),
            electrometer=self.electrometer.text().strip(),
            calibration_lab=self.lab.text().strip(),
            calibration_date=self.cal_date.text().strip(),
            photon_coefficients=photon,
            electron_coefficients=electron,
        )
        if errors:
            QMessageBox.warning(self, "Ion chamber", "\n".join(errors))
            return
        self.accept()


class MachineDialog(QDialog):
    def __init__(self, machine: Machine | None, energy_in_use, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Machine")
        self.resize(560, 420)
        self.energy_in_use = energy_in_use
        self.result_machine: Machine | None = None
        self._id = machine.id if machine else new_id()
        self._original = {energy.id: energy.modality for energy in (machine.energies if machine else [])}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(machine.name if machine else "")
        self.manufacturer = QLineEdit(machine.manufacturer if machine else "")
        self.model = QLineEdit(machine.model if machine else "")
        self.serial = QLineEdit(machine.serial if machine else "")
        self.comment = QLineEdit(machine.comment if machine else "")
        form.addRow("Name", self.name)
        form.addRow("Manufacturer", self.manufacturer)
        form.addRow("Model", self.model)
        form.addRow("Serial", self.serial)
        form.addRow("Comment", self.comment)
        layout.addLayout(form)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Modality", "Nominal", "FFF"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add energy")
        remove = QPushButton("Remove energy")
        add.clicked.connect(lambda: self._add_energy(Energy(id=new_id(), modality="photon", nominal=6, fff=False)))
        remove.clicked.connect(self._remove_energy)
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch(1)
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)
        starting = list(machine.energies) if machine else [Energy(id=new_id(), modality="photon", nominal=6, fff=False)]
        for energy in starting:
            self._add_energy(energy)

    def _add_energy(self, energy: Energy) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        modality = QComboBox()
        modality.addItem("Photon", "photon")
        modality.addItem("Electron", "electron")
        modality.setCurrentIndex(1 if energy.modality == "electron" else 0)
        modality.setProperty("energy_id", energy.id)
        nominal = QLineEdit(format_input(energy.nominal))
        fff = QCheckBox("FFF")
        fff.setChecked(bool(energy.fff) and energy.modality == "photon")
        modality.currentIndexChanged.connect(lambda _index, combo=modality, box=fff: self._sync_fff(combo, box))
        self._sync_fff(modality, fff)
        self.table.setCellWidget(row, 0, modality)
        self.table.setCellWidget(row, 1, nominal)
        self.table.setCellWidget(row, 2, fff)

    def _sync_fff(self, modality: QComboBox, fff: QCheckBox) -> None:
        electron = modality.currentData() == "electron"
        fff.setEnabled(not electron)
        if electron:
            fff.setChecked(False)

    def _remove_energy(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Machine", "Enter a name.")
            return
        energies: list[Energy] = []
        seen = set()
        for row in range(self.table.rowCount()):
            modality = self.table.cellWidget(row, 0)
            nominal_edit = self.table.cellWidget(row, 1)
            fff = self.table.cellWidget(row, 2)
            text = nominal_edit.text().strip()
            try:
                nominal = float(text)
            except ValueError:
                QMessageBox.warning(self, "Machine", "Enter a nominal energy for each row.")
                return
            if nominal <= 0:
                QMessageBox.warning(self, "Machine", "Nominal energy must be greater than zero.")
                return
            mode = str(modality.currentData())
            flag = bool(fff.isChecked()) if mode == "photon" else False
            key = (mode, nominal, flag)
            if key in seen:
                QMessageBox.warning(self, "Machine", "Two energies on this machine are the same.")
                return
            seen.add(key)
            energies.append(Energy(id=str(modality.property("energy_id")), modality=mode, nominal=nominal, fff=flag))
        for energy in energies:
            previous = self._original.get(energy.id)
            if previous and previous != energy.modality and self.energy_in_use(energy.id):
                QMessageBox.warning(self, "Machine", "This energy has saved cases, so its modality cannot change.")
                return
        kept = {energy.id for energy in energies}
        for energy_id in self._original:
            if energy_id not in kept:
                message = self.energy_in_use(energy_id)
                if message:
                    QMessageBox.warning(self, "Machine", message)
                    return
        self.result_machine = Machine(
            id=self._id,
            name=name,
            manufacturer=self.manufacturer.text().strip(),
            model=self.model.text().strip(),
            serial=self.serial.text().strip(),
            comment=self.comment.text().strip(),
            energies=energies,
        )
        self.accept()


class SettingsDialog(QDialog):
    def __init__(self, catalog: Catalog, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        layout = QFormLayout(self)
        self.institution = QLineEdit(catalog.institution)
        self.family = QLineEdit(catalog.font_family)
        self.size = QLineEdit(str(catalog.font_size))
        layout.addRow("Institution", self.institution)
        layout.addRow("Font family", self.family)
        layout.addRow("Font size", self.size)
        layout.addRow(_hint("Leave the family blank and the size at 0 to use the platform font plus 3 pt, with a 13 pt floor."))
        row = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addRow(row)

    def values(self) -> tuple[str, str, int] | None:
        text = self.size.text().strip() or "0"
        try:
            size = int(text)
        except ValueError:
            return None
        if size < 0:
            return None
        return self.institution.text().strip(), self.family.text().strip(), size


def _action_bar(*buttons: QPushButton) -> QWidget:
    bar = QWidget()
    bar.setObjectName("actionBar")
    bar.setStyleSheet(BAR_STYLE)
    layout = QHBoxLayout(bar)
    layout.setContentsMargins(8, 4, 8, 4)
    for button in buttons:
        layout.addWidget(button)
    layout.addStretch(1)
    return bar


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setSelectionBehavior(QTableWidget.SelectRows)
    table.setSelectionMode(QTableWidget.SingleSelection)
    table.setEditTriggers(QTableWidget.NoEditTriggers)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.verticalHeader().setVisible(False)
    return table


def _fill_table(table: QTableWidget, rows: list[tuple[str, list[str]]], selected_id: str) -> None:
    table.setRowCount(0)
    select = -1
    for record_id, cells in rows:
        row = table.rowCount()
        table.insertRow(row)
        for column, text in enumerate(cells):
            item = QTableWidgetItem(text)
            item.setData(Qt.UserRole, record_id)
            table.setItem(row, column, item)
        if record_id == selected_id:
            select = row
    if select >= 0:
        table.selectRow(select)


def _upsert(items, record):
    updated = []
    found = False
    for item in items:
        if item.id == record.id:
            updated.append(record)
            found = True
        else:
            updated.append(item)
    if not found:
        updated.append(record)
    return updated


def _selected_id(table: QTableWidget) -> str:
    row = table.currentRow()
    if row < 0:
        return ""
    item = table.item(row, 0)
    if item is None:
        return ""
    return str(item.data(Qt.UserRole) or "")


class MainWindow(QMainWindow):
    def __init__(self, settings_path: Path | None = None, cases_dir: Path | None = None):
        super().__init__()
        self.settings_file = Path(settings_path) if settings_path else app_settings.settings_path()
        self.store = CaseStore(cases_dir if cases_dir is not None else app_settings.cases_dir())
        self.catalog = Catalog.from_settings(load_settings(self.settings_file))
        self.setWindowTitle("TG-51")
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_heading())
        self.stack = QWidget()
        stack_layout = QVBoxLayout(self.stack)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        self.pages = QFrame()
        self.page_stack = QVBoxLayout(self.pages)
        self.page_stack.setContentsMargins(0, 0, 0, 0)
        self._page_widgets: list[QWidget] = []
        self._build_pages()
        stack_layout.addWidget(self.pages)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)
        self._refresh()

    def _build_heading(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("appHeading")
        bar.setStyleSheet(HEADING_STYLE)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)
        title = QLabel("TG-51")
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.institution_label = QLabel()
        layout.addWidget(title)
        layout.addWidget(self.institution_label)
        layout.addStretch(1)
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        for index, name in enumerate(("Calibrations", "Machines", "Ion Chambers", "Users")):
            button = QPushButton(name)
            button.setCheckable(True)
            self.nav.addButton(button, index)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
        self.nav.buttonClicked.connect(self._show_page)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self._edit_settings)
        layout.addWidget(settings_btn)
        return bar

    def _show_page(self, button) -> None:
        index = self.nav.id(button)
        for page_index, page in enumerate(self._page_widgets):
            page.setVisible(page_index == index)

    def _build_pages(self) -> None:
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda *_args: self._fill_cases())
        self.case_table = _table(["Date", "Physicist", "Chamber", "kQ", "Dose/MU at dmax", "Status"])
        self.case_table.doubleClicked.connect(lambda *_args: self._edit_case(self._selected_case()))
        new_case = QPushButton("New")
        edit_case = QPushButton("Edit")
        duplicate_case = QPushButton("Duplicate")
        delete_case = QPushButton("Delete")
        open_pdf = QPushButton("Open PDF")
        new_case.clicked.connect(lambda: self._edit_case(None))
        edit_case.clicked.connect(lambda: self._edit_case(self._selected_case()))
        duplicate_case.clicked.connect(self._duplicate_case)
        delete_case.clicked.connect(self._delete_case)
        open_pdf.clicked.connect(self._open_pdf)
        self._case_buttons = {
            "new": new_case,
            "edit": edit_case,
            "duplicate": duplicate_case,
            "delete": delete_case,
            "pdf": open_pdf,
        }
        cases = QWidget()
        cases_layout = QVBoxLayout(cases)
        cases_layout.setContentsMargins(0, 0, 0, 0)
        cases_layout.addWidget(_action_bar(new_case, edit_case, duplicate_case, delete_case, open_pdf))
        cases_layout.addWidget(self.case_table, 1)
        splitter = QSplitter()
        splitter.addWidget(self.tree)
        splitter.addWidget(cases)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        self.tree.setMinimumWidth(220)
        self._add_page(splitter, "Select a machine energy, then create or edit its TG-51 cases.")

        self.machine_table = _table(["Name", "Manufacturer", "Model", "Energies"])
        self.machine_table.doubleClicked.connect(lambda *_args: self._edit_machine())
        add_m = QPushButton("New")
        edit_m = QPushButton("Edit")
        del_m = QPushButton("Delete")
        add_m.clicked.connect(lambda: self._edit_machine(new=True))
        edit_m.clicked.connect(self._edit_machine)
        del_m.clicked.connect(lambda: self._delete_record("machine"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.addWidget(self.machine_table)
        self._add_page(page, "Each machine has its own energies. Edit a machine to add or remove them.", _action_bar(add_m, edit_m, del_m))

        self.chamber_table = _table(["Name", "Model", "Serial", "NDw", "Electrometer"])
        self.chamber_table.doubleClicked.connect(lambda *_args: self._edit_chamber())
        add_c = QPushButton("New")
        edit_c = QPushButton("Edit")
        del_c = QPushButton("Delete")
        add_c.clicked.connect(lambda: self._edit_chamber(new=True))
        edit_c.clicked.connect(self._edit_chamber)
        del_c.clicked.connect(lambda: self._delete_record("chamber"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.addWidget(self.chamber_table)
        self._add_page(page, "Chambers keep the calibration-lab NDw, P_elec, and electrometer.", _action_bar(add_c, edit_c, del_c))

        self.user_table = _table(["Name", "Email"])
        self.user_table.doubleClicked.connect(lambda *_args: self._edit_user())
        add_u = QPushButton("New")
        edit_u = QPushButton("Edit")
        del_u = QPushButton("Delete")
        add_u.clicked.connect(lambda: self._edit_user(new=True))
        edit_u.clicked.connect(self._edit_user)
        del_u.clicked.connect(lambda: self._delete_record("user"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.addWidget(self.user_table)
        self._add_page(page, "The physicist on a case is chosen from this list.", _action_bar(add_u, edit_u, del_u))
        self._show_page(self.nav.button(0))

    def _add_page(self, body: QWidget, hint: str, bar: QWidget | None = None) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        if bar is not None:
            layout.addWidget(bar)
        hint_label = QLabel(hint)
        hint_label.setWordWrap(True)
        hint_label.setStyleSheet("color: #64748b; padding: 6px 12px;")
        layout.addWidget(hint_label)
        if body.parent() is None:
            layout.addWidget(body, 1)
        else:
            layout.addWidget(body, 1)
        self.page_stack.addWidget(page)
        self._page_widgets.append(page)

    def _save_catalog(self) -> None:
        save_settings(self.catalog.to_settings(), self.settings_file)
        self._refresh()

    def _refresh(self) -> None:
        self.institution_label.setText(self.catalog.institution)
        self.institution_label.setVisible(bool(self.catalog.institution))
        self._fill_tree()
        self._fill_machines()
        self._fill_chambers()
        self._fill_users()

    def _fill_tree(self) -> None:
        machine, energy = self._current_energy()
        selected = (machine.id if machine else "", energy.id if energy else "")
        self.tree.blockSignals(True)
        self.tree.clear()
        target = None
        first = None
        for item in self.catalog.machines:
            parent = QTreeWidgetItem([item.name])
            parent.setData(0, Qt.UserRole, item.id)
            self.tree.addTopLevelItem(parent)
            parent.setExpanded(True)
            for beam in item.energies:
                child = QTreeWidgetItem([energy_label(beam)])
                child.setData(0, Qt.UserRole, beam.id)
                child.setData(0, Qt.UserRole + 1, item.id)
                parent.addChild(child)
                if first is None:
                    first = child
                if item.id == selected[0] and beam.id == selected[1]:
                    target = child
        self.tree.blockSignals(False)
        chosen = target or first
        if chosen is not None:
            self.tree.setCurrentItem(chosen)
        self._fill_cases()

    def _current_energy(self) -> tuple[Machine | None, Energy | None]:
        item = self.tree.currentItem()
        if item is None or item.parent() is None:
            return None, None
        machine = self.catalog.machine(str(item.data(0, Qt.UserRole + 1) or ""))
        if machine is None:
            return None, None
        return machine, machine.energy(str(item.data(0, Qt.UserRole) or ""))

    def _fill_cases(self) -> None:
        machine, energy = self._current_energy()
        selected = _selected_id(self.case_table)
        rows = []
        if machine is not None and energy is not None:
            for case in self.store.for_energy(machine.id, energy.id):
                user = self.catalog.user(case.user_id)
                chamber = self.catalog.chamber(case.chamber_id)
                result = case.result or {}
                kq = "" if result.get("kq") is None else f"{float(result['kq']):.5f}"
                dose = "" if result.get("dose_mu_dmax") is None else f"{float(result['dose_mu_dmax']):.4f}"
                rows.append(
                    (
                        case.id,
                        [
                            case.measurement_date,
                            user.name if user else "",
                            chamber.name if chamber else "",
                            kq,
                            dose,
                            "Calculated" if case.status == "calculated" else "Draft",
                        ],
                    )
                )
        _fill_table(self.case_table, rows, selected)
        has_energy = machine is not None and energy is not None
        has_case = bool(_selected_id(self.case_table))
        self._case_buttons["new"].setEnabled(has_energy)
        for key in ("edit", "duplicate", "delete", "pdf"):
            self._case_buttons[key].setEnabled(has_case)

    def _selected_case(self) -> CalibrationCase | None:
        case_id = _selected_id(self.case_table)
        if not case_id:
            return None
        return next((case for case in self.store.load_all() if case.id == case_id), None)

    def _edit_case(self, case: CalibrationCase | None) -> None:
        machine, energy = self._current_energy()
        if machine is None or energy is None:
            return
        if case is None:
            case = CalibrationCase.new(machine.id, energy.id)
        dialog = CaseDialog(
            self,
            catalog=self.catalog,
            machine=machine,
            energy=energy,
            case=case,
            on_save=self.store.save,
        )
        dialog.exec_()
        self._fill_cases()

    def _duplicate_case(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        copy_case = case.clone()
        copy_case.id = new_id()
        copy_case.pdf_path = ""
        self._edit_case(copy_case)

    def _delete_case(self) -> None:
        case = self._selected_case()
        if case is None:
            return
        label = describe_case(case, self.catalog)
        if QMessageBox.question(self, "Delete case", f"Delete {label}?") != QMessageBox.Yes:
            return
        self.store.delete(case)
        self._fill_cases()

    def _open_pdf(self) -> None:
        case = self._selected_case()
        if case is None or not case.pdf_path:
            QMessageBox.information(self, "Open PDF", "This case has no saved PDF.")
            return
        if not Path(case.pdf_path).is_file():
            QMessageBox.information(self, "Open PDF", "The saved PDF is not at that path anymore.")
            return
        if hasattr(os, "startfile"):
            os.startfile(case.pdf_path)
            return
        QMessageBox.information(self, "Open PDF", case.pdf_path)

    def _fill_machines(self) -> None:
        selected = _selected_id(self.machine_table)
        rows = []
        for machine in self.catalog.machines:
            summary = ", ".join(energy_label(energy) for energy in machine.energies)
            rows.append((machine.id, [machine.name, machine.manufacturer, machine.model, summary]))
        _fill_table(self.machine_table, rows, selected)

    def _fill_chambers(self) -> None:
        selected = _selected_id(self.chamber_table)
        rows = []
        for chamber in self.catalog.chambers:
            rows.append(
                (
                    chamber.id,
                    [
                        chamber.name,
                        model_label(chamber.model),
                        chamber.serial,
                        format_input(chamber.n_dw),
                        chamber.electrometer,
                    ],
                )
            )
        _fill_table(self.chamber_table, rows, selected)

    def _fill_users(self) -> None:
        selected = _selected_id(self.user_table)
        rows = [(user.id, [user.name, user.email]) for user in self.catalog.users]
        _fill_table(self.user_table, rows, selected)

    def _edit_machine(self, new: bool = False) -> None:
        current = None if new else self.catalog.machine(_selected_id(self.machine_table))
        if not new and current is None:
            QMessageBox.information(self, "Machines", "Select a machine first.")
            return
        dialog = MachineDialog(current, lambda energy_id: deletion_block(self.store, self.catalog, "energy", energy_id), self)
        if dialog.exec_() != QDialog.Accepted or dialog.result_machine is None:
            return
        self.catalog.machines = _upsert(self.catalog.machines, dialog.result_machine)
        self._save_catalog()

    def _edit_chamber(self, new: bool = False) -> None:
        current = None if new else self.catalog.chamber(_selected_id(self.chamber_table))
        if not new and current is None:
            QMessageBox.information(self, "Ion Chambers", "Select an ion chamber first.")
            return
        dialog = ChamberDialog(current, self)
        if dialog.exec_() != QDialog.Accepted or dialog.result_chamber is None:
            return
        self.catalog.chambers = _upsert(self.catalog.chambers, dialog.result_chamber)
        self._save_catalog()

    def _edit_user(self, new: bool = False) -> None:
        current = None if new else self.catalog.user(_selected_id(self.user_table))
        if not new and current is None:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        dialog = UserDialog(current, self)
        if dialog.exec_() != QDialog.Accepted or dialog.result_user is None:
            return
        self.catalog.users = _upsert(self.catalog.users, dialog.result_user)
        self._save_catalog()

    def _delete_record(self, kind: str) -> None:
        if kind == "machine":
            record_id = _selected_id(self.machine_table)
            title = "Machines"
        elif kind == "chamber":
            record_id = _selected_id(self.chamber_table)
            title = "Ion Chambers"
        else:
            record_id = _selected_id(self.user_table)
            title = "Users"
        if not record_id:
            QMessageBox.information(self, title, "Select a row first.")
            return
        message = deletion_block(self.store, self.catalog, kind, record_id)
        if message:
            QMessageBox.information(self, title, message)
            return
        if QMessageBox.question(self, title, "Delete the selected row?") != QMessageBox.Yes:
            return
        if kind == "machine":
            self.catalog.machines = [item for item in self.catalog.machines if item.id != record_id]
        elif kind == "chamber":
            self.catalog.chambers = [item for item in self.catalog.chambers if item.id != record_id]
        else:
            self.catalog.users = [item for item in self.catalog.users if item.id != record_id]
        self._save_catalog()

    def _edit_settings(self) -> None:
        dialog = SettingsDialog(self.catalog, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        if values is None:
            QMessageBox.warning(self, "Settings", "Font size must be a whole number, 0 or greater.")
            return
        self.catalog.institution, self.catalog.font_family, self.catalog.font_size = values
        self._save_catalog()
        app = QApplication.instance()
        if app is not None:
            app.setFont(
                themed_font(
                    QFont(),
                    {"Font": {"family": self.catalog.font_family, "size": self.catalog.font_size}},
                )
            )
