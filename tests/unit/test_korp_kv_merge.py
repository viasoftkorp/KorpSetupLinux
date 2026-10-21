import copy, random, unittest
from _loader import load_module_utils


# Cópia literal de roles/utils/library/consul_kv.py (antes da refatoração)
def _orig_replace_key(keys_sequence, dictionary, new_val):
    current_key = keys_sequence[0]
    if len(keys_sequence) == 1:
        dictionary[current_key] = new_val
    else:
        dictionary[current_key] = _orig_replace_key(keys_sequence[1:], dictionary[current_key], new_val)
    return dictionary


def _orig_access_value(keys_sequence, dictionary):
    if not keys_sequence:
        return dictionary
    current_key = keys_sequence[0]
    if current_key in dictionary:
        return _orig_access_value(keys_sequence[1:], dictionary[current_key])
    else:
        return None


def _orig_merge(current_kv, new_kv, keys_to_overwrite):
    merged_kv = new_kv.copy()
    merged_kv.update(current_kv)
    for key_path in keys_to_overwrite:
        keys_sequence = key_path.split(".")
        new_val = _orig_access_value(keys_sequence, new_kv)
        if new_val:
            merged_kv = _orig_replace_key(keys_sequence, merged_kv, new_val)
    return merged_kv


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.m = load_module_utils()

    def test_readme_table(self):
        current = {"a": {"b": "Valor antigo1", "d": "Valor antigo2"}}
        new = {"a": {"b": {"c": "Valor novo"}}}
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a.b"]),
                         {"a": {"b": {"c": "Valor novo"}, "d": "Valor antigo2"}})
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a"]),
                         {"a": {"b": {"c": "Valor novo"}}})
        # Nota: A tabela original está incorreta nesta linha - o original também lança TypeError aqui
        with self.assertRaises(TypeError):
            self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["a.b.c"])
        self.assertEqual(self.m.merge_kv(copy.deepcopy(current), copy.deepcopy(new), ["b"]), current)

    def test_falsy_new_values_never_overwrite(self):
        for falsy in ("", 0, False, None, [], {}):
            self.assertEqual(self.m.merge_kv({"k": "old"}, {"k": falsy}, ["k"]), {"k": "old"})

    def test_random_equivalence_with_original(self):
        rnd = random.Random(7)
        keys = ["A", "B", "C"]

        def tree(depth):
            if depth == 0 or rnd.random() < 0.3:
                return rnd.choice(["x", "y", "", 0, 1, True, False, None, [1], {}])
            return {k: tree(depth - 1) for k in rnd.sample(keys, rnd.randint(1, 3))}

        for _ in range(3000):
            cur, new = tree(3), tree(3)
            if not isinstance(cur, dict) or not isinstance(new, dict):
                continue
            paths = [".".join(rnd.sample(keys, rnd.randint(1, 2))) for _ in range(rnd.randint(0, 3))]
            try:
                expected = _orig_merge(copy.deepcopy(cur), copy.deepcopy(new), paths)
            except Exception as exc:  # original também falha
                with self.assertRaises(type(exc)):
                    self.m.merge_kv(copy.deepcopy(cur), copy.deepcopy(new), paths)
                continue
            self.assertEqual(self.m.merge_kv(copy.deepcopy(cur), copy.deepcopy(new), paths), expected)

    def test_to_nice_json_matches_ansible_filter(self):
        from ansible.plugins.filter.core import to_nice_json as ansible_to_nice_json
        value = {"b": [1, 2, {"z": None}], "a": "çé", "c": True, "d": 1.5}
        self.assertEqual(self.m.to_nice_json(value), ansible_to_nice_json(value, indent=2))


if __name__ == "__main__":
    unittest.main()
