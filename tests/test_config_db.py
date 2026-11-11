from __future__ import annotations

import os
import sqlite3

import pytest

from pamela import db
from pamela.config import (
    ActivityType,
    ConfigError,
    ConfigStore,
    Settings,
    default_config_text,
    ensure_config_file,
    parse_config,
)
from pamela.tracking import estimate_kcal, scale_macros


def test_default_config_is_valid():
    cfg = parse_config(default_config_text())
    assert cfg.targets.kcal > 0
    assert cfg.meals.names[0] == "Breakfast"
    assert cfg.targets.steps == 8000
    assert cfg.activity_types == []  # they live in the database now


def test_ensure_config_creates_file_once(tmp_path):
    path = tmp_path / "info" / "config.toml"
    ensure_config_file(path)
    assert path.read_text() == default_config_text()
    path.write_text("[targets]\nkcal = 1\n")
    ensure_config_file(path)  # must not overwrite user edits
    assert "kcal = 1" in path.read_text()


def test_config_store_reloads_on_change(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[targets]\nkcal = 1800\n")
    store = ConfigStore(path)
    assert store.get().targets.kcal == 1800
    path.write_text("[targets]\nkcal = 2000.5\n")
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    assert store.get().targets.kcal == 2000.5


@pytest.mark.parametrize(
    ("text", "msg"),
    [
        ("[targets\n", "invalid TOML"),
        ("[targets]\nkcal = -5\n", "targets.kcal"),
        ("[meals]\nnames = []\n", "at least one meal"),
        ("[meals]\nnames = ['A', 'A']\n", "unique"),
        ("[[activity_types]]\nname = 'Run'\nmet = 0\n", "activity_types.0.met"),
    ],
)
def test_invalid_config_reports_location(text, msg):
    with pytest.raises(ConfigError, match=msg):
        parse_config(text)


def test_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("PAMELA_LOCAL_DIR", str(tmp_path / "x"))
    monkeypatch.setenv("PAMELA_INFO_DIR", str(tmp_path / "y"))
    s = Settings.from_env()
    assert s.db_path == tmp_path / "x" / "pamela.sqlite3"
    assert s.config_path == tmp_path / "y" / "config.toml"


def test_migrate_is_idempotent(tmp_path):
    path = tmp_path / "db.sqlite3"
    assert db.migrate(path) == len(db.MIGRATIONS)
    assert db.migrate(path) == len(db.MIGRATIONS)
    with db.session(path) as conn:
        tables = {
            r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert {
        "foods",
        "food_entries",
        "activities",
        "saved_meals",
        "saved_meal_items",
        "activity_types",
        "day_metrics",
    } <= tables


def test_import_config_activity_types_once(tmp_path):
    path = tmp_path / "db.sqlite3"
    db.migrate(path)
    legacy = [ActivityType(name="running", met=11, distance=True), ActivityType(name="Pogo", met=6)]
    with db.session(path) as conn:
        assert db.import_config_activity_types(conn, legacy) is True
        # a second run (e.g. after the user deleted a type in the app) changes nothing
        conn.execute("DELETE FROM activity_types WHERE name = 'Pogo'")
        assert db.import_config_activity_types(conn, legacy) is False
        rows = {r["name"]: r for r in conn.execute("SELECT * FROM activity_types")}
    assert rows["Running"]["met"] == 11  # the config's value wins, matched ignoring case
    assert "Pogo" not in rows


def test_session_rolls_back_on_error(tmp_path):
    path = tmp_path / "db.sqlite3"
    db.migrate(path)
    with pytest.raises(sqlite3.IntegrityError), db.session(path) as conn:
        conn.execute("INSERT INTO foods (name) VALUES ('kept?')")
        conn.execute("INSERT INTO foods (name, basis_qty) VALUES ('bad', 0)")  # CHECK fails
    with db.session(path) as conn:
        assert conn.execute("SELECT COUNT(*) AS n FROM foods").fetchone()["n"] == 0


def test_target_on():
    from pamela.tracking import target_on

    periods = [(None, 1), ("2026-01-10", 2), ("2026-02-01", 3)]
    assert [target_on(periods, d) for d in ("2025-12-31", "2026-01-10", "2026-03-01")] == [1, 2, 3]
    assert target_on([], "2026-01-01") is None


def test_scale_and_estimate():
    food = {"basis_qty": 100, "kcal": 200, "protein_g": 10, "carbs_g": 20, "fat_g": 5, "fiber_g": 2}
    assert scale_macros(food, 50) == {
        "kcal": 100,
        "protein_g": 5,
        "carbs_g": 10,
        "fat_g": 2.5,
        "fiber_g": 1,
    }
    assert estimate_kcal(met=8, weight_kg=75, duration_min=30) == pytest.approx(300)


def test_food_rebuild_keeps_ids_links_and_tags(tmp_path):
    """Migration 6 rebuilds foods: entries and saved meals must keep pointing at them."""
    path = tmp_path / "old.sqlite3"
    conn = db.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    for i, script in enumerate(db.MIGRATIONS[:5], start=1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")
    conn.execute("INSERT INTO foods (id, name, kcal, vegetarian) VALUES (7, 'Egg', 72, 1)")
    conn.execute("INSERT INTO foods (id, name, kcal, vegan) VALUES (8, 'Rice', 130, 1)")
    conn.execute(
        "INSERT INTO food_entries (day, meal, food_id, name, kcal) "
        "VALUES ('2026-01-01', 'L', 7, 'Egg', 72)"
    )
    conn.execute("INSERT INTO saved_meals (id, name) VALUES (1, 'm')")
    conn.execute("INSERT INTO saved_meal_items (saved_meal_id, food_id, quantity) VALUES (1, 8, 1)")
    conn.commit()
    conn.close()

    assert db.migrate(path) == len(db.MIGRATIONS)
    conn = db.connect(path)
    assert conn.execute("SELECT food_id FROM food_entries").fetchone()["food_id"] == 7
    assert conn.execute("SELECT food_id FROM saved_meal_items").fetchone()["food_id"] == 8
    egg, rice = conn.execute("SELECT * FROM foods ORDER BY id").fetchall()
    assert (egg["pescatarian"], egg["ovolactovegetarian"], egg["vegan"]) == (1, 1, 0)
    assert (rice["pescatarian"], rice["vegetarian"], rice["vegan"]) == (1, 1, 1)
    conn.execute("INSERT INTO foods (name) VALUES ('Unknown')")
    assert conn.execute("SELECT kcal FROM foods WHERE name = 'Unknown'").fetchone()["kcal"] is None
    # foreign keys still work on the rebuilt table
    conn.execute("DELETE FROM foods WHERE id = 8")
    assert conn.execute("SELECT COUNT(*) AS n FROM saved_meal_items").fetchone()["n"] == 0
    conn.close()


def test_unit_becomes_whole(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = db.connect(path)
    for i, script in enumerate(db.MIGRATIONS[:6], start=1):
        conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {i};\nCOMMIT;")
    conn.execute("INSERT INTO foods (id, name, unit, basis_qty) VALUES (1, 'Apple', 'unit', 1)")
    conn.execute(
        "INSERT INTO food_entries (day, meal, food_id, name, quantity, unit) "
        "VALUES ('2026-01-01', 'L', 1, 'Apple', 2, 'unit')"
    )
    conn.commit()
    conn.close()
    db.migrate(path)
    conn = db.connect(path)
    f = conn.execute("SELECT unit, food_group FROM foods").fetchone()
    assert (f["unit"], f["food_group"]) == ("whole", "")
    assert conn.execute("SELECT unit FROM food_entries").fetchone()["unit"] == "whole"
    conn.close()
