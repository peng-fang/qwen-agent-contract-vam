from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys

from clause_extraction.schema import Clause, ClauseType, DocRole, Document, EvidenceSpan, PageText
from scripts.eval_clauses import _evidence_status

ROOT = Path(__file__).resolve().parents[1]


def test_evidence_diagnostics_distinguish_missing_clause_and_bad_citation():
    text = '退款手续费20%。服务期为一年。'
    document = Document('doc', 'contract.txt', DocRole.CONTRACT, [PageText(1, text)])
    quote = '退款手续费20%'
    span = EvidenceSpan('doc', 'contract.txt', DocRole.CONTRACT, 1, 'chunk', 0, len(quote), quote)
    clause = Clause(ClauseType.REFUND, span, {})
    # Negative Python slice offsets can still round-trip to the same quote.
    invalid = replace(clause, evidence=replace(span, char_start=-len(text),
                                               char_end=len(quote) - len(text)))
    assert text[invalid.evidence.char_start:invalid.evidence.char_end] == quote
    assert _evidence_status([invalid], document, quote) == 'invalid_location'
    assert _evidence_status([invalid, clause], document, quote) == 'located'
    assert _evidence_status([clause], document, '服务期为一年') == 'different_excerpt'
    assert _evidence_status([], document, quote) == 'missing_clause'
    assert _evidence_status([clause], document, None) == 'unexpected_clause'
    assert _evidence_status([], document, None) == 'not_annotated'


def test_heldout_cli_exports_trace_without_changing_metrics(tmp_path):
    args = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/eval_heldout.py'),
            '--dataset', 'heldout_v2']
    baseline = tmp_path / 'baseline'
    detailed = tmp_path / 'detailed'
    subprocess.run([*args, '--output-dir', str(baseline)], cwd=ROOT, check=True, timeout=30)
    subprocess.run([*args, '--output-dir', str(detailed), '--diagnostics'],
                   cwd=ROOT, check=True, timeout=30)

    metrics_name = 'eval_heldout_v2_metrics.json'
    plain_metrics = json.loads((baseline / metrics_name).read_bytes())
    detailed_metrics = json.loads((detailed / metrics_name).read_bytes())
    assert plain_metrics['overall'] == detailed_metrics['overall']
    assert plain_metrics['by_category'] == detailed_metrics['by_category']

    diagnostics_name = 'eval_heldout_v2_diagnostics.json'
    assert not (baseline / diagnostics_name).exists()
    trace = json.loads((detailed / diagnostics_name).read_bytes())
    label_bytes = (ROOT / 'eval_data/heldout_v2/labels.json').read_bytes()
    cases = {case['id']: case for case in json.loads(label_bytes)['cases']}
    rows = trace['rows']
    assert trace['schema_version'] == 1
    assert trace['labels_sha256'] == sha256(label_bytes).hexdigest()
    assert len(rows) == len({(row['case'], row['clause_type']) for row in rows})
    assert len(rows) == sum(len(case['expected_verdicts']) for case in cases.values())
    mismatches = [row for row in rows if row['gold'] != row['predicted']]
    assert len(mismatches) == plain_metrics['overall']['matching']['error_count']
    assert trace['summary']['verdict_mismatches'] == len(mismatches)
    for row in rows:
        case = cases[row['case']]
        assert row['gold'] == case['expected_verdicts'][row['clause_type']]
        for side in ('promo', 'contract'):
            if row[side]['status'] == 'located':
                text = case[f'{side}_text']
                assert any(text[ev['char_start']:ev['char_end']] == ev['quote']
                           for ev in (item['evidence'] for item in row[side]['candidates']))
