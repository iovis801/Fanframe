import pytest

from fanframe import sensors


def _make_fake_hwmon(tmp_path):
    root = tmp_path / "hwmon"
    decoy = root / "hwmon0"
    decoy.mkdir(parents=True)
    (decoy / "name").write_text("nvme\n")

    cros = root / "hwmon3"
    cros.mkdir(parents=True)
    (cros / "name").write_text("cros_ec\n")
    (cros / "fan1_input").write_text("0\n")
    (cros / "fan2_input").write_text("595\n")
    (cros / "temp4_input").write_text("44850\n")
    (cros / "temp4_label").write_text("cpu@4c\n")
    (cros / "temp3_input").write_text("40850\n")
    (cros / "temp3_label").write_text("mainboard_ambient@4d\n")
    return str(root)


def test_find_cros_ec_matches_by_name(tmp_path):
    root = _make_fake_hwmon(tmp_path)
    found = sensors.find_cros_ec_hwmon(root)
    assert found is not None and found.endswith("hwmon3")


def test_read_snapshot_parses_fans_and_temps(tmp_path):
    root = _make_fake_hwmon(tmp_path)
    snapshot = sensors.read_snapshot(root)

    fans = {f.name: f.rpm for f in snapshot.fans}
    assert fans == {"fan1": 0, "fan2": 595}

    temps = {t.name: t.celsius for t in snapshot.temps}
    assert temps["temp4"] == pytest.approx(44.85)
    assert temps["temp3"] == pytest.approx(40.85)


def test_max_cpu_celsius_ignores_non_cpu(tmp_path):
    root = _make_fake_hwmon(tmp_path)
    snapshot = sensors.read_snapshot(root)
    # Only temp4 is cpu-labelled; ambient must not count.
    assert snapshot.max_cpu_celsius == pytest.approx(44.85)


def test_missing_cros_ec_raises(tmp_path):
    only = tmp_path / "hwmon" / "hwmon0"
    only.mkdir(parents=True)
    (only / "name").write_text("acpitz\n")
    with pytest.raises(FileNotFoundError):
        sensors.read_snapshot(str(tmp_path / "hwmon"))
