"""Single authorized protocol probe. Not used by the web app or test suite live."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import httpx

ENDPOINT = 'https://intlapi.thingo.com.cn/v1/chat/completions'
MODEL = 'gpt-6.1-sol'
AUTHORIZATION_ID = 'supervision-2026-11-19-single-probe'


def probe(*, key: str, excerpt: str, ledger: Path, transport=None) -> dict:
    if not key.strip() or not 1 <= len(excerpt) <= 300:
        raise ValueError('Missing local key or invalid public excerpt length')
    payload = {'model': MODEL, 'messages': [{'role': 'user', 'content': 'Summarize this excerpt in one short English sentence:\n' + excerpt}], 'max_tokens': 200, 'stream': False}
    ledger.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(ledger)
    try:
        db.execute('CREATE TABLE IF NOT EXISTS attempts (authorization_id TEXT PRIMARY KEY, started_at TEXT NOT NULL, excerpt_sha256 TEXT NOT NULL, result_json TEXT)')
        # Commit BEFORE any network operation. A failure/crash consumes the permit.
        try:
            db.execute('INSERT INTO attempts VALUES (?,?,?,NULL)', (AUTHORIZATION_ID, datetime.now(timezone.utc).isoformat(), hashlib.sha256(excerpt.encode()).hexdigest()))
            db.commit()
        except sqlite3.IntegrityError:
            raise RuntimeError('This single-request authorization is already consumed') from None
        result = {'attempts_consumed': 1, 'requested_model': MODEL, 'max_tokens_requested': 200, 'excerpt_characters': len(excerpt), 'actual_charge_confirmed': False, 'status': 'failed'}
        try:
            # No redirects, environment proxies or transport retries. Never log headers/body.
            transport = transport if transport is not None else httpx.HTTPTransport(retries=0)
            with httpx.Client(transport=transport, timeout=httpx.Timeout(60, connect=15), follow_redirects=False, trust_env=False) as client:
                response = client.post(ENDPOINT, headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}, json=payload)
            result['http_status'] = response.status_code
            # Never persist raw error bodies: providers may echo credentials.
            if not 200 <= response.status_code < 300:
                result['error'] = 'Provider returned non-success HTTP status; error body withheld'
            else:
                try:
                    data = response.json()
                except ValueError:
                    data = None
                if not isinstance(data, dict):
                    result['error'] = 'Success response is not a JSON object'
                else:
                    # Observed fields only. No response schema was assumed by the request.
                    result['response_field_presence'] = {name: name in data for name in ('id','model','choices','usage','error')}
                    model = data.get('model')
                    if isinstance(model, str): result['returned_model'] = model[:120].replace(key, '[REDACTED]')
                    usage = data.get('usage')
                    if isinstance(usage, dict):
                        result['usage'] = {name: usage[name] for name in ('prompt_tokens','completion_tokens','total_tokens') if type(usage.get(name)) is int and usage[name] >= 0}
                    choices = data.get('choices')
                    first = choices[0] if isinstance(choices,list) and choices and isinstance(choices[0],dict) else {}
                    finish = first.get('finish_reason')
                    result['finish_reason'] = finish if finish in ('stop','length','content_filter','tool_calls','function_call') else None
                    result['truncated'] = finish == 'length' if finish is not None else None
                    message = first.get('message')
                    text = message.get('content') if isinstance(message,dict) else None
                    if isinstance(text,str) and text.strip():
                        result['text'] = text[:6000].replace(key, '[REDACTED]')
                        result['status'] = 'text_received'
                    else:
                        result['error'] = 'No nonempty textual choices[0].message.content observed'
        except httpx.TimeoutException:
            result['error'] = 'Request timed out; permit consumed; no retry'
        except Exception:
            # Exception repr/str can contain headers or echoed secrets.
            result['error'] = 'Transport or response processing failed; details withheld; no retry'
        db.execute('UPDATE attempts SET result_json=? WHERE authorization_id=?', (json.dumps(result,ensure_ascii=False),AUTHORIZATION_ID))
        db.commit()
        return result
    finally:
        db.close()
