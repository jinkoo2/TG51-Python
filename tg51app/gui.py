"""PyQt5 window for TG-51 catalogs and calibration cases."""

from __future__ import annotations

import copy
import os
import re
from datetime import datetime
from pathlib import Path

from PyQt5.QtCore import QDate, Qt, QTimer
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
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import app_settings
from .app_settings import (
    font_settings,
    history_warn_percent,
    load_settings,
    load_window_state,
    save_settings,
    save_window_state,
    valid_ranges,
)
from .field_checks import (
    FIELD_LABELS,
    FIELD_UNITS,
    READING_FIELDS,
    READING_RANGE_KEY,
    canonical_values,
    history_messages,
    range_message,
)
from .calc import (
    CalcOutcome,
    calculate,
    kecal_hint,
    chamber_kecal,
    model_label,
    pressure_kpa,
    ptp_text,
    ptp_value,
    photon_kq_text,
    photon_dose_text,
    photon_kq_value,
    electron_dose_text,
    electron_dref,
    electron_quality_text,
    electron_r50,
    electron_kq_value,
    pylinac_model_choices,
    range_warnings,
    readings_correction_text,
    m_adjusted_corrected_value,
    m_corrected_value,
    temperature_celsius,
    write_pdf,
)
from .models import (
    Calibration,
    CalibrationCase,
    CaseStore,
    Catalog,
    CHAMBER_CYLINDER,
    CHAMBER_PARALLEL_PLATE,
    Chamber,
    Electrometer,
    Energy,
    Machine,
    User,
    deletion_block,
    chamber_type_label,
    describe_case,
    electrometer_label,
    energy_label,
    input_dict,
    new_id,
    parse_calibration_date,
)

_LEGACY_ELECTROMETER = "legacy:"

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
RANGE_EDIT_STYLE = "QLineEdit { background: #fde8e8; border: 1px solid #dc2626; }"
HISTORY_EDIT_STYLE = "QLineEdit { background: #fff7e6; border: 1px solid #d97706; }"
NEEDED_EDIT_STYLE = "QLineEdit { background: #ffedd5; border: 1px solid #ea580c; }"
CALC_DEBOUNCE_MS = 400
_BLANK_CALC_ERRORS = {
    "Enter a temperature.",
    "Enter a pressure.",
    "Enter PDD(10)x.",
    "Enter clinical PDD(10).",
    "Enter clinical PDD.",
    "Enter I50.",
    "Enter at least one reference reading.",
    "Enter at least one opposite-polarity reading.",
    "Enter at least one reduced-voltage reading.",
    "Enter the gradient reading at dref + 0.5 rcav.",
}


def themed_font(font: QFont, settings: dict | None = None) -> QFont:
    """Uses Font.family and Font.size. Empty family and size 0 mean the platform font + 3 pt, 13 pt floor."""
    config = font_settings(settings)
    bumped = QFont(font)
    if config["family"]:
        bumped.setFamily(config["family"])
    bumped.setPointSize(config["size"] or max(font.pointSize() + 3, 13))
    return bumped


def fill_electrometer_combo(
    combo: QComboBox,
    electrometers: list,
    electrometer_id: str = "",
    legacy: str = "",
) -> None:
    combo.blockSignals(True)
    combo.clear()
    combo.addItem("", "")
    for item in electrometers:
        combo.addItem(item.name, item.id)
    chosen = ""
    if electrometer_id and combo.findData(electrometer_id) >= 0:
        chosen = electrometer_id
    else:
        text = (legacy or "").strip()
        for item in electrometers:
            if text and (electrometer_label(item) == text or item.name == text):
                chosen = item.id
                break
        if not chosen and electrometer_id:
            combo.addItem(text or "(missing electrometer)", electrometer_id)
            chosen = electrometer_id
        elif not chosen and text:
            combo.addItem(text, f"{_LEGACY_ELECTROMETER}{text}")
            chosen = f"{_LEGACY_ELECTROMETER}{text}"
    index = combo.findData(chosen)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def chosen_electrometer(combo: QComboBox, electrometers: list) -> tuple[str, str]:
    data = str(combo.currentData() or "")
    if data.startswith(_LEGACY_ELECTROMETER):
        return "", data[len(_LEGACY_ELECTROMETER) :]
    for item in electrometers:
        if item.id == data:
            return item.id, electrometer_label(item)
    if data:
        return data, combo.currentText().strip()
    return "", ""


def reading_heading(volts: int, depth: str) -> str:
    return f"M({volts}V, {depth}) [nC]"


def field_size_text(value: str) -> str:
    shown = value.replace("X", "x").replace("×", "x").replace("x", "×")
    if "cm" not in shown.lower():
        shown = f"{shown} [cm]"
    return shown


def format_input(value) -> str:
    if value is None:
        return ""
    return format(float(value), ".12g")


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(HINT_STYLE)
    return label


_DOSE_AMOUNT = re.compile(r"(: )(-?\d+(?:\.\d+)?)( \[cGy\])")
_PION_VALUE = re.compile(r"^Pion:\s*(-?\d+(?:\.\d+)?)\s*$")
# (Pion - 1) above 5% means recombination is too large for the chamber.
PION_RECOMBINATION_LIMIT = 1.05
PION_RECOMBINATION_NOTE = "Recombination is above 5%. Investigate or replace the chamber."


def _pion_recombination_high(line: str) -> bool:
    match = _PION_VALUE.match(line.strip())
    if match is None:
        return False
    return float(match.group(1)) > PION_RECOMBINATION_LIMIT


def _with_dose_places(text: str, places: int) -> str:
    """Round each displayed dose to the configured number of decimal places."""
    return _DOSE_AMOUNT.sub(
        lambda match: f"{match.group(1)}{float(match.group(2)):.{places}f}{match.group(3)}",
        text,
    )


def _headlines(text: str) -> str:
    """First line of each calculation block, without the worked arithmetic."""
    lines = []
    for section in text.split("\n\n"):
        first = section.strip().split("\n", 1)[0].strip()
        if first:
            lines.append(first)
    return "\n".join(lines)


def _bold_dmax(text: str, *, underline_results: bool = False) -> str:
    """Rich text with each Dose at dmax result line in bold.

    When underline_results is set, the first line of each block (Ptp, kQ, Pion, dose, and so on) is underlined.
    """
    lines = []
    at_result = True
    for line in text.split("\n"):
        if not line.strip():
            lines.append("")
            at_result = True
            continue
        shown = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.startswith("Dose at dmax"):
            shown = f"<b>{shown}</b>"
        if underline_results and at_result and ":" in line:
            shown = f"<u>{shown}</u>"
        if _pion_recombination_high(line):
            shown = f'<font color="#dc2626"><b>{shown}</b></font>'
            lines.append(shown)
            lines.append(f'<font color="#dc2626">{PION_RECOMBINATION_NOTE}</font>')
        else:
            lines.append(shown)
        at_result = False
    return "<br>".join(lines)


class CollapsibleGroup(QWidget):
    """A titled section that shows its body only while the arrow is open."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(False)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.RightArrow)
        self.toggle.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle.setStyleSheet("QToolButton { border: none; padding: 2px 0; text-align: left; }")
        self.body = QWidget()
        self.body.setVisible(False)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(16, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.body.setVisible(expanded)


def _optional_float(edit: QLineEdit, errors: list[str], label: str) -> float | None:
    text = edit.text().strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        errors.append(f"{label} is not a number.")
        return None


def _positive_int(value, minimum: int) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < minimum:
        return None
    return number


def _fit_on_screen(widget) -> None:
    screen_at = getattr(QApplication, "screenAt", None)
    center = widget.frameGeometry().center()
    screen = screen_at(center) if screen_at is not None else None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:
        return
    avail = screen.availableGeometry()
    frame = widget.frameGeometry()
    if avail.intersects(frame):
        x = min(max(frame.x(), avail.left()), avail.right() - min(80, frame.width()))
        y = min(max(frame.y(), avail.top()), avail.bottom() - min(80, frame.height()))
        widget.move(x, y)
        return
    widget.move(avail.x() + 40, avail.y() + 40)


class WindowMemory:
    """Restores a window's geometry and writes it back when the window closes."""

    def __init__(self, widget, settings_file: Path, name: str, default_size: tuple[int, int]):
        self.widget = widget
        self.settings_file = settings_file
        self.name = name
        self._maximize_on_show = False
        widget._window_memory = self
        state = load_window_state(settings_file, name) or {}
        width = _positive_int(state.get("width"), 240)
        height = _positive_int(state.get("height"), 180)
        if width is None or height is None:
            widget.resize(*default_size)
        else:
            widget.resize(width, height)
            x = _positive_int(state.get("x"), -10000)
            y = _positive_int(state.get("y"), -10000)
            if x is not None and y is not None:
                widget.move(x, y)
                _fit_on_screen(widget)
            self._maximize_on_show = bool(state.get("maximized"))
        apply_extra = getattr(widget, "apply_window_extra_state", None)
        if apply_extra is not None:
            apply_extra(state)
        if isinstance(widget, QDialog):
            widget.finished.connect(self.save)

    def on_show(self) -> None:
        if self._maximize_on_show:
            self._maximize_on_show = False
            self.widget.setWindowState(self.widget.windowState() | Qt.WindowMaximized)

    def save(self, *_args) -> None:
        rect = self.widget.normalGeometry() if self.widget.isMaximized() else self.widget.geometry()
        if rect.width() < 240 or rect.height() < 180:
            rect = self.widget.geometry()
        state = {
            "x": int(rect.x()),
            "y": int(rect.y()),
            "width": int(rect.width()),
            "height": int(rect.height()),
            "maximized": bool(self.widget.isMaximized()),
        }
        extra = getattr(self.widget, "window_extra_state", None)
        if extra is not None:
            state.update(extra())
        save_window_state(self.settings_file, self.name, state)


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


