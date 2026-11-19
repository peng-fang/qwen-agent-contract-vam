"""Resume a verification with separately attributed, validated user facts."""
from copy import deepcopy

from clause_extraction import Document, DocRole, PageText, analyze_documents
from clause_extraction.amounts import _refund_check
from . import workflow_store as store


def create(bundle: dict) -> dict:
    data = {'bundle': deepcopy(bundle), 'facts': {}, 'fact_history': []}
    docs = documents(data)
    calculated = analyze_documents(docs)
    for item, match in zip(data['bundle']['matches'], calculated.matches):
        if match.clause_type.value == 'refund':
            item['amount'] = _refund_check(match, calculated.clauses, docs, {})
    return public(store.save('verifications', data))


def documents(task: dict) -> list[Document]:
    return [Document(document_id=d['document_id'], filename=d['filename'], role=DocRole(d['role']),
                     pages=[PageText(page=p['page'], text=p['text']) for p in d['pages']])
            for d in task['bundle']['documents']]


def supplement(task_id: str, facts: dict, revision: int) -> dict:
    task = store.get('verifications', task_id)
    if task['revision'] != revision:
        raise store.RevisionConflict('核验已更新，请重新加载')
    task['facts'].update(facts)
    task['fact_history'].append({'facts': facts, 'source': 'user', 'based_on_revision': revision})
    docs = documents(task)
    bundle = analyze_documents(docs)
    original_file_ids = {d['document_id']: d.get('file_id') for d in task['bundle']['documents']}
    result = bundle.to_dict()
    for doc in result['documents']:
        doc['file_id'] = original_file_ids.get(doc['document_id'])
    for item, match in zip(result['matches'], bundle.matches):
        if match.clause_type.value == 'refund':
            item['amount'] = _refund_check(match, bundle.clauses, docs, task['facts'])
    task['bundle'] = result
    # Semantic opinions and amounts must never survive a change to confirmed facts.
    task.pop('semantic_review', None)
    task = store.save('verifications', task, expected=revision)
    return public(task)


def public(task: dict) -> dict:
    return {**task['bundle'], 'task_id': task['id'], 'task_revision': task['revision'],
            'confirmed_facts': task['facts'], 'fact_history': task['fact_history'],
            'semantic_review': task.get('semantic_review')}
