"""Shared TG-51 inputs. The photon numbers are pylinac's worked example."""

from tg51app.models import CalibrationCase, Catalog, Chamber, Energy, Machine, User


def example_catalog() -> Catalog:
    user = User(id="user", name="Ada Physicist", email="ada@example.com")
    chamber = Chamber(
        id="chamber",
        name="Farmer",
        serial="123",
        model="30013",
        n_dw=5.443,
        p_elec=1.0,
        electrometer="Keithley",
    )
    machine = Machine(
        id="machine",
        name="TrueBeam1",
        manufacturer="Varian",
        model="TrueBeam",
        serial="TB",
        energies=[
            Energy(id="energy6", modality="photon", nominal=6, fff=False),
            Energy(id="energy9", modality="electron", nominal=9, fff=False),
        ],
    )
    return Catalog(institution="UH", users=[user], chambers=[chamber], machines=[machine])


def photon_case() -> CalibrationCase:
    return CalibrationCase(
        id="photoncase",
        machine_id="machine",
        energy_id="energy6",
        user_id="user",
        measurement_date="2026-04-01",
        temp_value=22.1,
        temp_unit="C",
        press_value=755.0,
        press_unit="mmHg",
        chamber_id="chamber",
        n_dw=5.443,
        p_elec=1.0,
        electrometer="Keithley",
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=[25.65, 25.66, 25.65],
        m_opposite=[25.64, 25.65, 25.65],
        m_reduced=[25.64, 25.63, 25.63],
        m_reference_adjusted=[25.44, 25.44, 25.43],
        mu=200,
        tissue_correction=1.0,
        measured_pdd10=66.4,
        clinical_pdd10=66.5,
        lead_foil="none",
    )


def electron_case(method: str = "legacy") -> CalibrationCase:
    return CalibrationCase(
        id="electroncase",
        machine_id="machine",
        energy_id="energy9",
        user_id="user",
        measurement_date="2026-04-02",
        temp_value=22.0,
        temp_unit="C",
        press_value=760.0,
        press_unit="mmHg",
        chamber_id="chamber",
        n_dw=5.443,
        p_elec=1.0,
        electrometer="Keithley",
        voltage_reference=-300,
        voltage_reduced=-150,
        m_reference=[25.65, 25.66, 25.65],
        m_opposite=[25.64, 25.65, 25.64],
        m_reduced=[25.63, 25.62, 25.63],
        mu=200,
        tissue_correction=1.0,
        electron_method=method,
        clinical_pdd=98.5,
        cone="10x10",
        i_50=3.52,
        k_ecal=0.901,
        m_gradient=[25.40, 25.41, 25.40],
    )
