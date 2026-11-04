from PyQt5.QtGui import QFont
from pylinac.calibration import tg51

from tg51app.app_settings import save_settings
from tg51app.gui import CaseDialog, MainWindow, themed_font
from tg51app.models import CaseStore
from tests.samples import example_catalog, photon_case


def test_default_font_is_platform_plus_three_with_a_13pt_floor(qapp):
    base = QFont()
    base.setPointSize(10)
    bumped = themed_font(base, {"Font": {"family": "", "size": 0}})
    assert bumped.pointSize() == 13
    named = themed_font(base, {"Font": {"family": "Consolas", "size": 16}})
    assert named.family() == "Consolas"
    assert named.pointSize() == 16


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
    window.close()


def test_case_dialog_matches_pylinac_and_keeps_a_calculated_case(qapp, tmp_path):
    catalog = example_catalog()
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
    assert "kQ:" in dialog.results.text()

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
