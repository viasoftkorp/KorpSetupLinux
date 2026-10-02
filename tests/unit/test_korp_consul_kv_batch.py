import json, unittest
from _loader import load, load_module_utils

load_module_utils()
mod = load("roles/utils/library/korp_consul_kv_batch.py", "korp_consul_kv_batch")
nice = load_module_utils().to_nice_json


class FakeKV:
    """Imita python-consul: get -> (index, {'Value': bytes}|None); put -> bool."""
    def __init__(self, data=None):
        self.data = {k: v.encode() for k, v in (data or {}).items()}
        self.puts = []

    def get(self, key):
        return 1, ({"Key": key, "Value": self.data[key]} if key in self.data else None)

    def put(self, key, value, cas=None):
        self.puts.append((key, value, cas))
        if cas == 0 and key in self.data:
            return False
        self.data[key] = value.encode()
        return True


class BatchTest(unittest.TestCase):
    def run_batch(self, kv, items, default=("D",), custom=None, custom_defined=False, read=()):
        return mod.ensure_kvs(kv, items, list(default), custom, custom_defined, list(read))

    def test_new_key_created_with_cas_zero(self):
        kv = FakeKV()
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"b": 1, "a": True}, "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [("A", nice({"b": 1, "a": True}), 0)])
        self.assertTrue(res["changed"])
        self.assertEqual(res["results"], [{"key": "A", "action": "created"}])

    def test_new_key_from_string_value(self):
        kv = FakeKV()
        self.run_batch(kv, [{"key": "A", "new_kv": "nao-json", "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts[0][1], json.dumps("nao-json"))

    def test_existing_unchanged_is_not_written(self):
        current = {"Authorization": {"Secret": "S"}, "D": "x"}
        kv = FakeKV({"A": nice(current)})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "N"}, "D": "x"},
                                   "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [])
        self.assertFalse(res["changed"])

    def test_existing_merged_and_written_without_cas(self):
        kv = FakeKV({"A": '{"Authorization": {"Secret": "S"}, "D": "old"}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "N"}, "D": "new", "E": 1},
                                   "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.puts, [("A", nice({"Authorization": {"Secret": "S"}, "D": "new", "E": 1}), None)])
        self.assertEqual(res["results"], [{"key": "A", "action": "updated"}])

    def test_existing_from_json_string_new_kv(self):
        kv = FakeKV({"A": '{"D": "old"}'})
        self.run_batch(kv, [{"key": "A", "new_kv": '{"D": "new"}', "has_custom_kv_overwrite": False}])
        self.assertEqual(kv.data["A"].decode(), nice({"D": "new"}))

    def test_custom_overwrite_leaks_across_items(self):
        kv = FakeKV({"A": '{"C": "a0"}', "B": '{"C": "b0"}', "N": '{"C": "n0"}'})
        items = [
            {"key": "N", "new_kv": {"C": "n1"}, "has_custom_kv_overwrite": False},  # usa o valor inicial
            {"key": "A", "new_kv": {"C": "a1"}, "has_custom_kv_overwrite": True, "custom_kv_overwrite": ["C"]},
            {"key": "B", "new_kv": {"C": "b1"}, "has_custom_kv_overwrite": False},  # herda ["C"] de A
        ]
        res = self.run_batch(kv, items, default=(), custom=None, custom_defined=False)
        self.assertEqual(json.loads(kv.data["N"]), {"C": "n0"})
        self.assertEqual(json.loads(kv.data["A"]), {"C": "a1"})
        self.assertEqual(json.loads(kv.data["B"]), {"C": "b1"})
        self.assertEqual(res["custom_kv_overwrite"], ["C"])
        self.assertTrue(res["custom_kv_overwrite_set"])

    def test_custom_overwrite_only_updated_when_key_exists(self):
        kv = FakeKV()
        res = self.run_batch(kv, [{"key": "A", "new_kv": {}, "has_custom_kv_overwrite": True,
                                   "custom_kv_overwrite": ["C"]}], custom=["X"], custom_defined=True)
        self.assertEqual(res["custom_kv_overwrite"], ["X"])
        self.assertFalse(res["custom_kv_overwrite_set"])

    def test_initial_custom_overwrite_is_used(self):
        kv = FakeKV({"A": '{"C": "old"}'})
        self.run_batch(kv, [{"key": "A", "new_kv": {"C": "new"}, "has_custom_kv_overwrite": False}],
                       default=(), custom=["C"], custom_defined=True)
        self.assertEqual(json.loads(kv.data["A"]), {"C": "new"})

    def test_cas_conflict_is_not_changed(self):
        class Racy(FakeKV):
            def get(self, key):
                return 1, None
        kv = Racy({"A": '{"x": 1}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"x": 2}, "has_custom_kv_overwrite": False}])
        self.assertFalse(res["changed"])
        self.assertEqual(res["results"], [{"key": "A", "action": "cas_conflict"}])

    def test_read_keys_after_writes(self):
        kv = FakeKV({"B": '{"Authorization": {"Secret": "SB"}}'})
        res = self.run_batch(kv, [{"key": "A", "new_kv": {"Authorization": {"Secret": "SA"}},
                                   "has_custom_kv_overwrite": False}], read=("A", "B", "Z"))
        self.assertEqual(json.loads(res["values"]["A"])["Authorization"]["Secret"], "SA")
        self.assertEqual(json.loads(res["values"]["B"])["Authorization"]["Secret"], "SB")
        self.assertIsNone(res["values"]["Z"])

    def test_invalid_current_value_raises_with_key(self):
        kv = FakeKV({"A": "nao-json"})
        with self.assertRaises(mod.KorpKVError) as ctx:
            self.run_batch(kv, [{"key": "A", "new_kv": {}, "has_custom_kv_overwrite": False}])
        self.assertIn("A", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
