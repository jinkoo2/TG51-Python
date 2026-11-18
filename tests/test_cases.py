from tg51app.models import (
    CHAMBER_PARALLEL_PLATE,
    Calibration,
    CalibrationCase,
    CaseStore,
    Catalog,
    Chamber,
    Electrometer,
    deletion_block,
    latest_calibration,
)
from tests.samples import example_catalog, photon_case


def test_case_round_trip(tmp_path):
    store = CaseStore(tmp_path)
    store.save(photon_case())
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0].id == "photoncase"
    assert loaded[0].m_reference == [25.65, 25.66, 25.65]
    assert loaded[0].m_reference_adjusted == [25.44, 25.44, 25.43]
    assert loaded[0].voltage_reference == -300
    assert loaded[0].energy_id == "energy6"


def test_new_case_copies_the_last_saved_setup_for_the_machine(tmp_path):
    import os

    store = CaseStore(tmp_path)
    first = photon_case()
    first.temp_value = 20.0
    store.save(first)
    later = photon_case()
    later.id = "latercase"
    later.energy_id = "energy9"
    later.measurement_date = "2026-04-03"
    later.user_id = "user"
    later.temp_value = 22.5
    later.temp_unit = "C"
    later.press_value = 752.0
    later.press_unit = "mmHg"
    later.m_reference = [1.0]
    store.save(later)
    os.utime(store.path_for(first), (1_000_000_000, 1_000_000_000))
    os.utime(store.path_for(later), (1_700_000_000, 1_700_000_000))
    latest = store.latest_for_machine("machine")
    assert latest is not None
    assert latest.id == "latercase"
    fresh = CalibrationCase.new("machine", "energy6")
    fresh.copy_shared_setup(latest)
    assert fresh.measurement_date == "2026-04-03"
    assert fresh.user_id == "user"
    assert fresh.temp_value == 22.5
    assert fresh.press_value == 752.0
    assert fresh.chamber_id == "chamber"
    assert fresh.n_dw is None
    assert fresh.p_elec is None
    assert fresh.m_reference == []
    assert fresh.energy_id == "energy6"


def test_delete_is_refused_while_a_case_points_at_the_record(tmp_path):
    store = CaseStore(tmp_path)
    store.save(photon_case())
    catalog = example_catalog()
    for kind, record_id in (
        ("user", "user"),
        ("chamber", "chamber"),
        ("machine", "machine"),
        ("energy", "energy6"),
    ):
        message = deletion_block(store, catalog, kind, record_id)
        assert message is not None
        assert "2026-04-01" in message
        assert "TrueBeam1" in message
        assert "6 MV" in message
    assert deletion_block(store, catalog, "user", "nobody") is None

    store.delete(photon_case())
    assert store.load_all() == []
    assert deletion_block(store, catalog, "chamber", "chamber") is None


def test_latest_calibration_wins_and_old_records_still_load():
    chamber = Chamber.from_dict(
        {
            "id": "c",
            "name": "Farmer",
            "n_dw": 5.41,
            "calibration_lab": "ADCL",
            "calibration_date": "11/1/2024",
        }
    )
    assert chamber.n_dw == 5.41
    assert len(chamber.calibrations) == 1
    again = Chamber(
        id="c",
        name="Farmer",
        calibrations=[
            Calibration(date="2/12/2019", lab="ADCL", factor=5.45),
            Calibration(date="11/1/2024", lab="ADCL", factor=5.41),
        ],
    )
    assert again.n_dw == 5.41
    assert again.calibration_date == "11/1/2024"
    stored = Chamber.from_dict(again.to_dict())
    assert [item.factor for item in stored.calibrations] == [5.45, 5.41]
    assert latest_calibration(stored.calibrations).factor == 5.41
    meter = Electrometer.from_dict({"id": "e", "name": "MAX", "p_elec": 0.999, "calibration_date": "1/1/2022"})
    assert meter.p_elec == 0.999
    updated = Electrometer(
        id="e",
        name="MAX",
        calibrations=[
            Calibration(date="1/1/2022", factor=0.999),
            Calibration(date="2024-06-01", lab="ADCL", factor=1.0),
        ],
    )
    assert updated.p_elec == 1.0
    assert updated.calibration_lab == "ADCL"


def test_parallel_plate_drops_rcav_and_cylinder_keeps_it():
    plate = Chamber.from_dict(
        {"id": "pp", "name": "Markus", "chamber_type": "parallel plate", "rcav_cm": 0.2}
    )
    assert plate.chamber_type == CHAMBER_PARALLEL_PLATE
    assert plate.rcav_cm is None
    cylinder = Chamber.from_dict({"id": "cy", "name": "Farmer", "rcav_cm": 0.305})
    assert cylinder.chamber_type == "cylinder"
    assert cylinder.rcav_cm == 0.305
    again = Chamber.from_dict(cylinder.to_dict())
    assert again.rcav_cm == 0.305


def test_legacy_electrometer_text_becomes_one_catalog_record():
    catalog = Catalog.from_settings(
        {
            "IonChambers": [
                {"id": "a", "name": "A", "electrometer": "Keithley", "p_elec": 1.0},
                {"id": "b", "name": "B", "electrometer": "Keithley"},
            ]
        }
    )
    assert len(catalog.electrometers) == 1
    assert catalog.electrometers[0].name == "Keithley"
    assert catalog.electrometers[0].p_elec == 1.0
    shared = catalog.electrometers[0].id
    assert catalog.chamber("a").electrometer_id == shared
    assert catalog.chamber("b").electrometer_id == shared
    again = Catalog.from_settings(catalog.to_settings())
    assert [item.id for item in again.electrometers] == [shared]
    assert again.chamber("a").electrometer_id == shared


def test_delete_electrometer_is_refused_while_a_chamber_or_case_uses_it(tmp_path):
    catalog = example_catalog()
    catalog.electrometers = [Electrometer(id="meter", name="Keithley")]
    store = CaseStore(tmp_path)
    message = deletion_block(store, catalog, "electrometer", "meter")
    assert message is not None
    assert "Farmer" in message
    catalog.chambers[0].electrometer = ""
    catalog.chambers[0].electrometer_id = ""
    assert deletion_block(store, catalog, "electrometer", "meter") is None
    store.save(photon_case())
    message = deletion_block(store, catalog, "electrometer", "meter")
    assert "2026-04-01" in message
    assert "TrueBeam1" in message
