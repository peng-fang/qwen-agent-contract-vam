"""Coordinate contract evidence, scenario runs and deterministic comparisons."""

import copy
import sys
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from app.schemas import VamCompareRequest, VamRunRequest, VamStudy
from app.services.vam_evidence import resolve_evidence

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vam_sandbox import deepen_leaf, find_leaf_path, render_markdown_report, run_sandbox  # noqa: E402
from vam_sandbox.comparison import build_comparison  # noqa: E402
from vam_sandbox.pipeline import compute_scores, iter_leaves_with_path  # noqa: E402

# Recent snapshots support backtracking and preserve the source and score data
# across requests. The server never trusts a tree or score posted by a client.
_MAX_SNAPSHOTS = 32
_snapshots: OrderedDict[str, dict] = OrderedDict()
_lock = Lock()


class RunUnavailable(ValueError):
    pass


def _store(result: dict) -> dict:
    with _lock:
        _snapshots[result['run_id']] = result
        _snapshots.move_to_end(result['run_id'])
        if len(_snapshots) > _MAX_SNAPSHOTS:
            _snapshots.popitem(last=False)
    return _public(result)


def _load(run_id: Any) -> dict:
    with _lock:
        result = _snapshots.get(run_id) if isinstance(run_id, str) else None
        if result is None:
            raise RunUnavailable('此推演记录已不可用，请重新开始推演。')
        _snapshots.move_to_end(run_id)
        return result


def _public(result: dict) -> dict:
    tree = result['tree']
    return {
        'run_id': result['run_id'],
        'query': result['query'],
        'scenario': tree['scenario'],
        'assumptions': tree['assumptions'],
        'uncertainties': tree['uncertainties'],
        'warnings': tree.get('warnings', []),
        'tree': tree,
        'ranked': result['ranked'],
        'best': result['best'],
        'study': {key: value for key, value in result['study'].items() if key != 'analyzed_actions'},
        'comparison': result['comparison'],
    }


def _study(model: VamStudy) -> dict:
    study = model.model_dump()
    study.pop('query', None)
    study.pop('evidence', None)
    study['actions'] = [
        {**item, 'label': item['label'].strip(), 'terms': item['terms'].strip(), 'id': f'A{index}'}
        for index, item in enumerate(study['actions'], 1)
    ]
    return study


def run(request: VamRunRequest | str) -> dict:
    if isinstance(request, str):
        request = VamRunRequest(query=request)
    study = _study(request)
    study['evidence'] = resolve_evidence(request.evidence)
    query = request.query.strip()
    if not query and not study['evidence']:
        raise ValueError('请输入条款或背景，或从合同核验带入原文。')
    return _store(run_sandbox(query or '仅分析所选合同原文。', study=study))


def deepen(result: dict, leaf_id: str) -> dict:
    stored = _load(result.get('run_id'))
    return _store(deepen_leaf(stored, find_leaf_path(stored, leaf_id)))


def compare(request: VamCompareRequest) -> dict:
    previous = _load(request.run_id)
    tree = copy.deepcopy(previous['tree'])
    study = copy.deepcopy(previous['study'])
    updated = VamStudy.model_validate({
        **study, 'actions': request.actions,
        'weights': request.weights or study.get('weights'),
    })
    study.update(_study(updated))
    leaves = iter_leaves_with_path(tree)
    nodes = {node['id']: node for _, node in leaves}
    if request.triggers.keys() - nodes.keys():
        raise ValueError('只能调整当前树内的末端情景。')
    for leaf_id, trigger in request.triggers.items():
        node = nodes[leaf_id]
        original = node.get('trigger', 'unknown')
        if original != 'unknown' and trigger not in (original, 'unknown'):
            raise ValueError('调整后的状态与情景前提冲突。可标为待确认，或修改背景后重新推演。')
        if trigger == original:
            node.pop('trigger_override', None)
        else:
            node['trigger_override'] = trigger

    evaluations = {score['leaf_id']: score for score in previous['ranked']}
    ranked, best = compute_scores(tree, evaluations, study['weights'])
    return _store({
        **previous, 'run_id': uuid4().hex, 'tree': tree, 'study': study,
        'ranked': ranked, 'best': best, 'comparison': build_comparison(study, leaves),
        'trace_parent_run_id': request.run_id, 'raw_eval': [],
        'raw_diverge': {}, 'diverge_text': '', 'eval_text': '',
    })


def export_markdown(result: dict) -> str:
    return render_markdown_report(_load(result.get('run_id')))
