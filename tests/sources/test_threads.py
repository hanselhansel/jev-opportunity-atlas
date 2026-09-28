import numpy as np
import pytest

from atlas.sources.threads import kind_code, resolve_roots, resolve_roots_np, thread_type_of

B = 9_000_000_000


def test_resolve_roots_and_depth():
    # story B+1 <- c2 <- c3 ; poll B+10 <- c11 ; c20's parent B+99 is unknown
    parent = {B + 2: B + 1, B + 3: B + 2, B + 11: B + 10, B + 20: B + 99}
    kind = {
        B + 1: "story",
        B + 2: "comment",
        B + 3: "comment",
        B + 10: "poll",
        B + 11: "comment",
        B + 20: "comment",
    }
    roots, missing = resolve_roots(parent, kind)
    assert roots[B + 3] == (B + 1, 2)
    assert roots[B + 2] == (B + 1, 1)
    assert roots[B + 11] == (B + 10, 1)
    assert B + 20 not in roots and missing == {B + 99}


def test_cycles_do_not_hang():
    roots, missing = resolve_roots(
        {B + 5: B + 6, B + 6: B + 5}, {B + 5: "comment", B + 6: "comment"}
    )
    assert roots == {} and missing == set()


def test_non_root_ancestors_leave_chain_unresolved():
    # pollopt is neither a comment nor a root: chain stops, nothing missing
    parent = {B + 30: B + 31, B + 31: B + 32}
    kind = {B + 30: "comment", B + 31: "pollopt", B + 32: "story"}
    roots, missing = resolve_roots(parent, kind)
    assert roots == {} and missing == set()
    # a comment with no parent entry is unresolved but not missing
    roots, missing = resolve_roots({}, {B + 40: "comment"})
    assert roots == {} and missing == set()


def test_thread_type_rules():
    assert thread_type_of("story", "Ask HN: How do you back up?") == "ask_hn"
    assert thread_type_of("story", "Show HN: A tiny DB") == "show_hn"
    assert thread_type_of("story", "Launch HN: Acme (YC S25)") == "launch_hn"
    assert thread_type_of("story", "Tell HN: I quit") == "tell_hn"
    assert thread_type_of("story", "Rust 2.0 released") == "story"
    assert thread_type_of("poll", "Which editor?") == "poll"
    assert thread_type_of("job", "Acme is hiring") == "job"
    assert thread_type_of(None, None) == "unknown"


def _forest(seed=7, n=5000):
    rng = np.random.default_rng(seed)
    ids = np.arange(B, B + n, dtype=np.int64)
    types = np.full(n, "comment", dtype=object)
    n_roots = n // 25
    types[:n_roots] = rng.choice(["story", "poll", "job"], size=n_roots)
    types[n_roots : n_roots + 40] = "pollopt"
    parent = np.full(n, -1, dtype=np.int64)
    for i in range(n):
        if types[i] != "comment":
            continue
        r = rng.random()
        if r < 0.75:
            j = rng.integers(0, i) if i else -1
            if j >= 0:
                parent[i] = ids[j]
        elif r < 0.9:
            parent[i] = B + n + int(rng.integers(0, 500))  # absent id
    # a few 2- and 3-cycles among comments
    tail = n - 30
    for k in range(0, 30, 2):
        a, b = tail + k, tail + k + 1
        parent[a], parent[b] = ids[b], ids[a]
    for k in range(0, 24, 3):
        a, b, c = tail - 30 + k, tail - 29 + k, tail - 28 + k
        parent[a], parent[b], parent[c] = ids[b], ids[c], ids[a]
    return ids, parent, types


def test_numpy_matches_reference_on_random_forest():
    ids, parent_arr, types = _forest()
    kind_arr = np.array([kind_code(t) for t in types], dtype=np.int8)
    parent_d = {int(ids[i]): int(parent_arr[i]) for i in range(len(ids)) if parent_arr[i] != -1}
    kind_d = {int(ids[i]): str(types[i]) for i in range(len(ids))}
    ref_roots, ref_missing = resolve_roots(parent_d, kind_d)

    root_id, depth, missing = resolve_roots_np(ids, parent_arr, kind_arr)
    pos = {int(i): k for k, i in enumerate(ids)}
    assert set(int(x) for x in missing) == ref_missing
    for i, iid in enumerate(ids):
        iid = int(iid)
        if types[i] != "comment":
            assert root_id[i] == -1 and depth[i] == -1
            continue
        if iid in ref_roots:
            assert root_id[i] == ref_roots[iid][0] and depth[i] == ref_roots[iid][1]
        else:
            assert root_id[i] == -1 and depth[i] == -1
        _ = pos


def test_kind_code_mapping():
    assert kind_code("comment") == 1
    assert kind_code("story") == kind_code("poll") == kind_code("job") == 2
    assert kind_code("pollopt") == kind_code(None) == 0


def test_resolve_roots_np_rejects_unsorted_ids():
    ids = np.array([B + 2, B + 1], dtype=np.int64)
    with pytest.raises(ValueError):
        resolve_roots_np(ids, np.array([-1, -1]), np.array([1, 1], dtype=np.int8))
