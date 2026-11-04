from tg51app.models import CaseStore, deletion_block
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
