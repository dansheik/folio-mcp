import argparse
import json
import sys
from pathlib import Path
from . import auth, assignments, client

def main():
    parser = argparse.ArgumentParser(description='Folio MCP – fakturamatching på Mac')
    parser.add_argument('command', nargs='?', default='serve', choices=['serve','login','logout','config','doctor','approve','purge'])
    parser.add_argument('proposal_id', nargs='?')
    args = parser.parse_args()
    try:
        if args.command == 'serve':
            from .server import mcp
            mcp.run(transport='stdio')
        elif args.command == 'login': auth.login()
        elif args.command == 'logout': auth.logout()
        elif args.command == 'approve':
            if not args.proposal_id: raise auth.FolioError('Oppgi forslags-ID.')
            assignments.approve(args.proposal_id)
        elif args.command == 'purge': assignments.purge()
        elif args.command == 'config':
            print(json.dumps({'mcpServers': {'folio': {'command': str(Path(sys.executable).parent / 'folio-mcp'),
                    'args': ['serve'], 'env': {'FOLIO_PROFILE': auth.profile()}}}}, indent=2))
        elif args.command == 'doctor':
            response = client.get('accounts')
            print(json.dumps({'status':'ok', 'account_count':len(response['accounts']), 'profile':auth.profile()}))
    except (auth.FolioError, OSError) as exc:
        print(str(exc) if isinstance(exc, auth.FolioError) else 'Lokal fil-/systemfeil. Kontroller sti og tilgang.', file=sys.stderr)
        raise SystemExit(1) from None

if __name__ == '__main__': main()
