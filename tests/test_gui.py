from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QLabel, QPushButton
from pylinac.calibration import tg51

import re

from tg51app.app_settings import save_settings
from tg51app.gui import (
    RANGE_EDIT_STYLE,
    HISTORY_EDIT_STYLE,
    NEEDED_EDIT_STYLE,
    CaseDialog,
    ChamberDialog,
    ElectrometerDialog,
    MachineDialog,
    MainWindow,
    _bold_dmax,
    _with_dose_places,
    themed_font,
)
from tg51app.calc import electron_dref, electron_r50
from tg51app.models import Calibration, CalibrationCase, CaseStore, Electrometer, electrometer_label
from tests.samples import example_catalog, electron_case, photon_case


def test_dose_display_rounds_outside_the_calculations_panel():
    assert _with_dose_places("Dose at dmax: 102.0121 [cGy]", 2) == "Dose at dmax: 102.01 [cGy]"
    assert (
        _with_dose_places("Dose at dmax, adjusted: 99.9335 [cGy]", 2)
        == "Dose at dmax, adjusted: 99.93 [cGy]"
    )


def test_pion_above_five_percent_is_red_bold():
    high = _bold_dmax("Pion: 1.0600\nPpol: 0.9990", underline_results=True)
    assert '<font color="#dc2626"><b><u>Pion: 1.0600</u></b></font>' in high
    assert "Recombination is above 5%. Investigate or replace the chamber." in high
    assert "#dc2626" not in high.split("Ppol:", 1)[1]
    normal = _bold_dmax("Pion: 1.0028")
    assert "#dc2626" not in normal
    exact = _bold_dmax("Pion: 1.0500")
    assert "#dc2626" not in exact


def test_electron_kecal_is_shown_from_the_chamber(qapp):
    catalog = example_catalog()
    catalog.chamber("chamber").rcav_cm = 0.305
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy9"),
        case=electron_case(),
        on_save=lambda _case: None,
    )
    assert isinstance(dialog.k_ecal, QLabel)
    assert dialog.k_ecal.text() == "0.901"
    assert dialog.r50.text() == f"{electron_r50(3.52):.2f}"
    assert dialog.dref_value.text() == f"{electron_dref(3.52):.2f}"
    assert dialog.depth_value.text() == f"{electron_dref(3.52):.2f} [cm]"
    assert dialog.clinical_pdd_label.text() == f"Clinical PDD (dref={electron_dref(3.52):.2f} cm) [%]"
    details = dialog.calculations_label.text()
    assert "<u>R50:" in details
    assert "<u>dref:" in details
    assert "1.029" in details
    assert "0.6 ×" in details
    depth = f"dref={electron_dref(3.52):.2f} cm"
    shift = electron_dref(3.52) + 0.5 * 0.305
    assert dialog.pgr_box.title() == "Pgr"
    assert not dialog.pgr_box.isHidden()
    assert dialog.gradient_labels[0].text() == f"M(300V, dref+0.5rcav={shift:.2f} cm) [nC]"
    assert [cell.text() for cell in dialog.m_gradient.cells] == ["25.4", "25.41", "25.4"]
    assert dialog.m_gradient.average.text()
    dialog.method.setCurrentIndex(dialog.method.findData("modern"))
    assert dialog.pgr_box.isHidden()
    dialog.method.setCurrentIndex(dialog.method.findData("legacy"))
    assert [label.text() for label in dialog.reading_labels] == [
        f"M(300V, {depth}) [nC]",
        f"M(-300V, {depth}) [nC]",
        f"M(150V, {depth}) [nC]",
    ]
    assert dialog.post_labels[0].text() == f"M(300V, {depth}) [nC]"
    dialog.i_50.setText("")
    assert dialog.reading_labels[0].text() == "M(300V, dref) [nC]"
    assert dialog.post_labels[0].text() == "M(300V, dref) [nC]"
    assert dialog.gradient_labels[0].text() == "M(300V, dref+0.5rcav) [nC]"
    assert dialog.r50.text() == ""
    assert dialog.dref_value.text() == ""
    assert dialog.depth_value.text() == ""
    assert dialog.clinical_pdd_label.text() == "Clinical PDD (dref) [%]"
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert "Cone size" in labels
    assert "Field size" not in labels
    assert "dref" in labels
    assert "Measurement depth" not in labels
    collected, errors = dialog._collect()
    assert errors == []
    assert collected is not None
    assert collected.cone == catalog.field_size
    editor = ChamberDialog(catalog.chamber("chamber"), catalog.electrometers)
    assert editor.k_ecal.text() == "0.901"
    dialog._close_choice = lambda: "discard"
    dialog.close()
    editor.close()


