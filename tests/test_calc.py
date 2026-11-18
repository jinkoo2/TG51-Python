import pylinac
from pylinac.calibration import tg51

from tg51app.calc import (
    calculate,
    chamber_kecal,
    electron_dose_text,
    m_adjusted_corrected_value,
    m_corrected_value,
    photon_dose_text,
    photon_kq_text,
    photon_kq_value,
    pressure_kpa,
    ptp_text,
    ptp_value,
    readings_correction_text,
    temperature_celsius,
    write_pdf,
)
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


def test_ptp_text_uses_the_celsius_and_kpa_numbers():
    temp_c = 22.1
    press = tg51.mmHg2kPa(755.0)
    text = ptp_text(temp_c, press)
    assert text.startswith(f"Ptp: {tg51.p_tp(temp=temp_c, press=press):.4f}")
    assert "273.2 + 22.10 °C = 295.30" in text
    assert f"101.33 / {press:.4f} kPa" in text
    assert "×" in text


def test_kq_text_uses_the_pddx_and_chamber_coefficients():
    chamber = example_catalog().chamber("chamber")
    text = photon_kq_text(chamber, pdd=66.4, energy=6, lead_foil="none")
    direct = tg51.kq_photon_pddx(chamber="30013", pddx=66.4)
    assert text.startswith(f"kQ: {direct:.5f}")
    assert "PDD(10)x = 66.4" in text
    assert "2.141 × 0.001 × 66.4" in text
    assert text.endswith(f"= {direct:.5f}")

    converted = tg51.pddx(pdd=80.0, energy=15, lead_foil="50cm")
    high = photon_kq_text(chamber, pdd=80.0, energy=15, lead_foil="50cm")
    high_kq = tg51.kq_photon_pddx(chamber="30013", pddx=converted)
    assert high.startswith(f"kQ: {high_kq:.5f}")
    assert "0.8905 + 0.0015 × 80" in high
    assert f"PDD(10)x = {converted:.6g}" in high


def test_reading_corrections_use_the_averages_and_voltages():
    case = photon_case()
    text = readings_correction_text(
        m_reference=case.m_reference,
        m_opposite=case.m_opposite,
        m_reduced=case.m_reduced,
        voltage_reference=-300,
        voltage_reduced=-150,
        p_tp=ptp_value(22.1, tg51.mmHg2kPa(755.0)),
        p_elec=1.0,
    )
    pion = tg51.p_ion(
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=case.m_reference,
        m_reduced=case.m_reduced,
    )
    ppol = tg51.p_pol(m_reference=case.m_reference, m_opposite=case.m_opposite)
    corrected = tg51.m_corrected(
        p_ion=pion,
        p_tp=ptp_value(22.1, tg51.mmHg2kPa(755.0)),
        p_elec=1.0,
        p_pol=ppol,
        m_reference=case.m_reference,
    )
    assert f"Pion: {pion:.4f}" in text
    assert "-300 / -150 = 2" in text
    assert f"Ppol: {ppol:.4f}" in text
    assert f"M corrected: {corrected:.3f} [nC]" in text
    assert "Pion" in text and "Ptp" in text and "P_elec" in text and "Ppol" in text


def test_photon_dose_text_matches_pylinac():
    case = photon_case()
    outcome = _run(case, "energy6")
    assert outcome.errors == []
    corrected = m_corrected_value(
        m_reference=case.m_reference,
        m_opposite=case.m_opposite,
        m_reduced=case.m_reduced,
        voltage_reference=-300,
        voltage_reduced=-150,
        p_tp=ptp_value(22.1, tg51.mmHg2kPa(755.0)),
        p_elec=1.0,
    )
    kq = photon_kq_value(example_catalog().chamber("chamber"), pdd=66.4, energy=6, lead_foil="none")
    assert abs(corrected - outcome.result["m_corrected"]) < 1e-9
    assert abs(kq - outcome.result["kq"]) < 1e-9
    text = photon_dose_text(
        tissue=1.0,
        m_corrected=corrected,
        kq=kq,
        n_dw=5.443,
        mu=200,
        clinical_pdd10=66.5,
    )
    assert text.startswith(f"Dose at 10 [cm]: {outcome.result['dose_mu_10'] * 200:.4f} [cGy]")
    assert f"Dose at dmax: {outcome.result['dose_mu_dmax'] * 200:.4f} [cGy]" in text
    assert "66.5 / 100 = 0.665" in text


def test_adjusted_dose_text_matches_pylinac():
    case = photon_case()
    outcome = _run(case, "energy6")
    assert outcome.errors == []
    corrected = m_adjusted_corrected_value(
        m_reference=case.m_reference,
        m_opposite=case.m_opposite,
        m_reduced=case.m_reduced,
        m_adjusted=case.m_reference_adjusted,
        voltage_reference=-300,
        voltage_reduced=-150,
        p_tp=ptp_value(22.1, tg51.mmHg2kPa(755.0)),
        p_elec=1.0,
    )
    text = photon_dose_text(
        tissue=1.0,
        m_corrected=corrected,
        kq=outcome.result["kq"],
        n_dw=5.443,
        mu=200,
        clinical_pdd10=66.5,
        adjusted=True,
    )
    assert text.startswith(
        f"Dose at 10 [cm], adjusted: {outcome.result['dose_mu_10_adjusted'] * 200:.4f} [cGy]"
    )
    assert f"Dose at dmax, adjusted: {outcome.result['dose_mu_dmax_adjusted'] * 200:.4f} [cGy]" in text


def test_electron_dose_text_matches_pylinac():
    outcome = _run(electron_case(), "energy9")
    assert outcome.errors == []
    text = electron_dose_text(
        tissue=1.0,
        m_corrected=outcome.result["m_corrected"],
        kq=outcome.result["kq"],
        n_dw=5.443,
        mu=200,
        clinical_pdd=98.5,
        pgr=outcome.result["pq_gr"],
    )
    assert text.startswith(f"Dose at dref: {outcome.result['dose_mu_dref'] * 200:.4f} [cGy]")
    assert f"Dose at dmax: {outcome.result['dose_mu_dmax'] * 200:.4f} [cGy]" in text


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


def test_kecal_is_a_chamber_property():
    chamber = example_catalog().chamber("chamber")
    assert chamber.k_ecal is None
    assert chamber_kecal(chamber) == 0.901
    chamber.k_ecal = 0.91
    assert chamber_kecal(chamber) == 0.91
    again = Chamber.from_dict(chamber.to_dict())
    assert again.k_ecal == 0.91


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


def test_pdd_entered_as_a_fraction_is_rejected():
    case = photon_case()
    case.measured_pdd10 = 0.664
    case.clinical_pdd10 = 0.664
    outcome = _run(case, "energy6")
    assert outcome.result is None
    assert any("percent" in error for error in outcome.errors)


def test_publish_pdf(tmp_path):
    outcome = _run(photon_case(), "energy6")
    path = tmp_path / "tg51.pdf"
    write_pdf(outcome.calculator, path, outcome.warnings)
    data = path.read_bytes()
    assert data.startswith(b"%PDF-")
