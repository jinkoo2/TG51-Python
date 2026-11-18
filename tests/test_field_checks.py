from tg51app.app_settings import valid_ranges
from tg51app.field_checks import history_messages, outside_range, range_message
from tests.samples import photon_case


def test_valid_ranges_merge_and_null_removes_a_field():
    ranges = valid_ranges({"ValidRanges": {"measured_pdd10": {"min": 60, "max": 70}, "p_elec": None}})
    assert ranges["measured_pdd10"] == {"min": 60.0, "max": 70.0}
    assert ranges["temperature_c"]["min"] == 17.0
    assert "p_elec" not in ranges


def test_pdd_fraction_is_outside_the_percent_range():
    bounds = valid_ranges({})["measured_pdd10"]
    assert outside_range(0.664, bounds)
    assert range_message("Measured PDD(10)", 0.664, bounds, "%") == (
        "Measured PDD(10) 0.664 [%] is outside 62.7–89 [%]."
    )
    assert not outside_range(66.4, bounds)


def test_history_warns_past_five_percent_and_keeps_the_boundary():
    previous = photon_case()
    previous.status = "calculated"
    previous.m_reference = [10.0, 10.0, 10.0]
    current = photon_case()
    current.id = "later"
    current.m_reference = [10.5, 10.5, 10.5]
    assert history_messages(current, [previous], 5) == []
    current.m_reference = [10.6, 10.6, 10.6]
    messages = history_messages(current, [previous], 5)
    assert any(key == "m_reference" and "M at Vref" in text for key, text in messages)
    assert history_messages(current, [previous], 0) == []
