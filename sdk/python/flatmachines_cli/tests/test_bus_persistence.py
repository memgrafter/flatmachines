"""Tests for DataBus serialization and persistence."""

import json
import pytest

from flatmachines_cli.bus import DataBus


class TestToJson:
    def test_empty_bus(self):
        bus = DataBus()
        j = bus.to_json()
        assert json.loads(j) == {}

    def test_simple_values(self):
        bus = DataBus()
        bus.write("status", {"state": "running"})
        bus.write("tokens", {"count": 42})
        j = bus.to_json()
        data = json.loads(j)
        assert data["status"] == {"state": "running"}
        assert data["tokens"] == {"count": 42}

    def test_non_serializable_uses_str(self):
        bus = DataBus()
        bus.write("obj", set([1, 2, 3]))
        j = bus.to_json()
        data = json.loads(j)
        assert isinstance(data["obj"], str)  # set → str repr

    def test_unwritten_slots_excluded(self):
        bus = DataBus()
        bus.slot("empty")  # Create but don't write
        bus.write("full", "data")
        j = bus.to_json()
        data = json.loads(j)
        assert "empty" not in data
        assert data["full"] == "data"


class TestFromJson:
    def test_roundtrip(self):
        bus1 = DataBus()
        bus1.write("a", 1)
        bus1.write("b", "two")
        bus1.write("c", [3, 4, 5])

        j = bus1.to_json()
        bus2 = DataBus.from_json(j)

        assert bus2.read_data("a") == 1
        assert bus2.read_data("b") == "two"
        assert bus2.read_data("c") == [3, 4, 5]

    def test_empty_json(self):
        bus = DataBus.from_json("{}")
        assert len(bus) == 0
        assert bus.snapshot() == {}

    def test_restored_slots_have_version_1(self):
        bus = DataBus.from_json('{"x": 42}')
        assert bus.slot("x").version == 1

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            DataBus.from_json("not json")


class TestSaveLoad:
    def test_save_load_roundtrip(self, tmp_path):
        bus1 = DataBus()
        bus1.write("status", {"state": "done", "step": 5})
        bus1.write("content", {"text": "Hello world"})

        path = str(tmp_path / "bus.json")
        bus1.save(path)

        bus2 = DataBus.load(path)
        assert bus2.read_data("status") == {"state": "done", "step": 5}
        assert bus2.read_data("content") == {"text": "Hello world"}

    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            DataBus.load(str(tmp_path / "nonexistent.json"))

    def test_save_creates_file(self, tmp_path):
        bus = DataBus()
        bus.write("x", 1)
        path = tmp_path / "out.json"
        bus.save(str(path))
        assert path.exists()
        data = json.loads(path.read_text())
        assert data["x"] == 1

    def test_load_invalid_json_raises(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{{invalid}}")
        with pytest.raises(json.JSONDecodeError):
            DataBus.load(str(path))

    def test_overwrite_existing(self, tmp_path):
        path = str(tmp_path / "bus.json")
        bus1 = DataBus()
        bus1.write("v", 1)
        bus1.save(path)

        bus2 = DataBus()
        bus2.write("v", 2)
        bus2.save(path)

        loaded = DataBus.load(path)
        assert loaded.read_data("v") == 2


class TestNestedData:
    def test_nested_dict_roundtrip(self):
        bus = DataBus()
        bus.write("deep", {
            "level1": {
                "level2": {
                    "level3": [1, 2, {"key": "val"}]
                }
            }
        })
        j = bus.to_json()
        restored = DataBus.from_json(j)
        assert restored.read_data("deep")["level1"]["level2"]["level3"][2]["key"] == "val"

    def test_null_values(self):
        bus = DataBus()
        bus.write("none_val", None)
        j = bus.to_json()
        restored = DataBus.from_json(j)
        assert restored.read_data("none_val") is None
        assert restored.slot("none_val").version == 1

    def test_boolean_values(self):
        bus = DataBus()
        bus.write("yes", True)
        bus.write("no", False)
        j = bus.to_json()
        restored = DataBus.from_json(j)
        assert restored.read_data("yes") is True
        assert restored.read_data("no") is False
