from fanframe import config


def test_save_then_load_roundtrip(tmp_path):
    path = str(tmp_path / "labels.json")
    config.save_labels({"fan1": "CPU", "fan2": "Intake"}, path=path)
    assert config.load_labels(path=path) == {"fan1": "CPU", "fan2": "Intake"}


def test_load_missing_file_returns_empty(tmp_path):
    assert config.load_labels(path=str(tmp_path / "nope.json")) == {}


def test_load_malformed_returns_empty(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text("not json {{{")
    assert config.load_labels(path=str(path)) == {}


def test_load_non_object_returns_empty(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text("[1, 2, 3]")
    assert config.load_labels(path=str(path)) == {}


def test_save_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "labels.json")
    config.save_labels({"fan1": "Top"}, path=path)
    assert config.load_labels(path=path) == {"fan1": "Top"}


def test_values_coerced_to_str(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text('{"fan1": 123}')
    assert config.load_labels(path=str(path)) == {"fan1": "123"}
