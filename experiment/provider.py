import asyncio
import os
import re
import httpx
from .common import require

class ProviderFailure(Exception):
    def __init__(self, category, *, retryable=False, http_status=None, retry_after=0):
        super().__init__(category)
        self.category, self.retryable = category, retryable
        self.http_status, self.retry_after = http_status, retry_after

def credentials():
    key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    require(bool(key), 'A model-provider credential is required in the environment.')
    return key

def request_body(prompt, cfg):
    return {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
            'generationConfig': cfg['generation_config']}

class Gemini:
    def __init__(self, cfg, client=None):
        self.cfg = cfg
        self.client = client or httpx.AsyncClient(timeout=cfg['retry_policy']['request_timeout_seconds'],
            headers={'x-goog-api-key': credentials()}, follow_redirects=False)

    async def close(self):
        await self.client.aclose()

    async def request(self, method, suffix, body=None):
        url = self.cfg['api_base'] + '/models/' + self.cfg['model'] + suffix
        try:
            response = await self.client.request(method, url, json=body)
        except httpx.TransportError as e:
            category = type(e).__name__
            raise ProviderFailure(category, retryable=category in self.cfg['retry_policy']['retry_transport']) from None
        if response.status_code != 200:
            # Never log URL headers, credentials, or unsanitized exception/error bodies.
            delay = response.headers.get('retry-after', '0')
            try: delay = float(delay)
            except ValueError: delay = 0
            raise ProviderFailure(f'http_{response.status_code}', http_status=response.status_code,
                retryable=response.status_code in self.cfg['retry_policy']['retry_http_statuses'], retry_after=delay)
        try: return response.json()
        except ValueError: raise ProviderFailure('non_json_response', retryable=False) from None

    async def model(self):
        data = await self.request('GET', '')
        require(data.get('name') == 'models/' + self.cfg['model'], 'Model metadata resolved to an unexpected ID')
        require('generateContent' in data.get('supportedGenerationMethods', []), 'Requested model lacks generateContent')
        require(data.get('outputTokenLimit', 0) >= self.cfg['generation_config']['maxOutputTokens'], 'Output limit too small')
        require(data.get('inputTokenLimit', 0) >= self.cfg['prompt_utf8_byte_limit'], 'Input limit below conservative prompt bound')
        require(0 <= self.cfg['generation_config']['temperature'] <= data.get('maxTemperature', 2), 'Temperature outside advertised range')
        require(data.get('thinking', True) is not False, 'Model metadata says thinking configuration is unsupported')
        return data

    async def count(self, prompt):
        data = await self.request('POST', ':countTokens', {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}]})
        require(type(data.get('totalTokens')) is int and data['totalTokens'] > 0, 'Invalid countTokens response')
        return data['totalTokens']

    async def generate(self, prompt):
        return await self.request('POST', ':generateContent', request_body(prompt, self.cfg))

def parse_response(raw):
    """Classify integrity independently of gold correctness. Invalid outputs are not retried."""
    raw = raw if isinstance(raw, dict) else {}
    candidates = raw.get('candidates', [])
    candidates = candidates if isinstance(candidates, list) else []
    feedback = raw.get('promptFeedback', {})
    feedback = feedback if isinstance(feedback, dict) else {}
    status, answer, finish = 'malformed', '', None
    if feedback.get('blockReason'): status = 'refused'
    elif len(candidates) == 1 and isinstance(candidates[0], dict):
        c = candidates[0]; finish = c.get('finishReason')
        content = c.get('content', {})
        parts = content.get('parts', []) if isinstance(content, dict) else []
        parts = parts if isinstance(parts, list) else []
        parts = [p for p in parts if isinstance(p, dict)]
        answer = ''.join(p.get('text', '') for p in parts if not p.get('thought') and isinstance(p.get('text'), str)).strip()
        if finish == 'MAX_TOKENS': status = 'truncated'
        elif finish in ('SAFETY', 'RECITATION', 'BLOCKLIST', 'PROHIBITED_CONTENT', 'SPII'): status = 'refused'
        elif finish != 'STOP' or any('functionCall' in p for p in parts): status = 'malformed'
        elif not answer: status = 'empty'
        elif len(answer.split()) > 100 or '\n' in answer or answer.startswith('```'): status = 'malformed'
        elif re.match(r"^(?:I (?:cannot|can't|am unable to)|I'm (?:sorry|unable)|I do not have enough|Insufficient (?:information|context)|Cannot (?:answer|determine))\b", answer, re.I): status = 'refused'
        else: status = 'valid'
    # Store final text and provider metadata, never thought text/signatures.
    saved = {k: raw[k] for k in ('modelVersion', 'responseId', 'usageMetadata', 'promptFeedback') if k in raw}
    saved['candidates'] = [{k: c[k] for k in ('index', 'finishReason', 'safetyRatings', 'citationMetadata') if k in c}
                            for c in candidates if isinstance(c, dict)]
    usage = raw.get('usageMetadata', {})
    if not isinstance(usage, dict):
        usage = {}; status = 'malformed'
    else:
        usage = dict(usage)
        for key in list(usage):
            if key.endswith('TokenCount') and (type(usage[key]) is not int or usage[key] < 0):
                del usage[key]; status = 'malformed'
    version = raw.get('modelVersion')
    if version is not None and not isinstance(version, str):
        version = None; status = 'malformed'
    return {'status': status, 'answer': answer, 'finish_reason': finish,
            'returned_model_version': version, 'token_usage': usage,
            'provider_metadata': saved}
