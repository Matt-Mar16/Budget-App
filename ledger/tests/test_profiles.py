import os

import profiles


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "APP_DIR", str(tmp_path))


def test_rename_profile_updates_the_display_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profile = profiles.create_profile("Original Name")

    profiles.rename_profile(profile["slug"], "New Name")

    match = next(p for p in profiles.list_profiles() if p["slug"] == profile["slug"])
    assert match["name"] == "New Name"


def test_rename_profile_ignores_a_blank_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profile = profiles.create_profile("Keep This Name")

    profiles.rename_profile(profile["slug"], "   ")

    match = next(p for p in profiles.list_profiles() if p["slug"] == profile["slug"])
    assert match["name"] == "Keep This Name"


def test_rename_profile_does_not_change_the_slug(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profile = profiles.create_profile("Original Name")

    profiles.rename_profile(profile["slug"], "Completely Different Name")

    match = next(p for p in profiles.list_profiles() if p["slug"] == profile["slug"])
    assert match["slug"] == profile["slug"]  # renaming doesn't move/recreate the .db file


def test_create_profile_puts_the_database_in_its_own_subfolder(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    profile = profiles.create_profile("Folder Test")

    expected = tmp_path / profile["slug"] / "profile.db"
    assert expected.exists()
    assert not (tmp_path / f"{profile['slug']}.db").exists()  # not left flat at the top


def test_db_path_for_matches_where_create_profile_actually_wrote_it(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profile = profiles.create_profile("Path Test")

    assert profiles.db_path_for(profile["slug"]) == str(tmp_path / profile["slug"] / "profile.db")


def test_list_profiles_migrates_a_legacy_flat_db_file_into_its_own_subfolder(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    tmp_path.mkdir(parents=True, exist_ok=True)
    from finance_core import Database
    flat_path = tmp_path / "legacy_slug.db"
    db = Database(str(flat_path))
    db.set_meta("profile_name", "Legacy Profile")
    db.close()
    assert flat_path.exists()

    result = profiles.list_profiles()

    match = next(p for p in result if p["slug"] == "legacy_slug")
    assert match["name"] == "Legacy Profile"
    assert not flat_path.exists()  # moved, not copied
    assert (tmp_path / "legacy_slug" / "profile.db").exists()


def test_list_profiles_ignores_non_profile_directories(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profiles.create_profile("Real Profile")
    (tmp_path / "inbox_backups").mkdir()  # unrelated folder that happens to sit in Profiles/

    result = profiles.list_profiles()

    assert [p["slug"] for p in result] == ["real_profile"]


def test_delete_profile_removes_the_whole_profile_folder(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    profile = profiles.create_profile("Delete Me")
    profile_dir = tmp_path / profile["slug"]
    (profile_dir / "transactions.csv").write_text("id,date\n")  # simulate a sync CSV sitting alongside

    ok = profiles.delete_profile(profile["slug"], delete_data=True)

    assert ok is True
    assert not profile_dir.exists()
