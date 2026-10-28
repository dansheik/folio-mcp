"""Bound, expiring, one-use approval for attaching a specific file to an event."""
import hashlib
import json
import os
import secrets
import shlex
import sys
from pathlib import Path
import time
from . import auth, client, documents
from .auth import FolioError

TTL = 600

def digest(data): return hashlib.sha256(data).hexdigest()
def fingerprint(event): return digest(json.dumps(event, sort_keys=True, separators=(',', ':')).encode())

def paths(plan_id):
    if len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
        raise FolioError('Ugyldig forslags-ID.')
    return auth.root() / (plan_id + '.json'), auth.root() / (plan_id + '.bin')

def save(path, value):
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)

def load(plan_id):
    path, blob = paths(plan_id)
    if not path.exists(): raise FolioError('Forslaget finnes ikke i denne profilen.')
    plan = json.loads(path.read_text())
    if plan['expires_at'] < time.time(): raise FolioError('Forslaget er utløpt. Lag et nytt forslag.')
    return path, blob, plan

def preview(plan):
    return {k: plan[k] for k in ['proposal_id', 'profile', 'event_id', 'filename', 'size', 'sha256', 'event', 'expires_at', 'status']}

def prepare(event_id, file_path):
    import re
    if not re.fullmatch(client.UUID, event_id): raise FolioError('Ugyldig event-ID.')
    data, mime, filename = documents.file_data(file_path)
    with auth.lock():
        event = client._send('GET', f'events/{event_id}')['event']
        if event.get('id') != event_id: raise FolioError('Folio returnerte feil hendelse.')
        for existing in auth.root().glob('*.json'):
            prior = json.loads(existing.read_text())
            if prior.get('event_id') == event_id and prior.get('sha256') == digest(data) and prior.get('status') in {'uploaded', 'submitting', 'unknown'}:
                raise FolioError('Samme fil har allerede vært sendt til denne hendelsen. Kontroller Folio før ny opplasting.')
        plan_id = secrets.token_hex(16)
        path, blob = paths(plan_id)
        plan = {'proposal_id': plan_id, 'profile': auth.profile(), 'event_id': event_id,
                'filename': filename, 'mime': mime, 'size': len(data), 'sha256': digest(data),
                'event': event, 'event_fingerprint': fingerprint(event), 'credential_fingerprint': digest(auth.token().encode()),
                'expires_at': time.time()+TTL, 'status': 'pending'}
        fd = os.open(blob, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as stream: stream.write(data)
        save(path, plan)
        return {**preview(plan), 'approval_command': f'FOLIO_PROFILE={auth.profile()} {shlex.quote(str(Path(sys.executable).parent / "folio-mcp"))} approve {plan_id}',
                'next_step': 'Vis fil, beløp, mottaker, konto, hendelse og eksisterende vedlegg. Brukeren godkjenner i Terminal; kall deretter folio_attach_invoice. Ingen opplasting er utført.'}

def approve(plan_id):
    """Human-only CLI entry, never registered as an MCP tool."""
    import sys
    if not sys.stdin.isatty(): raise FolioError('Godkjenning krever en interaktiv terminal.')
    with auth.lock():
        path, _, plan = load(plan_id)
        if plan['status'] != 'pending': raise FolioError('Forslaget kan ikke godkjennes på nytt.')
        print(json.dumps(preview(plan), ensure_ascii=False, indent=2))
        answer = input('Last opp denne filen til denne Folio-hendelsen? Skriv JA: ')
        if answer != 'JA': raise FolioError('Ingen godkjenning gitt.')
        if plan['expires_at'] < time.time(): raise FolioError('Forslaget er utløpt.')
        plan['status'] = 'approved'; save(path, plan)
    print('Godkjent én gang. Be Claude kjøre folio_attach_invoice med forslags-ID-en.')

def attach(plan_id):
    with auth.lock():
        path, blob, plan = load(plan_id)
        if plan['status'] != 'approved': raise FolioError('Forslaget mangler gyldig, ubrukt godkjenning fra Terminal.')
        for existing in auth.root().glob('*.json'):
            if existing == path:
                continue
            prior = json.loads(existing.read_text())
            if (prior.get('event_id') == plan['event_id'] and prior.get('sha256') == plan['sha256']
                    and prior.get('status') in {'uploaded', 'submitting', 'unknown'}):
                raise FolioError('Samme fil er allerede sendt eller har et ukjent utfall for denne hendelsen.')
        if digest(auth.token().encode()) != plan['credential_fingerprint']: raise FolioError('Folio-tilgangen er endret. Lag et nytt forslag.')
        with blob.open('rb') as stream: data = stream.read(client.MAX_BYTES+1)
        if digest(data) != plan['sha256']: raise FolioError('Filen er endret. Lag et nytt forslag.')
        event = client._send('GET', f"events/{plan['event_id']}")['event']
        if fingerprint(event) != plan['event_fingerprint']:
            raise FolioError('Hendelsen eller vedleggene er endret. Kontroller og lag et nytt forslag.')
        # Consume before sending: a timeout must never trigger an automatic duplicate upload.
        plan['status'] = 'submitting'; save(path, plan)
        try:
            result = client.upload_attachment(plan['event_id'], data, plan['mime'], plan['filename'])
            from uuid import UUID
            UUID(result['id'])
        except Exception:
            plan['status'] = 'unknown'; save(path, plan)
            raise FolioError('Opplastingen ble ikke bekreftet. Kontroller hendelsen i Folio; ikke gjenta automatisk.') from None
        plan['status'] = 'uploaded'; save(path, plan)
        blob.unlink(missing_ok=True)
        return {'status': 'uploaded', 'event_id': plan['event_id'], 'sha256': plan['sha256'], 'result': result,
                'note': 'Vedlegget er lastet opp. Ingen betaling eller eksplisitt ferdigmarkering ble utført.'}

def purge():
    """Explicit local cleanup, including uploaded/uncertain history."""
    with auth.lock():
        for pattern in ('*.json', '*.bin', '*.tmp'):
            for path in auth.root().glob(pattern): path.unlink()
    print('Lokale forslag, fakturakopier og opplastingshistorikk slettet for profilen.')
