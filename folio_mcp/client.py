"""Explicit API allowlist. Only invoice attachment uploads can write."""
import json
import re
import time
from urllib.parse import quote
import httpx
from .auth import FolioError, token, lock

ROOT = 'https://api.folio.no/v2'
MAX_BYTES = 15 * 1024 * 1024
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
READ_PATHS = [r'accounts', r'transactions', rf'transactions/{UUID}',
              r'accounts/\d{11}/transactions', r'accounts/\d{11}/balance/\d{4}-\d{2}-\d{2}',
              r'events', rf'events/{UUID}', r'categories/[A-Za-z0-9_-]{1,128}',
              rf'attachments/{UUID}/(?:original|cropped|128x128|256x256|512x512)']

def get(path, params=None, binary=False):
    if not any(re.fullmatch(pattern, path) for pattern in READ_PATHS):
        raise FolioError('API-stien er ikke tillatt.')
    with lock():
        return _send('GET', path, params=params, binary=binary)

def upload_attachment(event_id, data, mime, filename):
    """Internal: the caller holds the profile lock and has consumed an approval."""
    if not re.fullmatch(UUID, event_id) or mime not in {'application/pdf', 'image/png', 'image/jpeg'}:
        raise FolioError('Ugyldig vedlegg.')
    if not data or len(data) > MAX_BYTES:
        raise FolioError('Ugyldig vedleggsstørrelse.')
    return _send('POST', f'events/{event_id}/attachments', data=data, extra_headers={
        'Content-Type': mime, 'Content-Disposition': "attachment; filename*=UTF-8''" + quote(filename, safe='')})

def _send(method, path, params=None, binary=False, data=None, extra_headers=None):
    if method == 'GET':
        if not any(re.fullmatch(pattern, path) for pattern in READ_PATHS):
            raise FolioError('API-stien er ikke tillatt.')
    elif method != 'POST' or not re.fullmatch(rf'events/{UUID}/attachments', path):
        raise FolioError('Bare vedleggsopplasting kan skrive til Folio.')
    clean = {k: str(v).lower() if isinstance(v, bool) else v for k,v in (params or {}).items() if v is not None and v != ''}
    try:
        with httpx.Client(timeout=45, follow_redirects=False) as client:
            with client.stream(method, ROOT + '/' + path, params=clean, content=data, headers={
                'Authorization': 'Bearer ' + token(), 'User-Agent': 'folio-mcp/0.1.0',
                'Accept': '*/*' if binary else 'application/json', **(extra_headers or {})}) as response:
                if response.status_code != 200:
                    raise FolioError(f'Folio svarte HTTP {response.status_code}. Ingen automatisk gjentakelse. Ved opplasting: kontroller hendelsen før nytt forsøk.')
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise FolioError('Svaret overstiger 15 MiB. Avgrens datoperioden.')
                if binary:
                    return bytes(body), response.headers.get('content-type','').split(';')[0]
                return json.loads(body)
    except (httpx.HTTPError, ValueError):
        raise FolioError('Kunne ikke lese svar fra Folio. Ved opplasting kan utfallet være ukjent; kontroller Folio før nytt forsøk.') from None
    finally:
        time.sleep(0.3)