def test_new_calibration_dialog_uses_the_last_saved_setup(qapp, tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    cases = tmp_path / "_cases"
    CaseStore(cases).save(photon_case())
    window = MainWindow(settings_path=settings, cases_dir=cases)
    window.show()
    qapp.processEvents()
    window._edit_case(None)
    qapp.processEvents()
    dialog = next(iter(window._case_windows.values()))
    assert dialog.date.date().toString("yyyy-MM-dd") == "2026-04-01"
    assert dialog.temp.text() == "22.1"
    assert dialog.temp_unit.currentData() == "C"
    assert dialog.press.text() == "755"
    assert dialog.press_unit.currentData() == "mmHg"
    assert dialog.user_combo.currentData() == "user"
    assert dialog.chamber_combo.currentData() == "chamber"
    assert dialog.m_reference.edits()[0].text() == ""
    assert dialog.measured_pdd10.text() == ""
    dialog.close()
    qapp.processEvents()
    window.close()


def test_recalculating_an_open_case_is_not_an_edit(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    case = photon_case()
    case.status = "calculated"
    case.result = {"kq": 1.0, "dose_mu_dmax": 1.0}
    case.pylinac_version = "old"
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=case,
        on_save=lambda _case: None,
    )
    dialog.show()
    qapp.processEvents()
    assert dialog._is_dirty() is False
    dialog._calculate_now()
    qapp.processEvents()
    assert dialog._is_dirty() is False
    dialog.comment.setPlainText("Output adjusted after the first reading.")
    assert dialog._is_dirty() is True
    dialog.comment.setPlainText("")
    assert dialog._is_dirty() is False
    dialog._closing = True
    dialog.close()
    qapp.processEvents()


def test_new_case_uses_the_latest_calibration(qapp):
    catalog = example_catalog()
    chamber = catalog.chamber("chamber")
    chamber.calibrations = [
        Calibration(date="1/1/2020", lab="ADCL", factor=5.3),
        Calibration(date="11/1/2024", lab="ADCL", factor=5.5),
    ]
    chamber.__post_init__()
    machine = catalog.machine("machine")
    old = photon_case()
    old.n_dw = 5.443
    kept = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=old,
        on_save=lambda _case: None,
    )
    assert "5.443" in kept.n_dw.text()
    fresh = CalibrationCase.new(machine.id, "energy6")
    fresh.chamber_id = chamber.id
    opened = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=fresh,
        on_save=lambda _case: None,
    )
    assert "5.5" in opened.n_dw.text()
    kept._closing = True
    opened._closing = True
    kept.close()
    opened.close()


def test_save_leaves_the_calibration_open_until_close(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    saved = []
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=saved.append,
    )
    dialog.show()
    qapp.processEvents()
    assert dialog._is_dirty() is False
    dialog.temp.setText("21.5")
    qapp.processEvents()
    assert dialog._is_dirty() is True
    dialog._close_choice = lambda: "cancel"
    dialog.close()
    qapp.processEvents()
    assert dialog.isVisible()
    assert saved == []
    assert dialog.save_case(close=False)
    qapp.processEvents()
    assert dialog.isVisible()
    assert saved[-1].temp_value == 21.5
    assert dialog._is_dirty() is False
    dialog.press.setText("760")
    qapp.processEvents()
    dialog._close_choice = lambda: "discard"
    dialog.close()
    qapp.processEvents()
    assert not dialog.isVisible()
    assert saved[-1].press_value == 755.0

    again = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=saved.append,
    )
    again.show()
    qapp.processEvents()
    again.temp.setText("20")
    qapp.processEvents()
    again._close_choice = lambda: "save"
    again.close()
    qapp.processEvents()
    assert not again.isVisible()
    assert saved[-1].temp_value == 20.0


def test_default_font_is_platform_plus_three_with_a_13pt_floor(qapp):
    base = QFont()
    base.setPointSize(10)
    bumped = themed_font(base, {"Font": {"family": "", "size": 0}})
    assert bumped.pointSize() == 13
    named = themed_font(base, {"Font": {"family": "Consolas", "size": 16}})
    assert named.family() == "Consolas"
    assert named.pointSize() == 16


