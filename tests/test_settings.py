from pathlib import Path

from tg51app.app_settings import default_settings, font_settings, load_settings, save_settings
from tg51app.models import Catalog


def test_project_sample_file_loads():
    sample = Path(__file__).resolve().parents[1] / "settings.sample.json"
    data = load_settings(sample)
    assert data["Users"] == []
    assert data["IonChambers"] == []
    assert data["Machines"] == []
    assert font_settings(data) == {"family": "", "size": 0}


def test_jsonc_comments_and_urls(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        """
        {
          // clinic name
          "Institution": "http://example.com",
          "Font": { "family": "Consolas", "size": 14 },
          "Users": [ /* none */ ]
        }
        """,
        encoding="utf-8",
    )
    data = load_settings(path)
    assert data["Institution"] == "http://example.com"
    assert font_settings(data) == {"family": "Consolas", "size": 14}
    assert data["Users"] == []


def test_missing_file_uses_sample_then_defaults(tmp_path):
    sample = tmp_path / "settings.sample.json"
    sample.write_text('{ "Institution": "From sample", "Users": [] }\n', encoding="utf-8")
    data = load_settings(tmp_path / "settings.json")
    assert data["Institution"] == "From sample"

    defaults = load_settings(tmp_path / "empty" / "settings.json")
    assert defaults["Users"] == []
    assert defaults["IonChambers"] == []
    assert defaults["Machines"] == []
    assert font_settings(defaults) == {"family": "", "size": 0}
    assert defaults == default_settings()


def test_settings_round_trip(tmp_path):
    catalog = Catalog.from_settings(default_settings())
    catalog.institution = "UH"
    catalog.users = []
    from tg51app.models import User

    catalog.users.append(User(id="user1", name="Ada", email="ada@example.com"))
    path = tmp_path / "settings.json"
    save_settings(catalog.to_settings(), path)
    loaded = Catalog.from_settings(load_settings(path))
    assert loaded.institution == "UH"
    assert loaded.users[0].name == "Ada"
    assert loaded.users[0].email == "ada@example.com"
    assert font_settings(load_settings(path))["size"] == 0
