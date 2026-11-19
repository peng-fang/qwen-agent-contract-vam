"""Reuse Qwen-Agent locally, or the existing course-agent key with Responses API."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

import jsonschema


class ModelUnavailable(RuntimeError):
    pass


def generate_text(instructions: str, text: str, *, model: str | None = None) -> str:
    """Responses transport for the existing rental-review JSON prompts."""
    from openai import OpenAI
    key = _key()
    if not key:
        raise ModelUnavailable('未找到现有 OpenAI 密钥')
    # This opt-in bridge uses the official endpoint only; no implicit key forwarding.
    try:
        with OpenAI(api_key=key, base_url='https://api.openai.com/v1', timeout=70, max_retries=1,
                    default_headers={'Accept-Encoding': 'gzip, deflate'}) as client:
            response = client.responses.create(
                model=model or os.getenv('WORKFLOW_MODEL', os.getenv('OPENAI_MODEL', 'gpt-6-luna')),
                instructions=instructions, input='请按任务指令输出 JSON 对象。\n' + text, max_output_tokens=4000,
                text={'format': {'type': 'json_object'}},
            )
        return response.output_text
    except Exception as exc:
        raise ModelUnavailable(f'模型调用失败（{type(exc).__name__}）') from None


def _key() -> str:
    key = os.getenv('OPENAI_API_KEY', '').strip()
    if key:
        return key
    # Resolve the sibling project, without copying its DPAPI blob or source.
    module_path = Path(__file__).resolve().parents[4] / 'course_agent' / 'local_key.py'
    if not module_path.is_file():
        return ''
    try:
        spec = importlib.util.spec_from_file_location('contract_workflow_key', module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_key('openai')
    except OSError:
        return ''


def generate_json(instructions: str, payload: dict, schema: dict, name: str) -> tuple[dict, dict]:
    """Bounded call; expose neither raw provider errors nor credential material."""
    provider = os.getenv('WORKFLOW_MODEL_PROVIDER', 'auto').strip().lower()
    if provider not in {'auto', 'openai', 'qwen'}:
        raise ModelUnavailable('WORKFLOW_MODEL_PROVIDER 只支持 auto、openai、qwen')
    base = os.getenv('WORKFLOW_API_BASE', 'https://api.openai.com/v1').rstrip('/')
    custom = base != 'https://api.openai.com/v1'
    key = (os.getenv('WORKFLOW_API_KEY', '').strip() if custom else _key()) if provider != 'qwen' else ''
    if provider == 'auto':
        provider = 'openai' if key or custom else 'qwen'
    try:
        if provider == 'openai':
            from openai import OpenAI
            if not key:
                if custom:
                    raise ModelUnavailable('自定义接口需要专用 WORKFLOW_API_KEY')
                raise ModelUnavailable('未找到现有 OpenAI 密钥；请配置环境变量或同用户的本地读取模块')
            model = os.getenv('WORKFLOW_MODEL', os.getenv('OPENAI_MODEL', 'gpt-6-luna'))
            with OpenAI(api_key=key, base_url=base, timeout=70, max_retries=1,
                        default_headers={'Accept-Encoding': 'gzip, deflate'}) as client:
                response = client.responses.create(
                    model=model, instructions=instructions,
                    input=json.dumps(payload, ensure_ascii=False), max_output_tokens=3000,
                    text={'format': {'type': 'json_schema', 'name': name, 'strict': True, 'schema': schema}},
                )
            result = json.loads(response.output_text)
            usage = response.usage
            metadata = {'provider': provider, 'model': model, 'input_tokens': usage.input_tokens if usage else None,
                        'output_tokens': usage.output_tokens if usage else None}
        else:
            from qwen_agent.llm import get_chat_model
            from vam_sandbox.pipeline import default_llm_cfg, _extract_json
            cfg = default_llm_cfg()
            output = get_chat_model(cfg).chat(messages=[
                {'role': 'system', 'content': instructions + '\n只输出符合以下结构的 JSON：' + json.dumps(schema)},
                {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
            ], stream=False)
            result = _extract_json(output[-1]['content'])
            metadata = {'provider': provider, 'model': cfg.get('model')}
        jsonschema.validate(result, schema)
        return result, metadata
    except ModelUnavailable:
        raise
    except Exception as exc:
        raise ModelUnavailable(f'模型未返回可用结果（{type(exc).__name__}），请稍后重试或检查后端配置') from None