def test_machine_energies_can_be_reordered(qapp):
    machine = example_catalog().machine("machine")
    dialog = MachineDialog(machine, lambda _energy_id: "")
    assert dialog.table.rowCount() == 2
    dialog.table.cellWidget(0, 1).setText("6")
    dialog.table.cellWidget(0, 2).setChecked(True)
    dialog.table.cellWidget(1, 1).setText("9")
    first_id = dialog.table.cellWidget(0, 0).property("energy_id")
    second_id = dialog.table.cellWidget(1, 0).property("energy_id")
    dialog.table.selectRow(1)
    dialog._move_energy(-1)
    qapp.processEvents()
    assert dialog.table.cellWidget(0, 0).property("energy_id") == second_id
    assert dialog.table.cellWidget(0, 0).currentData() == "electron"
    assert dialog.table.cellWidget(0, 1).text() == "9"
    assert dialog.table.cellWidget(0, 2).isChecked() is False
    assert dialog.table.cellWidget(1, 0).property("energy_id") == first_id
    assert dialog.table.cellWidget(1, 0).currentData() == "photon"
    assert dialog.table.cellWidget(1, 1).text() == "6"
    assert dialog.table.cellWidget(1, 2).isChecked() is True
    dialog._accept()
    assert dialog.result_machine is not None
    assert [energy.id for energy in dialog.result_machine.energies] == [second_id, first_id]
    assert dialog.result_machine.energies[0].nominal == 9
    assert dialog.result_machine.energies[1].nominal == 6
    assert dialog.result_machine.energies[1].fff is True
    dialog.close()


