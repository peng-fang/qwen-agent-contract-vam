"""端到端冒烟测试：上传 → 抽条款 → 证据反查 → 版本对比 → 无模型降级。

用法：
    python scripts/smoke_api.py [--base http://127.0.0.1:8001]

依赖：requests。失败时以非 0 退出，便于交付前自检。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'demo_data'
CASES = ROOT / 'eval_data' / 'cases'


def _fail(message: str) -> None:
    print(f'FAIL: {message}')
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:8001')
    args = parser.parse_args()
    base = args.base.rstrip('/')

    health = requests.get(f'{base}/api/health', timeout=5)
    if health.status_code != 200 or health.json().get('status') != 'ok':
        _fail(f'健康检查异常：{health.status_code} {health.text[:200]}')
    print('OK  health')

    promo = DEMO / 'promo_gym.pdf'
    contract = DEMO / 'contract_gym.pdf'
    with promo.open('rb') as promo_fp, contract.open('rb') as contract_fp:
        response = requests.post(
            f'{base}/api/contract/clauses',
            files=[
                ('files', (promo.name, promo_fp, 'application/pdf')),
                ('files', (contract.name, contract_fp, 'application/pdf')),
            ],
            data={'roles': 'promo,contract'},
            timeout=120,
        )
    if response.status_code != 200:
        _fail(f'条款抽取失败：{response.status_code} {response.text[:300]}')
    payload = response.json()
    if len(payload['matches']) != 5:
        _fail(f"匹配数量应为 5，实际 {len(payload['matches'])}")
    review = payload['evidence_review']
    if review['failed'] != 0:
        _fail(f"证据复核失败 {review['failed']} 条：{review['failures'][:2]}")
    risk = payload['risk']
    if not (0 <= risk['score'] <= 100) or 'level' not in risk:
        _fail(f'风险评分异常：{risk}')
    evidence = payload['clauses'][0]['evidence']
    print(
        f"OK  clauses  结论={[(m['verdict_group'], m['verdict']) for m in payload['matches']]} "
        f"复核={review['passed']}/{review['checked']} 风险={risk['score']}({risk['level']})"
    )

    lookup = requests.get(
        f"{base}/api/contract/evidence/{evidence['evidence_id']}", timeout=10,
    )
    if lookup.status_code != 200:
        _fail(f'证据反查失败：{lookup.status_code} {lookup.text[:200]}')
    resolved = lookup.json()
    if resolved['quote'] != evidence['quote'] or not resolved['verified']:
        _fail('证据反查返回的 quote 与上传结果不一致')
    missing = requests.get(f'{base}/api/contract/evidence/ev-doc-nope-p1-c0-1', timeout=10)
    if missing.status_code != 404:
        _fail(f'非法 evidence_id 应返回 404，实际 {missing.status_code}')
    print(f"OK  evidence {evidence['evidence_id']} -> p{resolved['page']} {resolved['quote'][:24]}")

    old_case = CASES / 'case_001_contract.txt'
    new_case = CASES / 'case_002_contract.txt'
    with old_case.open('rb') as old_fp, new_case.open('rb') as new_fp:
        versions = requests.post(
            f'{base}/api/contract/versions',
            files={
                'old_file': (old_case.name, old_fp, 'text/plain'),
                'new_file': (new_case.name, new_fp, 'text/plain'),
            },
            timeout=60,
        )
    if versions.status_code != 200:
        _fail(f'版本对比失败：{versions.status_code} {versions.text[:200]}')
    version_payload = versions.json()
    if len(version_payload['rows']) != 5:
        _fail(f"版本对比应返回 5 类条款，实际 {len(version_payload['rows'])}")
    print(f"OK  versions  summary={version_payload['summary']}")

    vam = requests.post(f'{base}/api/vam/run', json={'query': '测试无模型时的降级'}, timeout=60)
    if vam.status_code == 200:
        print('OK  vam       模型可用，返回 200（本机已配置模型）')
    elif vam.status_code == 503:
        detail = vam.json().get('detail', '')
        if '推演服务不可用' not in detail:
            _fail(f'503 缺少可读提示：{detail[:200]}')
        print(f'OK  vam       无模型降级 503：{detail[:60]}...')
    else:
        _fail(f'推演接口异常：{vam.status_code} {vam.text[:200]}')

    print('\n所有冒烟检查通过。')


if __name__ == '__main__':
    try:
        main()
    except requests.RequestException as exc:
        _fail(f'请求失败：{exc}')