class ReadingTriple:
    """Three fixed reading cells and the average of the numbers entered."""

    def __init__(self) -> None:
        self.cells = [QLineEdit(), QLineEdit(), QLineEdit()]
        self.average = QLineEdit()
        self.average.setReadOnly(True)
        self.average.setFocusPolicy(Qt.NoFocus)
        self.on_change = None
        for edit in self.cells:
            edit.textChanged.connect(self._changed)

    def _changed(self) -> None:
        self._update_average()
        if self.on_change is not None:
            self.on_change()

    def _update_average(self) -> None:
        numbers = []
        for edit in self.cells:
            text = edit.text().strip()
            if not text:
                continue
            try:
                numbers.append(float(text))
            except ValueError:
                continue
        self.average.setText(format_input(sum(numbers) / len(numbers)) if numbers else "")

    def edits(self) -> list[QLineEdit]:
        return list(self.cells)

    def set_values(self, values: list[float]) -> None:
        for edit in self.cells:
            edit.blockSignals(True)
        for index, edit in enumerate(self.cells):
            edit.setText(format_input(values[index]) if index < len(values) else "")
        for edit in self.cells:
            edit.blockSignals(False)
        self._update_average()

    def values(self) -> tuple[list[float], str | None]:
        numbers: list[float] = []
        for edit in self.cells:
            text = edit.text().strip()
            if not text:
                continue
            try:
                numbers.append(float(text))
            except ValueError:
                return [], f"{text!r} is not a reading"
        return numbers, None


def reading_table(rows: list[tuple[str, ReadingTriple]]) -> tuple[QWidget, list[QLabel]]:
    table = QWidget()
    grid = QGridLayout(table)
    grid.setContentsMargins(0, 0, 0, 0)
    for column, title in enumerate(("", "Reading 1", "Reading 2", "Reading 3", "Ave"), start=0):
        header = QLabel(title)
        header.setAlignment(Qt.AlignCenter)
        grid.addWidget(header, 0, column)
    labels: list[QLabel] = []
    for row_index, (label, reading) in enumerate(rows, start=1):
        row_label = QLabel(label)
        labels.append(row_label)
        grid.addWidget(row_label, row_index, 0)
        for column, edit in enumerate(reading.cells, start=1):
            grid.addWidget(edit, row_index, column)
        grid.addWidget(reading.average, row_index, 4)
        grid.setRowStretch(row_index, 0)
    grid.setColumnStretch(0, 0)
    for column in range(1, 5):
        grid.setColumnStretch(column, 1)
    return table, labels


