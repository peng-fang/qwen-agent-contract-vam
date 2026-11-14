"""Regression tests for VAM tree normalization."""

from __future__ import annotations

from vam_sandbox.pipeline import normalize_tree


def _collect_ids(tree):
    ids = []

    def walk(node):
        ids.append(node['id'])
        for child in node.get('children', []):
            walk(child)

    for branch in tree['branches']:
        walk(branch)
    return ids


def test_normalize_tree_rewrites_duplicate_model_ids():
    raw = {
        'scenario': 'duplicate ids',
        'assumptions': [],
        'uncertainties': [],
        'branches': [
            {
                'id': 'same',
                'branch': 'A',
                'children': [
                    {'id': 'same', 'branch': 'A1', 'children': []},
                ],
            },
            {'id': 'same', 'branch': 'B', 'children': []},
        ],
    }

    tree = normalize_tree(raw)
    ids = _collect_ids(tree)

    assert ids == ['B1', 'B1.1', 'B2']
    assert len(ids) == len(set(ids))
