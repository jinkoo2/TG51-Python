import pylinac
from pylinac.calibration import tg51

from tg51app.calc import calculate, pressure_kpa, temperature_celsius, write_pdf
from tg51app.models import Chamber
from tests.samples import electron_case, example_catalog, photon_case


def _run(case, energy_id):
    catalog = example_catalog()
    return calculate(
        case,
        institution=catalog.institution,
        physicist=catalog.user(case.user_id).name,
        unit=catalog.machine(case.machine_id).name,
        energy=catalog.machine(case.machine_id).energy(energy_id),
        chamber=catalog.chamber(case.chamber_id),
    )


def test_temperature_and_pressure_helpers_match_pylinac():
    assert temperature_celsius(22, "C") == 22
    assert pressure_kpa(760, "mmHg") == tg51.mmHg2kPa(760)
    assert temperature_celsius(72, "F") == tg51.fahrenheit2celsius(72)
    assert pressure_kpa(1013.25, "mbar") == tg51.mbar2kPa(1013.25)


def test_photon_matches_pylinac_class():
    outcome = _run(photon_case(), "energy6")
    assert outcome.errors == []
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
    assert outcome.result["pddx"] == direct.pddx
    assert outcome.result["kq"] == direct.kq
    assert outcome.result["dose_mu_10"] == direct.dose_mu_10
    assert outcome.result["dose_mu_dmax"] == direct.dose_mu_dmax
    assert outcome.result["dose_mu_dmax_adjusted"] == direct.dose_mu_dmax_adjusted
    assert outcome.pylinac_version == pylinac.__version__


def test_legacy_and_modern_electrons_match_pylinac():
    legacy = _run(electron_case("legacy"), "energy9")
    assert legacy.errors == []
    direct_legacy = tg51.TG51ElectronLegacy(
        institution="UH",
        physicist="Ada Physicist",
        unit="TrueBeam1",
        measurement_date="2026-04-02",
        energy=9,
        temp=22.0,
        press=tg51.mmHg2kPa(760.0),
        chamber="30013",
        k_ecal=0.901,
        n_dw=5.443,
        electrometer="Keithley",
        p_elec=1.0,
        clinical_pdd=98.5,
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=(25.65, 25.66, 25.65),
        m_opposite=(25.64, 25.65, 25.64),
        m_reduced=(25.63, 25.62, 25.63),
        m_gradient=(25.40, 25.41, 25.40),
        cone="10x10",
        mu=200,
        i_50=3.52,
        tissue_correction=1.0,
    )
    assert legacy.result["kq"] == direct_legacy.kq
    assert legacy.result["dose_mu_dref"] == direct_legacy.dose_mu_dref
    assert legacy.result["dose_mu_dmax"] == direct_legacy.dose_mu_dmax
    assert legacy.result["pq_gr"] == direct_legacy.pq_gr

    modern = _run(electron_case("modern"), "energy9")
    assert modern.errors == []
    direct_modern = tg51.TG51ElectronModern(
        institution="UH",
        physicist="Ada Physicist",
        unit="TrueBeam1",
        measurement_date="2026-04-02",
        energy=9,
        temp=22.0,
        press=tg51.mmHg2kPa(760.0),
        chamber="30013",
        n_dw=5.443,
        electrometer="Keithley",
        p_elec=1.0,
        clinical_pdd=98.5,
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=(25.65, 25.66, 25.65),
        m_opposite=(25.64, 25.65, 25.64),
        m_reduced=(25.63, 25.62, 25.63),
        cone="10x10",
        mu=200,
        i_50=3.52,
        tissue_correction=1.0,
    )
    assert modern.result["kq"] == direct_modern.kq
    assert modern.result["dose_mu_dref"] == direct_modern.dose_mu_dref
    assert modern.result["dose_mu_dmax"] == direct_modern.dose_mu_dmax


def test_calculate_blocks_incomplete_input():
    case = photon_case()
    case.m_reference = []
    case.voltage_reference = 300
    case.voltage_reduced = 400
    outcome = _run(case, "energy6")
    text = " ".join(outcome.errors)
    assert "reference reading" in text
    assert "magnitude" in text

    custom = example_catalog().chamber("chamber")
    custom = Chamber(id="custom", name="Custom", model="custom")
    case = photon_case()
    case.chamber_id = "custom"
    catalog = example_catalog()
    outcome = calculate(
        case,
        institution="",
        physicist="",
        unit="TrueBeam1",
        energy=catalog.machine("machine").energy("energy6"),
        chamber=custom,
    )
    assert any("photon coefficients" in error for error in outcome.errors)


def test_publish_pdf(tmp_path):
    outcome = _run(photon_case(), "energy6")
    path = tmp_path / "tg51.pdf"
    write_pdf(outcome.calculator, path, outcome.warnings)
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