class CaseDialog(QDialog):
    def __init__(
        self,
        parent,
        *,
        catalog: Catalog,
        machine: Machine,
        energy: Energy,
        case: CalibrationCase,
        on_save,
        previous: list[CalibrationCase] | None = None,
        ranges: dict | None = None,
        history_percent: float | None = None,
    ):
        super().__init__(parent)
        self.catalog = catalog
        self.machine = machine
        self.energy = energy
        self.case = case
        self._n_dw_override = case.n_dw
        self._p_elec_override = case.p_elec
        self.on_save = on_save
        self.previous = list(previous or [])
        self.ranges = ranges if ranges is not None else valid_ranges({})
        self.history_percent = catalog.history_warn_percent if history_percent is None else history_percent
        self._loading = True
        self._snapshot = None
        self._result = None
        self._version = ""
        self._warnings: list[str] = []
        self._calc_errors: list[str] = []
        self._field_notes: list[str] = []
        self._pdf_path = case.pdf_path
        self._calc_timer = QTimer(self)
        self._calc_timer.setSingleShot(True)
        self._calc_timer.timeout.connect(self._calculate_now)
        self.setWindowTitle(f"TG-51  {machine.name}  {energy_label(energy)}")
        self.setWindowFlags(
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinMaxButtonsHint
            | Qt.WindowCloseButtonHint
        )
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
            self._show(case.warnings, [], case.result, mu=case.mu or self.catalog.mu)
        else:
            self._show(case.warnings, [], None)
        self._refresh_field_styles()
        self._saved_signature = self._state_token()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form = QWidget()
        form_layout = QVBoxLayout(form)

        setup = QGroupBox("Information")
        self.date = QDateEdit()
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        self.user_combo = QComboBox()
        self.user_combo.addItem("", "")
        for user in self.catalog.users:
            self.user_combo.addItem(user.name, user.id)
        self._two_columns(
            setup,
            [
                ("Machine", QLabel(self.machine.name)),
                ("Energy", QLabel(energy_label(self.energy))),
                ("Measurement date", self.date),
                ("Physicist", self.user_combo),
            ],
        )
        self.comment = QPlainTextEdit()
        self.comment.setPlaceholderText("Notes for this energy")
        self.comment.setFixedHeight(72)
        comment_row = QFormLayout()
        comment_row.addRow("Comments", self.comment)
        setup.layout().addLayout(comment_row)
        form_layout.addWidget(setup)

        conditions = QGroupBox("Temperature/Pressure")
        self.temp = QLineEdit()
        self.temp_unit = QComboBox()
        self.temp_unit.addItem("°C", "C")
        self.temp_unit.addItem("°F", "F")
        self.press = QLineEdit()
        self.press_unit = QComboBox()
        self.press_unit.addItem("mmHg", "mmHg")
        self.press_unit.addItem("kPa", "kPa")
        self.press_unit.addItem("mbar", "mbar")
        self._two_columns(
            conditions,
            [
                ("Temperature (Water)", self._unit_row(self.temp, self.temp_unit)),
                ("Pressure", self._unit_row(self.press, self.press_unit)),
            ],
        )
        self._ptp_text = "Ptp"
        self.ptp_label = QLabel("Ptp")
        self.ptp_label.setWordWrap(True)
        self.ptp_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        conditions.layout().addWidget(self.ptp_label)
        form_layout.addWidget(conditions)

        chamber = QGroupBox("Ion Chamber/Electrometer")
        self.chamber_combo = QComboBox()
        self.chamber_combo.addItem("", "")
        for item in self.catalog.chambers:
            self.chamber_combo.addItem(f"{item.name}  ({model_label(item.model)})", item.id)
        self.chamber_combo.currentIndexChanged.connect(self._chamber_changed)
        self.electrometer = QComboBox()
        self.electrometer.currentIndexChanged.connect(self._electrometer_changed)
        fill_electrometer_combo(self.electrometer, self.catalog.electrometers)
        self.n_dw = QLabel("NDw")
        self.p_elec = QLabel("P_elec")
        for label in (self.n_dw, self.p_elec):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._two_columns(
            chamber,
            [
                ("Ion Chamber", self._factor_row(self.chamber_combo, self.n_dw)),
                ("Electrometer", self._factor_row(self.electrometer, self.p_elec)),
            ],
        )
        form_layout.addWidget(chamber)

        self.photon_box = QGroupBox("Photon beam quality")
        self.measured_pdd10 = QLineEdit()
        self.lead_foil = QComboBox()
        self.lead_foil.addItem("No lead foil", "none")
        self.lead_foil.addItem("Lead foil at 50 [cm]", "50cm")
        self.lead_foil.addItem("Lead foil at 30 [cm]", "30cm")
        self._two_columns(
            self.photon_box,
            [
                ("PDD(10)x [%]", self.measured_pdd10),
                ("Lead foil", self.lead_foil),
            ],
        )
        self._kq_text = "kQ"
        self.kq_label = QLabel("kQ")
        self.kq_label.setWordWrap(True)
        self.kq_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.photon_box.layout().addWidget(self.kq_label)
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
        self.i_50 = QLineEdit()
        electron_form.addRow("Method", self.method)
        electron_form.addRow(self.modern_warning)
        electron_form.addRow("I50 [cm]", self.i_50)
        self.r50 = QLabel()
        self.dref_value = QLabel()
        for label in (self.r50, self.dref_value):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        electron_form.addRow("R50 [cm]", self.r50)
        electron_form.addRow("dref [cm]", self.dref_value)
        self._quality_text = ""
        self.kecal_label = QLabel("k_ecal")
        self.k_ecal = QLabel("k_ecal")
        self.k_ecal.setTextInteractionFlags(Qt.TextSelectableByMouse)
        electron_form.addRow(self.kecal_label, self.k_ecal)
        form_layout.addWidget(self.electron_box)

        reference = QGroupBox("Setup")
        depth = (
            f"{self.catalog.measurement_depth_cm:g} [cm]"
            if self.energy.modality == "photon"
            else "dref"
        )
        setup_rows = []
        size_label = "Cone size" if self.energy.modality == "electron" else "Field size"
        depth_label = "dref" if self.energy.modality == "electron" else "Measurement depth"
        for label, text in (
            ("Vref", f"{self.catalog.voltage_reference} [V]"),
            ("Vreduced", f"{self.catalog.voltage_reduced} [V]"),
            ("MU", str(self.catalog.mu)),
            ("Tissue correction", format_input(self.catalog.tissue_correction)),
            (size_label, field_size_text(self.catalog.field_size)),
            (depth_label, depth),
        ):
            shown = QLabel(text)
            shown.setTextInteractionFlags(Qt.TextSelectableByMouse)
            if label == depth_label:
                self.depth_value = shown
            setup_rows.append((label, shown))
        self._two_columns(reference, setup_rows)
        form_layout.addWidget(reference)

        readings = QGroupBox("Pre-Calibration Readings")
        readings_layout = QVBoxLayout(readings)
        self.m_reference = ReadingTriple()
        self.m_opposite = ReadingTriple()
        self.m_reduced = ReadingTriple()
        readings_table, self.reading_labels = reading_table(
            [
                (reading_heading(self.catalog.voltage_reference, self._reading_depth()), self.m_reference),
                (reading_heading(-self.catalog.voltage_reference, self._reading_depth()), self.m_opposite),
                (reading_heading(self.catalog.voltage_reduced, self._reading_depth()), self.m_reduced),
            ]
        )
        readings_layout.addWidget(readings_table)
        self._corrections_text = "Pion\n\nPpol\n\nM corrected"
        self.corrections_label = QLabel("Pion\nPpol\nM corrected")
        self.corrections_label.setWordWrap(True)
        self.corrections_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        readings_layout.addWidget(self.corrections_label)
        form_layout.addWidget(readings)

        self.pgr_box = QGroupBox("Pgr")
        pgr_layout = QVBoxLayout(self.pgr_box)
        self.m_gradient = ReadingTriple()
        _pgr_table, self.gradient_labels = reading_table(
            [
                (
                    reading_heading(self.catalog.voltage_reference, self._gradient_depth()),
                    self.m_gradient,
                )
            ]
        )
        pgr_layout.addWidget(_pgr_table)
        form_layout.addWidget(self.pgr_box)

        self.depth_dose_box = QGroupBox("Pre-Calibration Doses")
        depth_form = QFormLayout(self.depth_dose_box)
        self.clinical_pdd10 = QLineEdit()
        self.clinical_pdd = QLineEdit()
        self.clinical_pdd10_label = QLabel("Clinical PDD(10) [%]")
        self.clinical_pdd_label = QLabel("Clinical PDD (dref) [%]")
        depth_form.addRow(self.clinical_pdd10_label, self.clinical_pdd10)
        depth_form.addRow(self.clinical_pdd_label, self.clinical_pdd)
        self._dose_text_block = "Dose at 10 [cm]\n\nDose at dmax"
        self.dose_label = QLabel("Dose at 10 [cm]\nDose at dmax")
        self.dose_label.setWordWrap(True)
        self.dose_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        depth_form.addRow(self.dose_label)
        form_layout.addWidget(self.depth_dose_box)
        photon = self.energy.modality == "photon"
        self.photon_box.setVisible(photon)
        self.electron_box.setVisible(not photon)
        self.clinical_pdd10_label.setVisible(photon)
        self.clinical_pdd10.setVisible(photon)
        self.clinical_pdd_label.setVisible(not photon)
        self.clinical_pdd.setVisible(not photon)

        post = QGroupBox("Post-Calibration Verification")
        post_layout = QVBoxLayout(post)
        self.m_adjusted = ReadingTriple()
        adjusted_table, self.post_labels = reading_table(
            [
                (
                    reading_heading(self.catalog.voltage_reference, self._reading_depth()),
                    self.m_adjusted,
                )
            ]
        )
        post_layout.addWidget(adjusted_table)
        self._adjusted_text = "Dose at 10 [cm], adjusted\n\nDose at dmax, adjusted"
        self.adjusted_dose_label = QLabel("Dose at 10 [cm], adjusted\nDose at dmax, adjusted")
        self.adjusted_dose_label.setWordWrap(True)
        self.adjusted_dose_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        post_layout.addWidget(self.adjusted_dose_label)
        form_layout.addWidget(post)

        self.calculations_box = CollapsibleGroup("Calculations")
        self.calculations_label = QLabel()
        self.calculations_label.setWordWrap(True)
        self.calculations_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.calculations_box.body_layout.addWidget(self.calculations_label)
        form_layout.addWidget(self.calculations_box)
        for edit in (
            self.temp,
            self.press,
            self.measured_pdd10,
            self.clinical_pdd10,
            self.clinical_pdd,
            self.i_50,
        ):
            edit.textChanged.connect(self._refresh_field_styles)
        self.temp_unit.currentIndexChanged.connect(self._refresh_field_styles)
        self.press_unit.currentIndexChanged.connect(self._refresh_field_styles)
        self.lead_foil.currentIndexChanged.connect(self._refresh_field_styles)
        for readings in (self.m_reference, self.m_opposite, self.m_reduced, self.m_adjusted, self.m_gradient):
            readings.on_change = self._refresh_field_styles

        form_layout.addStretch(1)
        scroll.setWidget(form)
        root.addWidget(scroll, 1)

        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(WARN_STYLE)
        self.warning_label.setVisible(False)
        root.addWidget(self.warning_label)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save")
        pdf_btn = QPushButton("Save PDF")
        cancel_btn = QPushButton("Cancel")
        save_btn.clicked.connect(lambda: self.save_case(close=False))
        pdf_btn.clicked.connect(self._on_save_pdf)
        cancel_btn.clicked.connect(self.close)
        buttons.addWidget(save_btn)
        buttons.addWidget(pdf_btn)
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _two_columns(self, box: QGroupBox, rows: list[tuple[str, QWidget]], hint: str = "") -> None:
        layout = QVBoxLayout(box)
        columns = QHBoxLayout()
        forms = (QFormLayout(), QFormLayout())
        for form in forms:
            form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        for index, (label, widget) in enumerate(rows):
            forms[index % 2].addRow(label, widget)
        columns.addLayout(forms[0], 1)
        columns.addLayout(forms[1], 1)
        layout.addLayout(columns)
        if hint:
            layout.addWidget(_hint(hint))

    def _factor_row(self, combo: QComboBox, factor: QLabel) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(combo, 1)
        layout.addWidget(factor)
        return row

    def _factor_text(self, name: str, value: float | None, unit: str) -> str:
        if value is None:
            return name
        suffix = f" [{unit}]" if unit else ""
        return f"{name}  {format_input(value)}{suffix}"

    def _factors(self) -> tuple[float | None, float | None]:
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        electrometer_id, _label = chosen_electrometer(self.electrometer, self.catalog.electrometers)
        meter = self.catalog.electrometer(electrometer_id)
        if self._n_dw_override is not None:
            n_dw = self._n_dw_override
        elif chamber is not None:
            n_dw = chamber.n_dw
        else:
            n_dw = self.case.n_dw
        if self._p_elec_override is not None:
            p_elec = self._p_elec_override
        elif meter is not None and meter.p_elec is not None:
            p_elec = meter.p_elec
        elif chamber is not None and chamber.p_elec is not None:
            p_elec = chamber.p_elec
        else:
            p_elec = self.case.p_elec
        return n_dw, p_elec

    def _use_latest_factors(self, *, n_dw: bool, p_elec: bool) -> None:
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        electrometer_id, _label = chosen_electrometer(self.electrometer, self.catalog.electrometers)
        meter = self.catalog.electrometer(electrometer_id)
        if n_dw:
            self._n_dw_override = chamber.n_dw if chamber is not None else None
        if p_elec:
            if meter is not None and meter.p_elec is not None:
                self._p_elec_override = meter.p_elec
            elif chamber is not None and chamber.p_elec is not None:
                self._p_elec_override = chamber.p_elec
            else:
                self._p_elec_override = None

    def _reading_depth(self) -> str:
        if self.energy.modality == "photon":
            return f"depth={self.catalog.measurement_depth_cm:.2f} cm"
        i_50, bad = self._parsed(self.i_50)
        if i_50 is None or bad:
            return "dref"
        depth = electron_dref(i_50)
        if depth is None:
            return "dref"
        return f"dref={depth:.2f} cm"

    def _gradient_depth(self) -> str:
        i_50, bad = self._parsed(self.i_50)
        dref = None if i_50 is None or bad else electron_dref(i_50)
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        rcav = None if chamber is None else chamber.rcav_cm
        if dref is None or rcav is None:
            return "dref+0.5rcav"
        return f"dref+0.5rcav={dref + 0.5 * rcav:.2f} cm"

    def _show_electron_quality(self) -> None:
        i_50, bad = self._parsed(self.i_50)
        if self.energy.modality != "electron" or i_50 is None or bad:
            self.r50.setText("")
            self.dref_value.setText("")
            self._quality_text = ""
            if self.energy.modality == "electron":
                self.depth_value.setText("")
                self.clinical_pdd_label.setText("Clinical PDD (dref) [%]")
            return
        r50 = electron_r50(i_50)
        dref = electron_dref(i_50)
        self.r50.setText("" if r50 is None else f"{r50:.2f}")
        self.dref_value.setText("" if dref is None else f"{dref:.2f}")
        self.depth_value.setText("" if dref is None else f"{dref:.2f} [cm]")
        if dref is None:
            self.clinical_pdd_label.setText("Clinical PDD (dref) [%]")
        else:
            self.clinical_pdd_label.setText(f"Clinical PDD (dref={dref:.2f} cm) [%]")
        self._quality_text = electron_quality_text(i_50) or ""

    def _show_reading_headings(self) -> None:
        depth = self._reading_depth()
        volts = (
            self.catalog.voltage_reference,
            -self.catalog.voltage_reference,
            self.catalog.voltage_reduced,
        )
        for label, volt in zip(self.reading_labels, volts):
            label.setText(reading_heading(volt, depth))
        self.post_labels[0].setText(reading_heading(self.catalog.voltage_reference, depth))
        self.gradient_labels[0].setText(
            reading_heading(self.catalog.voltage_reference, self._gradient_depth())
        )

    def _show_factors(self) -> None:
        n_dw, p_elec = self._factors()
        self.n_dw.setText(self._factor_text("NDw", n_dw, "Gy/nC"))
        self.p_elec.setText(self._factor_text("P_elec", p_elec, ""))

    def _current_kecal(self) -> float | None:
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        value = chamber_kecal(chamber)
        if value is not None:
            return value
        return self.case.k_ecal

    def _show_kecal(self) -> None:
        value = self._current_kecal()
        self.k_ecal.setText("" if value is None else format_input(value))

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
        self.comment.setPlainText(case.comment)
        self.temp.setText(format_input(case.temp_value))
        self._select(self.temp_unit, case.temp_unit if case.temp_unit in ("C", "F") else "C")
        self.press.setText(format_input(case.press_value))
        self._select(self.press_unit, case.press_unit if case.press_unit in ("mmHg", "kPa", "mbar") else "mmHg")
        if case.chamber_id and self.chamber_combo.findData(case.chamber_id) < 0:
            self.chamber_combo.addItem("(missing chamber)", case.chamber_id)
        self._select(self.chamber_combo, case.chamber_id)
        fill_electrometer_combo(
            self.electrometer, self.catalog.electrometers, case.electrometer_id, case.electrometer
        )
        self._show_factors()
        self.m_reference.set_values(case.m_reference)
        self.m_opposite.set_values(case.m_opposite)
        self.m_reduced.set_values(case.m_reduced)
        self.m_adjusted.set_values(case.m_reference_adjusted)
        self.measured_pdd10.setText(format_input(case.measured_pdd10))
        self.clinical_pdd10.setText(format_input(case.clinical_pdd10))
        self._select(self.lead_foil, case.lead_foil or "none")
        self._select(self.method, case.electron_method or "legacy")
        self.clinical_pdd.setText(format_input(case.clinical_pdd))
        self.i_50.setText(format_input(case.i_50))
        self._show_kecal()
        self.m_gradient.set_values(case.m_gradient)
        self._sync_method()

    def _chamber_changed(self) -> None:
        if self._loading:
            return
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        if chamber is not None:
            fill_electrometer_combo(
                self.electrometer,
                self.catalog.electrometers,
                chamber.electrometer_id,
                chamber.electrometer,
            )
        self._use_latest_factors(n_dw=True, p_elec=True)
        self._show_factors()
        self._show_kecal()
        self._refresh_field_styles()

    def _electrometer_changed(self) -> None:
        if self._loading:
            return
        self._use_latest_factors(n_dw=False, p_elec=True)
        self._show_factors()
        self._refresh_field_styles()

    def _sync_method(self) -> None:
        legacy = self.method.currentData() == "legacy"
        self.kecal_label.setVisible(legacy)
        self.k_ecal.setVisible(legacy)
        self.pgr_box.setVisible(self.energy.modality == "electron" and legacy)
        self.modern_warning.setVisible(not legacy)
        if not self._loading:
            self._refresh_field_styles()

    def _current_ptp(self) -> float | None:
        temp, temp_bad = self._parsed(self.temp)
        press, press_bad = self._parsed(self.press)
        if temp is None or press is None or temp_bad or press_bad:
            return None
        press_kpa_value = pressure_kpa(press, str(self.press_unit.currentData() or "kPa"))
        if press_kpa_value == 0:
            return None
        temp_c = temperature_celsius(temp, str(self.temp_unit.currentData() or "C"))
        return ptp_value(temp_c, press_kpa_value)

    def _current_m_corrected(self) -> float | None:
        m_reference = self._reading_values(self.m_reference)
        m_opposite = self._reading_values(self.m_opposite)
        m_reduced = self._reading_values(self.m_reduced)
        if m_reference is None or m_opposite is None or m_reduced is None:
            return None
        _n_dw, p_elec = self._factors()
        return m_corrected_value(
            m_reference=m_reference,
            m_opposite=m_opposite,
            m_reduced=m_reduced,
            voltage_reference=self.catalog.voltage_reference,
            voltage_reduced=self.catalog.voltage_reduced,
            p_tp=self._current_ptp(),
            p_elec=p_elec,
        )

    def _dose_text(self, corrected: float | None, *, adjusted: bool) -> str:
        photon = self.energy.modality == "photon"
        suffix = ", adjusted" if adjusted else ""
        missing = (
            f"Dose at 10 [cm]{suffix}\n\nDose at dmax{suffix}"
            if photon
            else f"Dose at dref{suffix}\n\nDose at dmax{suffix}"
        )
        n_dw, _p_elec = self._factors()
        mu = self.catalog.mu
        tissue = self.catalog.tissue_correction
        if corrected is None or n_dw is None or not mu or tissue is None:
            return missing
        if photon:
            pdd, bad = self._parsed(self.measured_pdd10)
            clinical, clinical_bad = self._parsed(self.clinical_pdd10)
            nominal = float(self.energy.nominal)
            chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
            if (
                pdd is None
                or bad
                or clinical is None
                or clinical_bad
                or clinical == 0
                or chamber is None
                or not nominal.is_integer()
            ):
                return missing
            kq = photon_kq_value(
                chamber,
                pdd=pdd,
                energy=int(nominal),
                lead_foil=str(self.lead_foil.currentData() or "none"),
            )
            if kq is None:
                return missing
            return photon_dose_text(
                tissue=tissue,
                m_corrected=corrected,
                kq=kq,
                n_dw=n_dw,
                mu=mu,
                clinical_pdd10=clinical,
                adjusted=adjusted,
            )
        clinical, clinical_bad = self._parsed(self.clinical_pdd)
        i_50, i_bad = self._parsed(self.i_50)
        if clinical is None or clinical_bad or clinical == 0 or i_50 is None or i_bad:
            return missing
        method = str(self.method.currentData() or "legacy")
        k_ecal = self._current_kecal()
        if method == "legacy" and k_ecal is None:
            return missing
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        kq = electron_kq_value(chamber, method=method, i_50=i_50, k_ecal=k_ecal)
        if kq is None:
            return missing
        pgr = None
        if method == "legacy":
            reference = self._reading_values(self.m_reference)
            gradient, error = self.m_gradient.values()
            if error or not reference or not gradient or sum(reference) == 0:
                return missing
            pgr = (sum(gradient) / len(gradient)) / (sum(reference) / len(reference))
        return electron_dose_text(
            tissue=tissue,
            m_corrected=corrected,
            kq=kq,
            n_dw=n_dw,
            mu=mu,
            clinical_pdd=clinical,
            pgr=pgr,
            adjusted=adjusted,
        )

    def _show_depth_dose(self) -> None:
        self._dose_text_block = self._dose_text(self._current_m_corrected(), adjusted=False)
        self.dose_label.setText(
            _bold_dmax(_with_dose_places(_headlines(self._dose_text_block), self.catalog.dose_decimal_places))
        )

    def _show_adjusted_dose(self) -> None:
        adjusted = self._reading_values(self.m_adjusted)
        corrected = None
        if adjusted:
            reference = self._reading_values(self.m_reference)
            opposite = self._reading_values(self.m_opposite)
            reduced = self._reading_values(self.m_reduced)
            _n_dw, p_elec = self._factors()
            if reference is not None and opposite is not None and reduced is not None:
                corrected = m_adjusted_corrected_value(
                    m_reference=reference,
                    m_opposite=opposite,
                    m_reduced=reduced,
                    m_adjusted=adjusted,
                    voltage_reference=self.catalog.voltage_reference,
                    voltage_reduced=self.catalog.voltage_reduced,
                    p_tp=self._current_ptp(),
                    p_elec=p_elec,
                )
        self._adjusted_text = self._dose_text(corrected, adjusted=True)
        self.adjusted_dose_label.setText(
            _bold_dmax(_with_dose_places(_headlines(self._adjusted_text), self.catalog.dose_decimal_places))
        )

    def _readings(self, widget: ReadingTriple, errors: list[str], label: str) -> list[float]:
        values, error = widget.values()
        if error:
            errors.append(f"{label}: {error}.")
        return values

    def _collect(self) -> tuple[CalibrationCase | None, list[str]]:
        errors: list[str] = []
        case = self.case.clone()
        case.measurement_date = self.date.date().toString("yyyy-MM-dd")
        case.user_id = str(self.user_combo.currentData() or "")
        case.comment = self.comment.toPlainText().strip()
        case.temp_value = _optional_float(self.temp, errors, "Temperature (Water)")
        case.temp_unit = str(self.temp_unit.currentData() or "C")
        case.press_value = _optional_float(self.press, errors, "Pressure")
        case.press_unit = str(self.press_unit.currentData() or "kPa")
        case.chamber_id = str(self.chamber_combo.currentData() or "")
        case.n_dw, case.p_elec = self._factors()
        case.electrometer_id, case.electrometer = chosen_electrometer(
            self.electrometer, self.catalog.electrometers
        )
        case.voltage_reference = self.catalog.voltage_reference
        case.voltage_reduced = self.catalog.voltage_reduced
        case.mu = self.catalog.mu
        case.tissue_correction = self.catalog.tissue_correction
        case.m_reference = self._readings(self.m_reference, errors, "M at Vref")
        case.m_opposite = self._readings(self.m_opposite, errors, "M at opposite polarity")
        case.m_reduced = self._readings(self.m_reduced, errors, "M at Vreduced")
        case.m_reference_adjusted = self._readings(self.m_adjusted, errors, "M adjusted")
        case.measured_pdd10 = _optional_float(self.measured_pdd10, errors, "PDD(10)x")
        case.clinical_pdd10 = _optional_float(self.clinical_pdd10, errors, "Clinical PDD(10)")
        case.lead_foil = str(self.lead_foil.currentData() or "none")
        case.electron_method = str(self.method.currentData() or "legacy")
        case.clinical_pdd = _optional_float(self.clinical_pdd, errors, "Clinical PDD")
        if self.energy.modality == "electron":
            case.cone = self.catalog.field_size
        case.i_50 = _optional_float(self.i_50, errors, "I50")
        if self.energy.modality == "electron":
            case.k_ecal = self._current_kecal()
        else:
            case.k_ecal = None
        case.m_gradient = self._readings(self.m_gradient, errors, "Gradient reading")
        if errors:
            return None, errors
        return case, []

    def _paint_edit(self, edit: QLineEdit, level: str, tip: str) -> None:
        if level == "range":
            edit.setStyleSheet(RANGE_EDIT_STYLE)
        elif level == "history":
            edit.setStyleSheet(HISTORY_EDIT_STYLE)
        elif level == "needed":
            edit.setStyleSheet(NEEDED_EDIT_STYLE)
        else:
            edit.setStyleSheet("")
        edit.setToolTip(tip)

    def _number_edits(self) -> list[QLineEdit]:
        edits = [
            self.temp,
            self.press,
            self.measured_pdd10,
            self.clinical_pdd10,
            self.clinical_pdd,
            self.i_50,
        ]
        for readings in (self.m_reference, self.m_opposite, self.m_reduced, self.m_adjusted, self.m_gradient):
            edits.extend(readings.edits())
        return edits

    def _parsed(self, edit: QLineEdit) -> tuple[float | None, bool]:
        text = edit.text().strip()
        if not text:
            return None, False
        try:
            return float(text), False
        except ValueError:
            return None, True

    def _show_ptp(self) -> None:
        temp, temp_bad = self._parsed(self.temp)
        press, press_bad = self._parsed(self.press)
        if temp is None or press is None or temp_bad or press_bad:
            self._set_ptp("Ptp")
            return
        temp_c = temperature_celsius(temp, str(self.temp_unit.currentData() or "C"))
        press_kpa_value = pressure_kpa(press, str(self.press_unit.currentData() or "kPa"))
        if press_kpa_value == 0:
            self._set_ptp("Ptp")
            return
        self._set_ptp(ptp_text(temp_c, press_kpa_value))

    def _set_ptp(self, text: str) -> None:
        self._ptp_text = text
        self.ptp_label.setText(_headlines(text))

    def _show_kq(self) -> None:
        if self.energy.modality != "photon":
            self._set_kq("kQ")
            return
        pdd, bad = self._parsed(self.measured_pdd10)
        nominal = float(self.energy.nominal)
        chamber = self.catalog.chamber(str(self.chamber_combo.currentData() or ""))
        if pdd is None or bad or chamber is None or not nominal.is_integer():
            self._set_kq("kQ")
            return
        text = photon_kq_text(
            chamber,
            pdd=pdd,
            energy=int(nominal),
            lead_foil=str(self.lead_foil.currentData() or "none"),
        )
        self._set_kq(text or "kQ")

    def _set_kq(self, text: str) -> None:
        self._kq_text = text
        self.kq_label.setText(_headlines(text))

    def _reading_values(self, widget: ReadingTriple) -> list[float] | None:
        values, error = widget.values()
        if error:
            return None
        return values

    def _show_reading_corrections(self) -> None:
        m_reference = self._reading_values(self.m_reference)
        m_opposite = self._reading_values(self.m_opposite)
        m_reduced = self._reading_values(self.m_reduced)
        if m_reference is None or m_opposite is None or m_reduced is None:
            self._set_corrections("Pion\n\nPpol\n\nM corrected")
            return
        _n_dw, p_elec = self._factors()
        p_tp = None
        temp, temp_bad = self._parsed(self.temp)
        press, press_bad = self._parsed(self.press)
        if temp is not None and press is not None and not temp_bad and not press_bad:
            temp_c = temperature_celsius(temp, str(self.temp_unit.currentData() or "C"))
            press_kpa_value = pressure_kpa(press, str(self.press_unit.currentData() or "kPa"))
            if press_kpa_value != 0:
                p_tp = ptp_value(temp_c, press_kpa_value)
        self._set_corrections(
            readings_correction_text(
                m_reference=m_reference,
                m_opposite=m_opposite,
                m_reduced=m_reduced,
                voltage_reference=self.catalog.voltage_reference,
                voltage_reduced=self.catalog.voltage_reduced,
                p_tp=p_tp,
                p_elec=p_elec,
            )
        )

    def _set_corrections(self, text: str) -> None:
        self._corrections_text = text
        self.corrections_label.setText(_bold_dmax(_headlines(text)))

    def _compose_calculations(self) -> None:
        parts = [self._ptp_text]
        if self.energy.modality == "photon":
            parts.append(self._kq_text)
        elif self._quality_text:
            parts.append(self._quality_text)
        parts.extend([self._corrections_text, self._dose_text_block, self._adjusted_text])
        self.calculations_label.setText(
            _bold_dmax("\n\n".join(part for part in parts if part), underline_results=True)
        )

    def _refresh_field_styles(self, *_args) -> None:
        if self._loading:
            return
        self._show_reading_headings()
        self._show_electron_quality()
        self._show_ptp()
        self._show_kq()
        self._show_reading_corrections()
        self._show_depth_dose()
        self._show_adjusted_dose()
        self._compose_calculations()
        case, errors = self._collect()
        notes: list[str] = []
        if errors or case is None:
            for edit in self._number_edits():
                _value, bad = self._parsed(edit)
                if bad:
                    self._paint_edit(edit, "range", "Not a number.")
            self._field_notes = errors
            self._compose_warnings()
            self._schedule_calculation()
            return
        if self.energy.modality == "photon":
            case.clinical_pdd = None
            case.i_50 = None
            case.k_ecal = None
            case.m_gradient = []
        else:
            case.measured_pdd10 = None
            case.clinical_pdd10 = None
        values = canonical_values(case)
        history = {key: message for key, message in history_messages(case, self.previous, self.history_percent)}
        for key in ("n_dw", "p_elec", "voltage_reference", "voltage_reduced", "mu", "tissue_correction"):
            value = values.get(key)
            if value is None:
                continue
            message = range_message(FIELD_LABELS[key], value, self.ranges.get(key), FIELD_UNITS.get(key, ""))
            if message:
                notes.append(message)
            elif key in history:
                notes.append(history[key])
        if self.energy.modality == "photon":
            hidden = {"clinical_pdd", "i_50", "k_ecal", "m_gradient"}
        else:
            hidden = {"measured_pdd10", "clinical_pdd10"}
        single_fields = (
            ("temperature_c", self.temp, values.get("temperature_c")),
            ("pressure_kpa", self.press, values.get("pressure_kpa")),
            ("measured_pdd10", self.measured_pdd10, values.get("measured_pdd10")),
            ("clinical_pdd10", self.clinical_pdd10, values.get("clinical_pdd10")),
            ("clinical_pdd", self.clinical_pdd, values.get("clinical_pdd")),
            ("i_50", self.i_50, values.get("i_50")),
        )
        for key, edit, value in single_fields:
            if key in hidden:
                self._paint_edit(edit, "ok", "")
                continue
            _value, bad = self._parsed(edit)
            label = FIELD_LABELS[key]
            if bad:
                self._paint_edit(edit, "range", f"{label} is not a number.")
                notes.append(f"{label} is not a number.")
                continue
            if value is None:
                if key in self._required_single_keys():
                    self._paint_edit(edit, "needed", "Enter a value.")
                else:
                    self._paint_edit(edit, "ok", "")
                continue
            message = range_message(label, value, self.ranges.get(key), FIELD_UNITS.get(key, ""))
            if message:
                self._paint_edit(edit, "range", message)
                notes.append(message)
            elif key in history:
                self._paint_edit(edit, "history", history[key])
                notes.append(history[key])
            else:
                self._paint_edit(edit, "ok", "")
        if self.energy.modality == "electron" and str(self.method.currentData() or "") == "legacy":
            kecal = self._current_kecal()
            if kecal is not None:
                message = range_message(FIELD_LABELS["k_ecal"], kecal, self.ranges.get("k_ecal"), "")
                if message:
                    notes.append(message)
        reading_widgets = {
            "m_reference": self.m_reference,
            "m_opposite": self.m_opposite,
            "m_reduced": self.m_reduced,
            "m_reference_adjusted": self.m_adjusted,
            "m_gradient": self.m_gradient,
        }
        reading_bounds = self.ranges.get(READING_RANGE_KEY)
        for key in READING_FIELDS:
            if key in hidden:
                for edit in reading_widgets[key].edits():
                    self._paint_edit(edit, "ok", "")
                continue
            label = FIELD_LABELS[key]
            edits = list(reading_widgets[key].edits())
            parsed = [self._parsed(edit) for edit in edits]
            has_value = any(value is not None and not bad for value, bad in parsed)
            required = key in self._required_reading_keys()
            group_bad = False
            for edit, (value, bad) in zip(edits, parsed):
                if bad:
                    self._paint_edit(edit, "range", f"{label} is not a number.")
                    notes.append(f"{label} is not a number.")
                    group_bad = True
                elif value is None:
                    if required and not has_value:
                        self._paint_edit(edit, "needed", "Enter a value.")
                    else:
                        self._paint_edit(edit, "ok", "")
                else:
                    message = range_message(label, value, reading_bounds, FIELD_UNITS.get(key, ""))
                    if message:
                        self._paint_edit(edit, "range", message)
                        notes.append(message)
                        group_bad = True
                    else:
                        self._paint_edit(edit, "ok", "")
            if key in history and not group_bad:
                for edit in reading_widgets[key].edits():
                    if edit.text().strip():
                        self._paint_edit(edit, "history", history[key])
                notes.append(history[key])
        self._field_notes = notes
        self._compose_warnings()
        self._schedule_calculation()

    def _required_single_keys(self) -> set[str]:
        if self.energy.modality == "photon":
            return {"temperature_c", "pressure_kpa", "measured_pdd10", "clinical_pdd10"}
        return {"temperature_c", "pressure_kpa", "clinical_pdd", "i_50"}

    def _required_reading_keys(self) -> set[str]:
        keys = {"m_reference", "m_opposite", "m_reduced"}
        if self.energy.modality == "electron" and str(self.method.currentData() or "") == "legacy":
            keys.add("m_gradient")
        return keys

    def _schedule_calculation(self) -> None:
        self._calc_timer.start(CALC_DEBOUNCE_MS)

    def _calculate_now(self) -> None:
        outcome = self.run_calculation()
        self.apply_outcome(outcome)
        if outcome.errors:
            self._calc_errors = [error for error in outcome.errors if error not in _BLANK_CALC_ERRORS]
            self._compose_warnings()

    def _compose_warnings(self) -> None:
        text = "\n".join(self._field_notes + list(self._warnings) + list(self._calc_errors))
        self.warning_label.setText(text)
        self.warning_label.setVisible(bool(text))

    def _show(self, warnings: list[str], errors: list[str], result: dict | None, *, mu: float | None = None) -> None:
        self._warnings = list(warnings)
        self._calc_errors = list(errors)
        self._compose_warnings()

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

    def _prepare_case(self) -> tuple[CalibrationCase | None, list[str]]:
        case, errors = self._collect()
        if errors or case is None:
            return None, errors or ["The case could not be read."]
        if self._snapshot == input_dict(case) and self._result is not None:
            case.status = "calculated"
            case.result = copy.deepcopy(self._result)
            case.pylinac_version = self._version
            case.warnings = list(self._warnings)
        else:
            case.status = "draft"
            case.result = None
            case.pylinac_version = ""
            case.warnings = _draft_warnings(case)
        case.pdf_path = self._pdf_path
        return case, []

    def _state_token(self) -> tuple:
        """User-entered fields. A recalculation on open is not an edit."""
        case, errors = self._collect()
        if errors or case is None:
            return ("invalid", tuple(errors))
        data = input_dict(case)
        data["comment"] = case.comment
        return ("ok", data)

    def _is_dirty(self) -> bool:
        return self._state_token() != self._saved_signature

    def _close_choice(self) -> str:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("TG-51 case")
        box.setText("Save changes to this calibration?")
        box.setStandardButtons(QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        box.setDefaultButton(QMessageBox.Save)
        discard = box.button(QMessageBox.Discard)
        if discard is not None:
            discard.setText("Don't save")
        choice = box.exec_()
        if choice == QMessageBox.Save:
            return "save"
        if choice == QMessageBox.Discard:
            return "discard"
        return "cancel"

    def closeEvent(self, event) -> None:
        if getattr(self, "_closing", False):
            event.accept()
            return
        if self._is_dirty():
            choice = self._close_choice()
            if choice == "cancel" or (choice == "save" and not self.save_case(close=False)):
                event.ignore()
                return
        self._closing = True
        event.accept()
        self.reject()

    def save_case(self, *, close: bool) -> bool:
        case, errors = self._prepare_case()
        if errors or case is None:
            QMessageBox.warning(self, "TG-51 case", "\n".join(errors or ["The case could not be read."]))
            return False
        self.case = case
        self.on_save(case)
        self._saved_signature = self._state_token()
        if close:
            self.accept()
        return True

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


class CalibrationTable(QWidget):
    """Date, lab, and factor rows. The newest dated factor is the one a new case uses."""

    def __init__(self, factor_header: str, calibrations: list[Calibration] | None = None):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Date", "Lab", factor_header])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(120)
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton("Add calibration")
        remove = QPushButton("Remove")
        add.clicked.connect(lambda: self.add_row())
        remove.clicked.connect(self._remove)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        rows = list(calibrations or [])
        rows.sort(key=lambda item: (parse_calibration_date(item.date) is not None, parse_calibration_date(item.date) or datetime.min), reverse=True)
        if rows:
            for item in rows:
                self.add_row(item.date, item.lab, format_input(item.factor))
        else:
            self.add_row()

    def add_row(self, date: str = "", lab: str = "", factor: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for column, text in enumerate((date, lab, factor)):
            self.table.setItem(row, column, QTableWidgetItem(text))

    def _remove(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _text(self, row: int, column: int) -> str:
        item = self.table.item(row, column)
        return item.text().strip() if item is not None else ""

    def read(self) -> tuple[list[Calibration], list[str]]:
        found: list[Calibration] = []
        errors: list[str] = []
        for row in range(self.table.rowCount()):
            date = self._text(row, 0)
            lab = self._text(row, 1)
            factor_text = self._text(row, 2)
            if not date and not lab and not factor_text:
                continue
            if not factor_text:
                errors.append(f"Enter the calibration factor on row {row + 1}.")
                continue
            try:
                factor = float(factor_text)
            except ValueError:
                errors.append(f"Calibration factor on row {row + 1} is not a number.")
                continue
            found.append(Calibration(date=date, lab=lab, factor=factor))
        return found, errors


class ChamberDialog(QDialog):
    def __init__(self, chamber: Chamber | None, electrometers: list | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ion chamber")
        self.resize(640, 680)
        self.result_chamber: Chamber | None = None
        self._electrometers = list(electrometers or [])
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
        self.chamber_type = QComboBox()
        self.chamber_type.addItem("Cylinder", CHAMBER_CYLINDER)
        self.chamber_type.addItem("Parallel plate", CHAMBER_PARALLEL_PLATE)
        selected_type = chamber.chamber_type if chamber else CHAMBER_CYLINDER
        type_index = self.chamber_type.findData(selected_type)
        self.chamber_type.setCurrentIndex(type_index if type_index >= 0 else 0)
        self.chamber_type.currentIndexChanged.connect(self._sync_type)
        self.rcav_label = QLabel("Rcav [cm]")
        self.rcav = QLineEdit(format_input(chamber.rcav_cm) if chamber else "")
        stored_kecal = chamber.k_ecal if chamber and chamber.k_ecal is not None else None
        if stored_kecal is None:
            stored_kecal = kecal_hint(Chamber(id="", name="", model=str(self.model.currentData() or "")))
        self.k_ecal = QLineEdit(format_input(stored_kecal))
        self.model.currentIndexChanged.connect(self._fill_kecal_from_model)
        self._p_elec = chamber.p_elec if chamber else None
        self.electrometer = QComboBox()
        fill_electrometer_combo(
            self.electrometer,
            self._electrometers,
            chamber.electrometer_id if chamber else "",
            chamber.electrometer if chamber else "",
        )
        form.addRow("Name", self.name)
        form.addRow("Serial", self.serial)
        form.addRow("Model", self.model)
        form.addRow("Type", self.chamber_type)
        form.addRow(self.rcav_label, self.rcav)
        form.addRow("k_ecal", self.k_ecal)
        form.addRow("Electrometer", self.electrometer)
        layout.addLayout(form)
        calibrations = QGroupBox("Calibrations")
        calibration_layout = QVBoxLayout(calibrations)
        calibration_layout.addWidget(
            _hint("Each laboratory calibration is kept. A new TG-51 case uses the factor with the newest date.")
        )
        self.calibrations = CalibrationTable(
            "NDw [Gy/nC]",
            chamber.calibrations if chamber else [],
        )
        calibration_layout.addWidget(self.calibrations)
        layout.addWidget(calibrations)

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
        self._sync_type()
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

    def _fill_kecal_from_model(self) -> None:
        model = str(self.model.currentData() or "")
        if model == "custom":
            return
        hint = kecal_hint(Chamber(id="", name="", model=model))
        self.k_ecal.setText("" if hint is None else format_input(hint))

    def _sync_type(self) -> None:
        cylinder = self.chamber_type.currentData() == CHAMBER_CYLINDER
        self.rcav_label.setVisible(cylinder)
        self.rcav.setVisible(cylinder)

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
        electrometer_id, electrometer = chosen_electrometer(self.electrometer, self._electrometers)
        chamber_type = str(self.chamber_type.currentData() or CHAMBER_CYLINDER)
        rcav = None
        if chamber_type == CHAMBER_CYLINDER:
            rcav = _optional_float(self.rcav, errors, "Rcav")
            if rcav is None and not any(item.startswith("Rcav") for item in errors):
                errors.append("Enter Rcav for a cylindrical chamber.")
            elif rcav is not None and rcav <= 0:
                errors.append("Rcav must be greater than zero.")
        calibrations, calibration_errors = self.calibrations.read()
        errors.extend(calibration_errors)
        k_ecal = _optional_float(self.k_ecal, errors, "k_ecal")
        if k_ecal is not None and k_ecal <= 0:
            errors.append("k_ecal must be greater than zero.")
        if errors:
            QMessageBox.warning(self, "Ion chamber", "\n".join(errors))
            return
        self.result_chamber = Chamber(
            id=self._id,
            name=name,
            serial=self.serial.text().strip(),
            model=model,
            chamber_type=chamber_type,
            rcav_cm=rcav,
            p_elec=self._p_elec,
            k_ecal=k_ecal,
            electrometer_id=electrometer_id,
            electrometer=electrometer,
            calibrations=calibrations,
            photon_coefficients=photon,
            electron_coefficients=electron,
        )
        self.accept()


class ElectrometerDialog(QDialog):
    def __init__(self, electrometer: Electrometer | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Electrometer")
        self.resize(560, 420)
        self.result_electrometer: Electrometer | None = None
        self._id = electrometer.id if electrometer else new_id()
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(electrometer.name if electrometer else "")
        self.manufacturer = QLineEdit(electrometer.manufacturer if electrometer else "")
        self.model = QLineEdit(electrometer.model if electrometer else "")
        self.serial = QLineEdit(electrometer.serial if electrometer else "")
        form.addRow("Name", self.name)
        form.addRow("Manufacturer", self.manufacturer)
        form.addRow("Model", self.model)
        form.addRow("Serial", self.serial)
        layout.addLayout(form)
        calibrations = QGroupBox("Calibrations")
        calibration_layout = QVBoxLayout(calibrations)
        calibration_layout.addWidget(
            _hint("Each laboratory calibration is kept. A new TG-51 case uses the factor with the newest date.")
        )
        self.calibrations = CalibrationTable(
            "P_elec",
            electrometer.calibrations if electrometer else [],
        )
        calibration_layout.addWidget(self.calibrations)
        layout.addWidget(calibrations, 1)
        row = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self._accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addLayout(row)

    def _accept(self) -> None:
        name = self.name.text().strip()
        if not name:
            QMessageBox.warning(self, "Electrometer", "Enter a name.")
            return
        calibrations, errors = self.calibrations.read()
        if errors:
            QMessageBox.warning(self, "Electrometer", "\n".join(errors))
            return
        self.result_electrometer = Electrometer(
            id=self._id,
            name=name,
            manufacturer=self.manufacturer.text().strip(),
            model=self.model.text().strip(),
            serial=self.serial.text().strip(),
            calibrations=calibrations,
        )
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
        self.table.setHorizontalHeaderLabels(["Modality", "Nominal [MV/MeV]", "FFF"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        add = QPushButton("Add energy")
        remove = QPushButton("Remove energy")
        move_up = QPushButton("Move up")
        move_down = QPushButton("Move down")
        add.clicked.connect(lambda: self._add_energy(Energy(id=new_id(), modality="photon", nominal=6, fff=False)))
        remove.clicked.connect(self._remove_energy)
        move_up.clicked.connect(lambda: self._move_energy(-1))
        move_down.clicked.connect(lambda: self._move_energy(1))
        row.addWidget(add)
        row.addWidget(remove)
        row.addWidget(move_up)
        row.addWidget(move_down)
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

    def _energy_row(self, row: int) -> tuple:
        modality = self.table.cellWidget(row, 0)
        nominal = self.table.cellWidget(row, 1)
        fff = self.table.cellWidget(row, 2)
        return (
            modality.property("energy_id"),
            modality.currentIndex(),
            nominal.text(),
            fff.isChecked(),
        )

    def _set_energy_row(self, row: int, state: tuple) -> None:
        energy_id, index, text, checked = state
        modality = self.table.cellWidget(row, 0)
        nominal = self.table.cellWidget(row, 1)
        fff = self.table.cellWidget(row, 2)
        modality.blockSignals(True)
        modality.setProperty("energy_id", energy_id)
        modality.setCurrentIndex(index)
        modality.blockSignals(False)
        nominal.setText(text)
        self._sync_fff(modality, fff)
        if modality.currentData() == "photon":
            fff.setChecked(checked)

    def _move_energy(self, delta: int) -> None:
        row = self.table.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self.table.rowCount():
            return
        moving = self._energy_row(row)
        other = self._energy_row(target)
        self._set_energy_row(target, moving)
        self._set_energy_row(row, other)
        self.table.selectRow(target)

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
        self.catalog = catalog
        self.error = ""
        self.resize(460, 480)
        layout = QFormLayout(self)
        self.institution = QLineEdit(catalog.institution)
        self.family = QLineEdit(catalog.font_family)
        self.size = QLineEdit(str(catalog.font_size))
        self.dose_places = QLineEdit(str(catalog.dose_decimal_places))
        self.voltage_reference = QLineEdit(str(catalog.voltage_reference))
        self.voltage_reduced = QLineEdit(str(catalog.voltage_reduced))
        self.mu = QLineEdit(str(catalog.mu))
        self.tissue = QLineEdit(format_input(catalog.tissue_correction))
        self.field_size = QLineEdit(catalog.field_size)
        self.depth = QLineEdit(format_input(catalog.measurement_depth_cm))
        layout.addRow("Institution", self.institution)
        layout.addRow("Font family", self.family)
        layout.addRow("Font size [pt]", self.size)
        layout.addRow(_hint("Leave the family blank and the size at 0 to use the platform font plus 3 pt, with a 13 pt floor."))
        layout.addRow("Vref [V]", self.voltage_reference)
        layout.addRow("Vreduced [V]", self.voltage_reduced)
        layout.addRow("MU", self.mu)
        layout.addRow("Tissue correction", self.tissue)
        layout.addRow("Field size [cm]", self.field_size)
        layout.addRow("Measurement depth [cm]", self.depth)
        layout.addRow(_hint("These apply to every calibration. Photon depth is this value. Electron depth is dref."))
        layout.addRow("Dose decimal places", self.dose_places)
        layout.addRow(
            _hint(
                "Digits after the decimal for dose in cGy on the form and the calibration list. "
                "The Calculations panel keeps the full figures."
            )
        )
        row = QHBoxLayout()
        ok = QPushButton("OK")
        cancel = QPushButton("Cancel")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(ok)
        row.addWidget(cancel)
        layout.addRow(row)

    def values(self) -> dict | None:
        text = self.size.text().strip() or "0"
        try:
            size = int(text)
        except ValueError:
            self.error = "Font size must be a whole number, 0 or greater."
            return None
        if size < 0:
            self.error = "Font size must be a whole number, 0 or greater."
            return None
        errors: list[str] = []
        voltage_reference = _optional_int(self.voltage_reference, errors, "Vref")
        voltage_reduced = _optional_int(self.voltage_reduced, errors, "Vreduced")
        mu = _optional_int(self.mu, errors, "MU")
        tissue = _optional_float(self.tissue, errors, "Tissue correction")
        depth = _optional_float(self.depth, errors, "Measurement depth")
        field_size = self.field_size.text().strip()
        if not field_size:
            errors.append("Enter the field size.")
        if voltage_reference is None or voltage_reduced is None or mu is None or tissue is None or depth is None:
            self.error = "\n".join(errors) or "Enter the setup values."
            return None
        if voltage_reference == 0 or voltage_reduced == 0:
            errors.append("Enter a non-zero reference voltage and reduced voltage.")
        elif (voltage_reference > 0) != (voltage_reduced > 0):
            errors.append("Reference and reduced voltages must have the same sign.")
        elif abs(voltage_reduced) >= abs(voltage_reference):
            errors.append("Reduced voltage must be lower in magnitude than the reference voltage.")
        if mu <= 0:
            errors.append("MU must be greater than zero.")
        if tissue <= 0:
            errors.append("Tissue correction must be greater than zero.")
        if depth <= 0:
            errors.append("Measurement depth must be greater than zero.")
        dose_places = _optional_int(self.dose_places, errors, "Dose decimal places")
        if dose_places is None and not any(error.startswith("Dose decimal places") for error in errors):
            errors.append("Enter the dose decimal places.")
        elif dose_places is not None and not 0 <= dose_places <= 6:
            errors.append("Dose decimal places must be a whole number from 0 to 6.")
        ranges = valid_ranges({"ValidRanges": self.catalog.valid_ranges})
        for key, value, unit in (
            ("voltage_reference", abs(voltage_reference), "V"),
            ("voltage_reduced", abs(voltage_reduced), "V"),
            ("mu", mu, "MU"),
            ("tissue_correction", tissue, ""),
        ):
            message = range_message(FIELD_LABELS[key], value, ranges.get(key), unit)
            if message:
                errors.append(message)
        if errors:
            self.error = "\n".join(errors)
            return None
        return {
            "institution": self.institution.text().strip(),
            "family": self.family.text().strip(),
            "size": size,
            "voltage_reference": voltage_reference,
            "voltage_reduced": voltage_reduced,
            "mu": mu,
            "tissue_correction": tissue,
            "field_size": field_size,
            "measurement_depth_cm": depth,
            "dose_decimal_places": dose_places,
        }


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


def _stored_number(value, places: int) -> str:
    if value is None:
        return ""
    return f"{float(value):.{places}f}"


def _case_columns(electron: bool) -> list[str]:
    columns = ["Date", "Physicist", "Chamber", "Ptp", "Pion", "Ppol", "P_elec"]
    if electron:
        columns.extend(["Pgr", "k_ecal", "I50 [cm]", "R50 [cm]", "dref [cm]"])
    columns.extend(["M corrected [nC]", "kQ", "Dose at dmax [cGy]", "Status", "Comments"])
    return columns


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
        self._case_windows: dict[str, CaseDialog] = {}
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
        self._window_memory = WindowMemory(self, self.settings_file, "Main", (1100, 720))

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
        for index, name in enumerate(("Calibrations", "Machines", "Ion Chambers", "Electrometers", "Users")):
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
        self.case_table = _table(_case_columns(False))
        self.case_table.doubleClicked.connect(lambda *_args: self._edit_case(self._selected_case()))
        self.case_table.itemSelectionChanged.connect(self._update_case_buttons)
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
        self.splitter = splitter
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

        self.chamber_table = _table(
            ["Name", "Model", "Type", "Rcav [cm]", "Serial", "NDw [Gy/nC]", "Calibrated", "k_ecal", "Electrometer"]
        )
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
        self._add_page(page, "Chambers keep the calibration-lab NDw and point at an electrometer.", _action_bar(add_c, edit_c, del_c))

        self.electrometer_table = _table(["Name", "Manufacturer", "Model", "Serial", "P_elec", "Calibrated"])
        self.electrometer_table.doubleClicked.connect(lambda *_args: self._edit_electrometer())
        add_e = QPushButton("New")
        edit_e = QPushButton("Edit")
        del_e = QPushButton("Delete")
        add_e.clicked.connect(lambda: self._edit_electrometer(new=True))
        edit_e.clicked.connect(self._edit_electrometer)
        del_e.clicked.connect(lambda: self._delete_record("electrometer"))
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 0, 12, 12)
        layout.addWidget(self.electrometer_table)
        self._add_page(
            page,
            "Electrometers keep P_elec. A calibration picks one and shows that factor beside the choice.",
            _action_bar(add_e, edit_e, del_e),
        )

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

    def _remember(self, dialog: QDialog, name: str) -> None:
        WindowMemory(dialog, self.settings_file, name, (dialog.width(), dialog.height()))

    def window_extra_state(self) -> dict:
        state = {}
        page = self.nav.checkedId()
        if page >= 0:
            state["page"] = page
        splitter = getattr(self, "splitter", None)
        if splitter is not None:
            sizes = [int(size) for size in splitter.sizes()]
            if sizes and all(size > 0 for size in sizes):
                state["splitter"] = sizes
        return state

    def apply_window_extra_state(self, state: dict) -> None:
        page = state.get("page")
        if isinstance(page, int) and self.nav.button(page) is not None:
            button = self.nav.button(page)
            button.setChecked(True)
            self._show_page(button)
        sizes = state.get("splitter")
        if (
            isinstance(sizes, list)
            and sizes
            and all(isinstance(size, int) and size > 0 for size in sizes)
        ):
            self._pending_splitter = sizes

    def showEvent(self, event) -> None:
        super().showEvent(event)
        memory = getattr(self, "_window_memory", None)
        if memory is not None:
            memory.on_show()
        splitter = getattr(self, "splitter", None)
        sizes = getattr(self, "_pending_splitter", None)
        if splitter is not None and sizes and len(sizes) == splitter.count():
            splitter.setSizes(sizes)
        self._pending_splitter = None

    def closeEvent(self, event) -> None:
        memory = getattr(self, "_window_memory", None)
        if memory is not None:
            memory.save()
        super().closeEvent(event)

    def _save_catalog(self) -> None:
        save_settings(self.catalog.to_settings(), self.settings_file)
        self._refresh()

    def _refresh(self) -> None:
        self.institution_label.setText(self.catalog.institution)
        self.institution_label.setVisible(bool(self.catalog.institution))
        self._fill_tree()
        self._fill_machines()
        self._fill_chambers()
        self._fill_electrometers()
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
        electron = energy is not None and energy.modality == "electron"
        headers = _case_columns(electron)
        self.case_table.setColumnCount(len(headers))
        self.case_table.setHorizontalHeaderLabels(headers)
        selected = _selected_id(self.case_table)
        rows = []
        comments = []
        if machine is not None and energy is not None:
            for case in self.store.for_energy(machine.id, energy.id):
                user = self.catalog.user(case.user_id)
                chamber = self.catalog.chamber(case.chamber_id)
                result = case.result or {}
                kq = _stored_number(result.get("kq"), 5)
                dose = ""
                if result.get("dose_mu_dmax") is not None and case.mu:
                    dose = f"{float(result['dose_mu_dmax']) * case.mu:.{self.catalog.dose_decimal_places}f}"
                cells = [
                    case.measurement_date,
                    user.name if user else "",
                    chamber.name if chamber else "",
                    _stored_number(result.get("p_tp"), 4),
                    _stored_number(result.get("p_ion"), 4),
                    _stored_number(result.get("p_pol"), 4),
                    _stored_number(case.p_elec, 4),
                ]
                if electron:
                    cells.extend(
                        [
                            _stored_number(result.get("pq_gr"), 4),
                            _stored_number(case.k_ecal, 4),
                            _stored_number(case.i_50, 2),
                            _stored_number(result.get("r_50"), 2),
                            _stored_number(result.get("dref"), 2),
                        ]
                    )
                cells.extend(
                    [
                        _stored_number(result.get("m_corrected"), 3),
                        kq,
                        dose,
                        "Calculated" if case.status == "calculated" else "Draft",
                        " ".join(case.comment.split()),
                    ]
                )
                rows.append((case.id, cells))
                comments.append(case.comment)
        _fill_table(self.case_table, rows, selected)
        comment_column = headers.index("Comments")
        for row_index, text in enumerate(comments):
            item = self.case_table.item(row_index, comment_column)
            if item is not None and text:
                item.setToolTip(text)
        self._update_case_buttons()

    def _update_case_buttons(self) -> None:
        if not hasattr(self, "_case_buttons"):
            return
        machine, energy = self._current_energy()
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
            latest = self.store.latest_for_machine(machine.id)
            if latest is not None:
                case.copy_shared_setup(latest)
        existing = self._case_windows.get(case.id)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        settings_data = {
            "ValidRanges": self.catalog.valid_ranges,
            "PreviousCalibrationWarnPercent": self.catalog.history_warn_percent,
        }
        previous = [
            item
            for item in self.store.for_energy(machine.id, energy.id)
            if item.id != case.id and item.status == "calculated"
        ]
        dialog = CaseDialog(
            self,
            catalog=self.catalog,
            machine=machine,
            energy=energy,
            case=case,
            on_save=self._save_open_case,
            previous=previous,
            ranges=valid_ranges(settings_data),
            history_percent=history_warn_percent(settings_data),
        )
        dialog.setModal(False)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        self._case_windows[case.id] = dialog
        self._remember(dialog, "Case")
        dialog.finished.connect(lambda *_args, case_id=case.id: self._case_closed(case_id))
        self._stagger_case_window(dialog)
        dialog.show()

    def _save_open_case(self, case: CalibrationCase) -> None:
        self.store.save(case)
        self._fill_cases()

    def _case_closed(self, case_id: str) -> None:
        self._case_windows.pop(case_id, None)
        self._fill_cases()

    def _stagger_case_window(self, dialog: CaseDialog) -> None:
        index = len(self._case_windows) - 1
        if index <= 0:
            return
        dialog.move(dialog.x() + 28 * index, dialog.y() + 28 * index)
        _fit_on_screen(dialog)

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
        if case.id in self._case_windows:
            open_dialog = self._case_windows[case.id]
            open_dialog.show()
            open_dialog.raise_()
            open_dialog.activateWindow()
            QMessageBox.information(self, "Delete case", "Close this calibration before deleting it.")
            return
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
                        chamber_type_label(chamber.chamber_type),
                        "" if chamber.chamber_type == CHAMBER_PARALLEL_PLATE else format_input(chamber.rcav_cm),
                        chamber.serial,
                        format_input(chamber.n_dw),
                        chamber.calibration_date,
                        format_input(chamber_kecal(chamber)),
                        self._electrometer_text(chamber),
                    ],
                )
            )
        _fill_table(self.chamber_table, rows, selected)

    def _electrometer_text(self, chamber: Chamber) -> str:
        item = self.catalog.electrometer(chamber.electrometer_id)
        if item is not None:
            return electrometer_label(item)
        return chamber.electrometer

    def _fill_electrometers(self) -> None:
        selected = _selected_id(self.electrometer_table)
        rows = [
            (item.id, [item.name, item.manufacturer, item.model, item.serial, format_input(item.p_elec), item.calibration_date])
            for item in self.catalog.electrometers
        ]
        _fill_table(self.electrometer_table, rows, selected)

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
        self._remember(dialog, "Machine")
        if dialog.exec_() != QDialog.Accepted or dialog.result_machine is None:
            return
        self.catalog.machines = _upsert(self.catalog.machines, dialog.result_machine)
        self._save_catalog()

    def _edit_chamber(self, new: bool = False) -> None:
        current = None if new else self.catalog.chamber(_selected_id(self.chamber_table))
        if not new and current is None:
            QMessageBox.information(self, "Ion Chambers", "Select an ion chamber first.")
            return
        dialog = ChamberDialog(current, self.catalog.electrometers, self)
        self._remember(dialog, "Chamber")
        if dialog.exec_() != QDialog.Accepted or dialog.result_chamber is None:
            return
        self.catalog.chambers = _upsert(self.catalog.chambers, dialog.result_chamber)
        self._save_catalog()

    def _edit_electrometer(self, new: bool = False) -> None:
        current = None if new else self.catalog.electrometer(_selected_id(self.electrometer_table))
        if not new and current is None:
            QMessageBox.information(self, "Electrometers", "Select an electrometer first.")
            return
        dialog = ElectrometerDialog(current, self)
        self._remember(dialog, "Electrometer")
        if dialog.exec_() != QDialog.Accepted or dialog.result_electrometer is None:
            return
        self.catalog.electrometers = _upsert(self.catalog.electrometers, dialog.result_electrometer)
        self._save_catalog()

    def _edit_user(self, new: bool = False) -> None:
        current = None if new else self.catalog.user(_selected_id(self.user_table))
        if not new and current is None:
            QMessageBox.information(self, "Users", "Select a user first.")
            return
        dialog = UserDialog(current, self)
        self._remember(dialog, "User")
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
        elif kind == "electrometer":
            record_id = _selected_id(self.electrometer_table)
            title = "Electrometers"
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
        elif kind == "electrometer":
            self.catalog.electrometers = [item for item in self.catalog.electrometers if item.id != record_id]
        else:
            self.catalog.users = [item for item in self.catalog.users if item.id != record_id]
        self._save_catalog()

    def _edit_settings(self) -> None:
        dialog = SettingsDialog(self.catalog, self)
        self._remember(dialog, "Settings")
        if dialog.exec_() != QDialog.Accepted:
            return
        values = dialog.values()
        if values is None:
            QMessageBox.warning(self, "Settings", dialog.error or "Check the settings values.")
            return
        self.catalog.institution = values["institution"]
        self.catalog.font_family = values["family"]
        self.catalog.font_size = values["size"]
        self.catalog.voltage_reference = values["voltage_reference"]
        self.catalog.voltage_reduced = values["voltage_reduced"]
        self.catalog.mu = values["mu"]
        self.catalog.tissue_correction = values["tissue_correction"]
        self.catalog.field_size = values["field_size"]
        self.catalog.measurement_depth_cm = values["measurement_depth_cm"]
        self.catalog.dose_decimal_places = values["dose_decimal_places"]
        self._save_catalog()
        app = QApplication.instance()
        if app is not None:
            app.setFont(
                themed_font(
                    QFont(),
                    {"Font": {"family": self.catalog.font_family, "size": self.catalog.font_size}},
                )
            )
