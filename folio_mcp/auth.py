"""Each macOS user/profile has its own Folio key. No plaintext fallback."""
import getpass
import os
import re
import sys
from pathlib import Path
from contextlib import contextmanager
import fcntl
from keyring.backends.macOS import Keyring

class FolioError(RuntimeError):
    pass

def profile():
    name = os.environ.get('FOLIO_PROFILE', 'default')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
        raise FolioError('Ugyldig FOLIO_PROFILE.')
    return name

def root():
    path = Path.home() / 'Library' / 'Application Support' / 'folio-mcp' / profile()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path

@contextmanager
def lock():
    fd = os.open(root() / 'session.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

def store():
    if sys.platform != 'darwin':
        raise FolioError('Piloten krever macOS Nøkkelring.')
    return Keyring()

def token():
    try:
        value = store().get_password('no.folio.mcp.api', profile())
    except Exception:
        raise FolioError('Kunne ikke lese Nøkkelring.') from None
    if not value:
        raise FolioError('Kjør folio-mcp login i Terminal først.')
    return value

def login():
    if not sys.stdin.isatty():
        raise FolioError('Innlogging må gjøres interaktivt i Terminal.')
    value = getpass.getpass('Din Folio API-nøkkel (skjult): ').strip()
    if not value or any(c.isspace() for c in value):
        raise FolioError('Ugyldig API-nøkkel.')
    with lock():
        try:
            store().set_password('no.folio.mcp.api', profile(), value)
        except Exception:
            raise FolioError('Kunne ikke lagre i Nøkkelring.') from None
    print('Nøkkel lagret. Kjør folio-mcp doctor for å teste tilgangen.')

def logout():
    with lock():
        if store().get_password('no.folio.mcp.api', profile()):
            store().delete_password('no.folio.mcp.api', profile())
    print('Lokal nøkkel slettet. Tilbakekall nøkkelen i Folio ved behov.')
