"""Resolve each comment's root story and depth from the parent map.

`resolve_roots` is the small dict reference implementation. `resolve_roots_np`
does the same thing over numpy arrays with pointer jumping, which is what the
snapshot build uses at millions of items. `thread_type_of` labels a root item.
"""

from __future__ import annotations

import math

import numpy as np

ROOT_KINDS = ("story", "poll", "job")

KIND_OTHER = np.int8(0)
KIND_COMMENT = np.int8(1)
KIND_ROOT = np.int8(2)

_TITLE_PREFIXES = (
    ("Ask HN:", "ask_hn"),
    ("Show HN:", "show_hn"),
    ("Launch HN:", "launch_hn"),
    ("Tell HN:", "tell_hn"),
)


def kind_code(type_str: str | None) -> int:
    if type_str == "comment":
        return int(KIND_COMMENT)
    if type_str in ROOT_KINDS:
        return int(KIND_ROOT)
    return int(KIND_OTHER)


def thread_type_of(item_type: str | None, title: str | None) -> str:
    if item_type == "story":
        t = title or ""
        for prefix, name in _TITLE_PREFIXES:
            if t.startswith(prefix):
                return name
        return "story"
    if item_type in ("poll", "job"):
        return item_type
    return "unknown"


def resolve_roots(
    parent: dict[int, int], kind: dict[int, str]
) -> tuple[dict[int, tuple[int, int]], set[int]]:
    """For every comment id: (root_id, depth). Depth 1 = direct reply to a root.

    Unresolved chains (missing ancestors, non-root/non-comment ancestors, cycles)
    get no entry; ancestors absent from `kind` are collected into `missing`.
    """
    memo: dict[int, tuple[int, int] | None] = {}
    missing: set[int] = set()
    for cid, k in kind.items():
        if k != "comment" or cid in memo:
            continue
        chain: list[int] = []
        seen: set[int] = set()
        node = cid
        res: tuple[int, int] | None
        while True:
            if node in memo:
                res = memo[node]
                break
            if node in seen:
                res = None
                break
            nk = kind.get(node)
            if nk is None:
                missing.add(node)
                res = None
                break
            if nk in ROOT_KINDS:
                res = (node, 0)
                break
            if nk != "comment":
                res = None
                break
            seen.add(node)
            chain.append(node)
            nxt = parent.get(node)
            if nxt is None:
                res = None
                break
            node = nxt
        for node in reversed(chain):
            if res is None:
                memo[node] = None
            else:
                res = (res[0], res[1] + 1)
                memo[node] = res
    roots = {i: r for i, r in memo.items() if r is not None}
    return roots, missing


def resolve_roots_np(
    ids: np.ndarray, parent: np.ndarray, kind: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized resolve_roots over a sorted-unique int64 id array.

    parent: int64, -1 when the item has no parent. kind: int8 via kind_code.
    Returns (root_id, depth, missing): per-row int64 (-1 = unresolved for
    non-comments and unresolved comments) and the sorted unique int64 ids that
    are a comment's parent but absent from `ids`.
    """
    ids = np.asarray(ids, dtype=np.int64)
    parent = np.asarray(parent, dtype=np.int64)
    kind = np.asarray(kind, dtype=np.int8)
    if len(ids) and (np.diff(ids) <= 0).any():
        raise ValueError("ids must be sorted and unique")
    n = len(ids)
    arange = np.arange(n, dtype=np.int64)
    if n == 0:
        return arange - 1, arange - 1, np.empty(0, dtype=np.int64)

    is_comment = kind == KIND_COMMENT
    has_parent = parent != -1
    pos = np.searchsorted(ids, np.where(has_parent, parent, 0))
    pos_clip = np.minimum(pos, n - 1)
    found = has_parent & (pos < n) & (ids[pos_clip] == np.where(has_parent, parent, 0))
    link = is_comment & found

    nxt = np.where(link, pos_clip, arange)
    dist = np.where(link, np.int64(1), np.int64(0))
    rounds = int(math.ceil(math.log2(max(n, 2)))) + 2
    for _ in range(rounds):
        prev = nxt
        dist = dist + dist[nxt]
        nxt = nxt[nxt]
        if np.array_equal(nxt, prev):
            break

    resolved = is_comment & (kind[nxt] == KIND_ROOT)
    root_id = np.where(resolved, ids[nxt], np.int64(-1))
    depth = np.where(resolved, dist, np.int64(-1))

    miss_vals = np.unique(parent[is_comment & has_parent & ~found])
    return root_id, depth, miss_vals