def test_calibration_list_shows_correction_factors(qapp, tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    case = photon_case()
    case.comment = "Output adjusted after the first reading."
    case.status = "calculated"
    case.result = {
        "kq": 0.99172,
        "p_tp": 1.0074,
        "p_ion": 1.0028,
        "p_pol": 0.9986,
        "m_corrected": 12.625,
        "dose_mu_dmax": 0.5100605,
    }
    CaseStore(tmp_path / "_cases").save(case)
    window = MainWindow(settings_path=settings, cases_dir=tmp_path / "_cases")
    window.show()
    qapp.processEvents()
    headers = [
        window.case_table.horizontalHeaderItem(column).text()
        for column in range(window.case_table.columnCount())
    ]
    assert headers == [
        "Date",
        "Physicist",
        "Chamber",
        "Ptp",
        "Pion",
        "Ppol",
        "P_elec",
        "M corrected [nC]",
        "kQ",
        "Dose at dmax [cGy]",
        "Status",
        "Comments",
    ]
    assert window.case_table.item(0, headers.index("Comments")).text() == case.comment
    values = [window.case_table.item(0, column).text() for column in range(3, 9)]
    assert values == ["1.0074", "1.0028", "0.9986", "1.0000", "12.625", "0.99172"]
    electron = electron_case()
    electron.status = "calculated"
    electron.result = {
        "kq": 0.91234,
        "p_tp": 1.0012,
        "p_ion": 1.0040,
        "p_pol": 0.9991,
        "m_corrected": 20.125,
        "dose_mu_dmax": 0.48,
        "pq_gr": 0.9934,
        "r_50": 3.56208,
        "dref": 2.03725,
    }
    CaseStore(tmp_path / "_cases").save(electron)
    window.store = CaseStore(tmp_path / "_cases")
    window.tree.setCurrentItem(window.tree.topLevelItem(0).child(1))
    qapp.processEvents()
    electron_headers = [
        window.case_table.horizontalHeaderItem(column).text()
        for column in range(window.case_table.columnCount())
    ]
    assert electron_headers[7:13] == ["Pgr", "k_ecal", "I50 [cm]", "R50 [cm]", "dref [cm]", "M corrected [nC]"]
    electron_values = [window.case_table.item(0, column).text() for column in range(7, 13)]
    assert electron_values == ["0.9934", "0.9010", "3.52", "3.56", "2.04", "20.125"]
    window.close()


def test_selecting_a_calibration_enables_its_buttons(qapp, tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    cases = tmp_path / "_cases"
    CaseStore(cases).save(photon_case())
    window = MainWindow(settings_path=settings, cases_dir=cases)
    window.show()
    qapp.processEvents()
    assert window.case_table.rowCount() == 1
    assert window._case_buttons["new"].isEnabled()
    assert window._case_buttons["edit"].isEnabled() is False
    window.case_table.selectRow(0)
    qapp.processEvents()
    for key in ("edit", "duplicate", "delete", "pdf"):
        assert window._case_buttons[key].isEnabled()
    window.close()


def test_window_lists_machine_energies(qapp, tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    window = MainWindow(settings_path=settings, cases_dir=tmp_path / "_cases")
    window.show()
    machine = window.tree.topLevelItem(0)
    assert machine.text(0) == "TrueBeam1"
    labels = [machine.child(index).text(0) for index in range(machine.childCount())]
    assert labels == ["6 MV", "9 MeV"]
    assert window.case_table.rowCount() == 0
    names = [window.nav.button(index).text() for index in range(5)]
    assert names == ["Calibrations", "Machines", "Ion Chambers", "Electrometers", "Users"]
    window.nav.button(3).click()
    qapp.processEvents()
    assert window.electrometer_table.rowCount() == 1
    assert window.electrometer_table.item(0, 0).text() == "Keithley"
    window.close()


def test_several_calibrations_stay_open_together(qapp, tmp_path):
    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    window = MainWindow(settings_path=settings, cases_dir=tmp_path / "_cases")
    window.show()
    qapp.processEvents()
    window._edit_case(None)
    window._edit_case(None)
    qapp.processEvents()
    assert len(window._case_windows) == 2
    dialogs = list(window._case_windows.values())
    assert dialogs[0].isVisible() and dialogs[1].isVisible()
    assert dialogs[0].isModal() is False
    first = dialogs[0].case
    window._edit_case(first)
    qapp.processEvents()
    assert len(window._case_windows) == 2
    assert window._case_windows[first.id] is dialogs[0]
    dialogs[0].close()
    qapp.processEvents()
    assert first.id not in window._case_windows
    assert len(window._case_windows) == 1
    remaining = next(iter(window._case_windows.values()))
    remaining.close()
    qapp.processEvents()
    window.close()


def test_window_and_dialog_sizes_are_restored(qapp, tmp_path):
    from tg51app.gui import WindowMemory

    settings = tmp_path / "settings.json"
    save_settings(example_catalog().to_settings(), settings)
    cases = tmp_path / "_cases"
    window = MainWindow(settings_path=settings, cases_dir=cases)
    window.show()
    qapp.processEvents()
    window.resize(1500, 800)
    window.nav.button(2).click()
    qapp.processEvents()
    width, height = window.width(), window.height()
    window.close()

    again = MainWindow(settings_path=settings, cases_dir=cases)
    again.show()
    qapp.processEvents()
    assert abs(again.width() - width) < 40
    assert abs(again.height() - height) < 40
    assert again.nav.checkedId() == 2

    catalog = example_catalog()
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    WindowMemory(dialog, settings, "Case", (dialog.width(), dialog.height()))
    dialog.show()
    qapp.processEvents()
    dialog.resize(960, 760)
    qapp.processEvents()
    dialog_width, dialog_height = dialog.width(), dialog.height()
    dialog.close()

    second = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    WindowMemory(second, settings, "Case", (second.width(), second.height()))
    second.show()
    qapp.processEvents()
    assert abs(second.width() - dialog_width) < 40
    assert abs(second.height() - dialog_height) < 40
    second.close()
    again.close()


def test_electrometer_dialog_stores_the_instrument_label(qapp):
    dialog = ElectrometerDialog(None)
    dialog.name.setText("MAX-4000")
    dialog.manufacturer.setText("Standard Imaging")
    dialog.model.setText("MAX-4000")
    dialog.serial.setText("E021075")
    dialog.calibrations.add_row("", "", "1.0")
    dialog._accept()
    meter = dialog.result_electrometer
    assert meter is not None
    assert meter.p_elec == 1.0
    assert len(meter.calibrations) == 1
    assert meter.calibrations[0].factor == 1.0
    assert electrometer_label(meter) == "Standard Imaging MAX-4000 (E021075)"
    dialog.close()


def test_calibration_factors_follow_the_dropdowns(qapp):
    catalog = example_catalog()
    catalog.electrometers.append(Electrometer(id="meter", name="MAX-4000", p_elec=0.999))
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    assert isinstance(dialog.n_dw, QLabel)
    assert isinstance(dialog.p_elec, QLabel)
    assert "5.443" in dialog.n_dw.text()
    assert "Gy/nC" in dialog.n_dw.text()
    assert dialog.p_elec.text() == "P_elec  1"
    dialog.electrometer.setCurrentIndex(dialog.electrometer.findData("meter"))
    qapp.processEvents()
    assert dialog.p_elec.text() == "P_elec  0.999"
    labels = dialog.findChildren(QLabel)
    texts = [label.text() for label in labels]
    assert "300 [V]" in texts
    assert "150 [V]" in texts
    assert "100" in texts
    assert "10×10 [cm]" in texts
    assert "10 [cm]" in texts
    dialog._close_choice = lambda: "discard"
    dialog.close()


def test_case_dialog_matches_pylinac_and_keeps_a_calculated_case(qapp, tmp_path):
    catalog = example_catalog()
    catalog.voltage_reference = -300
    catalog.voltage_reduced = -150
    catalog.mu = 200
    catalog.tissue_correction = 1.0
    machine = catalog.machine("machine")
    energy = machine.energy("energy6")
    saved = []
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=energy,
        case=photon_case(),
        on_save=saved.append,
    )
    outcome = dialog.run_calculation()
    assert outcome.errors == [], outcome.errors
    direct = tg51.TG51Photon(
        institution="UH",
        physicist="Ada Physicist",
        unit="TrueBeam1",
        measurement_date="2026-04-01",
        temp=22.1,
        press=tg51.mmHg2kPa(755.0),
        chamber="30013",
        n_dw=5.443,
        p_elec=1.0,
        electrometer="Keithley",
        measured_pdd10=66.4,
        lead_foil=None,
        clinical_pdd10=66.5,
        energy=6,
        fff=False,
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=(25.65, 25.66, 25.65),
        m_opposite=(25.64, 25.65, 25.65),
        m_reduced=(25.64, 25.63, 25.63),
        mu=200,
        tissue_correction=1.0,
        m_reference_adjusted=(25.44, 25.44, 25.43),
    )
    assert outcome.result["kq"] == direct.kq
    assert outcome.result["dose_mu_dmax"] == direct.dose_mu_dmax
    dialog.apply_outcome(outcome)
    assert dialog.save_case(close=False)
    assert saved[-1].status == "calculated"

    store = CaseStore(tmp_path)
    store.save(saved[-1])
    reloaded = store.load_all()[0]
    again = []
    second = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=energy,
        case=reloaded,
        on_save=again.append,
    )
    assert second.save_case(close=False)
    assert again[-1].status == "calculated"
    assert again[-1].result["kq"] == direct.kq
    dialog.close()
    second.close()


def test_blank_required_fields_are_orange_and_calculation_waits(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    assert dialog._calc_timer.isActive()
    assert dialog._calc_timer.interval() == 400
    assert all(button.text() != "Calculate" for button in dialog.findChildren(QPushButton))
    dialog._calculate_now()
    assert dialog._result is not None
    assert dialog._result["kq"]
    dialog.measured_pdd10.clear()
    assert dialog.measured_pdd10.styleSheet() == NEEDED_EDIT_STYLE
    for cell in dialog.m_reference.cells:
        cell.clear()
    assert all(cell.styleSheet() == NEEDED_EDIT_STYLE for cell in dialog.m_reference.cells)
    dialog.m_reference.cells[0].setText("25.65")
    assert dialog.m_reference.cells[0].styleSheet() == ""
    assert dialog.m_reference.cells[1].styleSheet() == ""
    for cell in dialog.m_adjusted.cells:
        cell.clear()
    assert all(cell.styleSheet() != NEEDED_EDIT_STYLE for cell in dialog.m_adjusted.cells)
    dialog._calculate_now()
    assert dialog._result is None
    assert "Enter PDD(10)x." not in dialog.warning_label.text()
    dialog._close_choice = lambda: "discard"
    dialog.close()


def test_out_of_range_pdd_turns_the_field_red(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    dialog.measured_pdd10.setText("0.664")
    dialog.clinical_pdd10.setText("0.664")
    qapp.processEvents()
    assert "fde8e8" in dialog.measured_pdd10.styleSheet()
    assert dialog.measured_pdd10.styleSheet() == RANGE_EDIT_STYLE
    assert "PDD(10)x" in dialog.warning_label.text()
    dialog._close_choice = lambda: "discard"
    dialog.close()


def test_previous_calibration_mean_turns_the_field_amber(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    previous = photon_case()
    previous.status = "calculated"
    previous.m_reference = [10.0]
    current = photon_case()
    current.id = "later"
    current.m_reference = [12.0]
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=current,
        on_save=lambda _case: None,
        previous=[previous],
        history_percent=5,
    )
    qapp.processEvents()
    assert dialog.m_reference.edits()[0].styleSheet() == HISTORY_EDIT_STYLE
    assert "M at Vref" in dialog.warning_label.text()
    dialog.close()


def test_reading_average_uses_only_entered_values(qapp):
    catalog = example_catalog()
    machine = catalog.machine("machine")
    dialog = CaseDialog(
        None,
        catalog=catalog,
        machine=machine,
        energy=machine.energy("energy6"),
        case=photon_case(),
        on_save=lambda _case: None,
    )
    assert dialog.m_reference.average.text() == format(sum((25.65, 25.66, 25.65)) / 3, ".12g")
    assert dialog.pgr_box.isHidden()
    assert [label.text() for label in dialog.reading_labels] == [
        "M(300V, depth=10.00 cm) [nC]",
        "M(-300V, depth=10.00 cm) [nC]",
        "M(150V, depth=10.00 cm) [nC]",
    ]
    assert dialog.post_labels[0].text() == "M(300V, depth=10.00 cm) [nC]"
    assert dialog.ptp_label.text().startswith("Ptp: ")
    assert "273.2" not in dialog.ptp_label.text()
    assert dialog.kq_label.text().startswith("kQ: 0.99172")
    assert "× 0.001 ×" not in dialog.kq_label.text()
    assert dialog.corrections_label.text().startswith("Pion: ")
    assert "Ppol: " in dialog.corrections_label.text()
    assert "M corrected: " in dialog.corrections_label.text()
    assert "[nC]" in dialog.corrections_label.text()
    assert dialog.dose_label.text().startswith("Dose at 10 [cm]: ")
    assert "<b>Dose at dmax:" in dialog.dose_label.text()
    shown = re.search(r"Dose at dmax: (\d+\.\d{4}) \[cGy\]", dialog.calculations_label.text())
    assert shown
    assert f"Dose at dmax: {float(shown.group(1)):.2f} [cGy]" in dialog.dose_label.text()
    assert re.search(r"\[cGy\]", dialog.dose_label.text())
    assert re.search(r"\d+\.\d{4} \[cGy\]", dialog.dose_label.text()) is None
    assert "tissue " not in dialog.dose_label.text()
    assert dialog.adjusted_dose_label.text().startswith("Dose at 10 [cm], adjusted: ")
    assert "<b>Dose at dmax, adjusted:" in dialog.adjusted_dose_label.text()
    details = dialog.calculations_label.text()
    assert "273.2 + 22.10 °C = 295.30" in details
    assert "kQ: 0.99172" in details
    assert "× 0.001 ×" in details
    assert "Pion: " in details
    assert "Ppol: " in details
    assert "M corrected: " in details
    assert "Dose at 10 [cm]:" in details
    assert "tissue " in details
    assert "Dose at 10 [cm], adjusted:" in details
    assert "<u>Ptp:" in details
    assert "<u>kQ:" in details
    assert "<u>Pion:" in details
    assert "<u>Ppol:" in details
    assert "<u>M corrected:" in details
    assert "<u>Dose at 10 [cm]:" in details
    assert "<u><b>Dose at dmax:" in details
    assert "<u>273.2" not in details
    assert "<u>" not in dialog.ptp_label.text()
    dialog.show()
    qapp.processEvents()
    assert dialog.calculations_box.toggle.isChecked() is False
    assert not dialog.calculations_box.body.isVisible()
    dialog.calculations_box.toggle.click()
    qapp.processEvents()
    assert dialog.calculations_box.body.isVisible()
    dialog.m_reference.cells[1].setText("")
    dialog.m_reference.cells[2].setText("")
    assert dialog.m_reference.average.text() == "25.65"
    values, error = dialog.m_reference.values()
    assert error is None
    assert values == [25.65]
    dialog.m_adjusted.cells[0].setText("")
    dialog.m_adjusted.cells[1].setText("")
    dialog.m_adjusted.cells[2].setText("")
    assert dialog.m_adjusted.average.text() == ""
    dialog._close_choice = lambda: "discard"
    dialog.close()
