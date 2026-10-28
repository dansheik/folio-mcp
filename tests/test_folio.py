import asyncio
from contextlib import nullcontext
import copy
import io
import json
import sys
import httpx
import pytest
from pypdf import PdfWriter
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from folio_mcp import auth, client, assignments, documents, server

EVENT = '457f0b7c-e3d6-44bf-9364-638b3d39dc7a'
ATTACHMENT = '8f1fc8d3-7900-4c05-8d67-f513ef760111'

@pytest.fixture
def staged(monkeypatch, tmp_path):
    root = tmp_path / 'state'; root.mkdir()
    monkeypatch.setattr(auth, 'root', lambda: root)
    monkeypatch.setattr(auth, 'lock', nullcontext)
    monkeypatch.setattr(auth, 'token', lambda: 'synthetic-token')
    monkeypatch.setattr(auth, 'profile', lambda: 'test')
    event = {'id': EVENT, 'amount': {'amount': '1250.00', 'currency': 'NOK'}, 'attachments': []}
    monkeypatch.setattr(client, '_send', lambda *a, **k: {'event': copy.deepcopy(event)})
    file = tmp_path / 'invoice.pdf'
    writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
    with file.open('wb') as stream: writer.write(stream)
    return file, event


def approved(monkeypatch, staged):
    plan = assignments.prepare(EVENT, str(staged[0]))
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'JA')
    assignments.approve(plan['proposal_id'])
    return plan['proposal_id']


def test_prepare_never_uploads(staged, monkeypatch):
    monkeypatch.setattr(client, 'upload_attachment', lambda *a: pytest.fail('unexpected upload'))
    result = assignments.prepare(EVENT, str(staged[0]))
    assert result['status'] == 'pending'
    path, blob = assignments.paths(result['proposal_id'])
    assert blob.read_bytes() == staged[0].read_bytes()
    assert path.stat().st_mode & 0o777 == 0o600
    assert blob.stat().st_mode & 0o777 == 0o600


def test_unapproved_upload_rejected(staged):
    plan = assignments.prepare(EVENT, str(staged[0]))
    with pytest.raises(auth.FolioError): assignments.attach(plan['proposal_id'])


def test_approval_must_be_interactive(staged, monkeypatch):
    plan = assignments.prepare(EVENT, str(staged[0]))
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    with pytest.raises(auth.FolioError): assignments.approve(plan['proposal_id'])


def test_declined_approval_does_not_authorize(staged, monkeypatch):
    plan = assignments.prepare(EVENT, str(staged[0]))
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda _: 'nei')
    with pytest.raises(auth.FolioError): assignments.approve(plan['proposal_id'])
    with pytest.raises(auth.FolioError): assignments.attach(plan['proposal_id'])


def test_success_is_single_use_and_same_file_blocked(staged, monkeypatch):
    plan_id = approved(monkeypatch, staged)
    calls = []
    monkeypatch.setattr(client, 'upload_attachment', lambda *args: calls.append(args) or {'id': ATTACHMENT})
    result = assignments.attach(plan_id)
    assert result['status'] == 'uploaded'
    assert calls[0][0] == EVENT and calls[0][1] == staged[0].read_bytes()
    assert not assignments.paths(plan_id)[1].exists()
    with pytest.raises(auth.FolioError): assignments.attach(plan_id)
    with pytest.raises(auth.FolioError): assignments.prepare(EVENT, str(staged[0]))
    assert len(calls) == 1


@pytest.mark.parametrize('change', ['file','event','credential','expiry'])
def test_changed_or_expired_plan_blocked(staged, monkeypatch, change):
    plan_id = approved(monkeypatch, staged)
    path, blob, plan = assignments.load(plan_id)
    if change == 'file': blob.write_bytes(b'changed')
    if change == 'event': staged[1]['attachments'] = [{'id': ATTACHMENT}]
    if change == 'credential': monkeypatch.setattr(auth, 'token', lambda: 'different-key')
    if change == 'expiry': plan['expires_at'] = 0; assignments.save(path, plan)
    monkeypatch.setattr(client, 'upload_attachment', lambda *a: pytest.fail('must not upload'))
    with pytest.raises(auth.FolioError): assignments.attach(plan_id)


def test_unknown_outcome_never_retried(staged, monkeypatch):
    plan_id = approved(monkeypatch, staged)
    calls = []
    def fail(*args):
        calls.append(args); raise TimeoutError
    monkeypatch.setattr(client, 'upload_attachment', fail)
    with pytest.raises(auth.FolioError): assignments.attach(plan_id)
    with pytest.raises(auth.FolioError): assignments.attach(plan_id)
    with pytest.raises(auth.FolioError): assignments.prepare(EVENT, str(staged[0]))
    assert len(calls) == 1
    assert assignments.load(plan_id)[2]['status'] == 'unknown'


def transport(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(client, 'lock', nullcontext)
    monkeypatch.setattr(client, 'token', lambda: 'synthetic-token')
    monkeypatch.setattr(client.time, 'sleep', lambda _: None)
    monkeypatch.setattr(client.httpx, 'Client', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


@pytest.mark.parametrize('method,path', [('POST','payments'),('GET','payments/signing'),('DELETE',f'events/{EVENT}/complete'),('PATCH',f'events/{EVENT}'),('GET','https://evil.test'),('GET','accounts/../payments')])
def test_write_and_path_barriers(method, path):
    with pytest.raises(auth.FolioError): client._send(method, path)


def test_documented_raw_upload_format(monkeypatch):
    def handler(req):
        assert req.method == 'POST'
        assert req.url.path == f'/v2/events/{EVENT}/attachments'
        assert req.headers['content-type'] == 'application/pdf'
        assert req.content == b'%PDF-test'
        assert '\n' not in req.headers['content-disposition']
        return httpx.Response(200, json={'id': ATTACHMENT})
    transport(monkeypatch, handler)
    assert client.upload_attachment(EVENT, b'%PDF-test', 'application/pdf', 'faktura\n.pdf')['id'] == ATTACHMENT


def test_no_redirect_or_secret_error_body(monkeypatch):
    calls=[]
    def handler(req):
        calls.append(req); return httpx.Response(302, text='private bank data', headers={'location':'https://evil.test'})
    transport(monkeypatch, handler)
    with pytest.raises(auth.FolioError) as exc: client.get('accounts')
    assert len(calls)==1 and 'private bank data' not in str(exc.value)


def row(amount='1250.00', currency='NOK', incoming=False):
    return {'id': ATTACHMENT, 'eventId': EVENT, 'bookingDate':'2026-10-05', 'description':'Example invoice 123',
            'transactionAmount':{'amount':amount,'currency':currency}, 'currencyAmount':{'amount':amount,'currency':currency},
            'debtor':{'accountNumber':'22222222222' if incoming else '11111111111'},
            'creditor':{'accountNumber':'11111111111' if incoming else '22222222222','name':'Example AS'}, 'attachments':[]}


def matches(monkeypatch, rows):
    monkeypatch.setattr(server, 'folio_list_transactions', lambda *a: {'transactions':{'booked':rows}})
    monkeypatch.setattr(server, 'folio_list_accounts', lambda: {'accounts':[{'accountNumber':'11111111111'}]})
    return server.folio_match_invoice('1250.00','NOK','2026-10-01','2026-10-15',supplier='Example',invoice_number='123')


def test_match_exact_decimal_and_event_id(monkeypatch):
    result=matches(monkeypatch,[row()])
    assert result['candidates'][0]['event_id']==EVENT
    assert result['candidates'][0]['rank_score']==3
    assert not result['ambiguous']


def test_no_wrong_currency_or_incoming_match(monkeypatch):
    result=matches(monkeypatch,[row(currency='EUR'),row(incoming=True),row(amount='1250.01')])
    assert not result['candidates'] and result['excluded_non_outgoing']==1


def test_equal_candidates_stay_ambiguous(monkeypatch):
    assert matches(monkeypatch,[row(),row()])['ambiguous']


@pytest.mark.parametrize('value',['NaN','Infinity','1250,00','1.001','1e3'])
def test_unsafe_money_rejected(value):
    with pytest.raises(auth.FolioError): server.money(value)


def test_invalid_or_unbounded_period():
    with pytest.raises(auth.FolioError): server.period('2026-02-30','2026-03-01')
    with pytest.raises(auth.FolioError): server.period('2020-01-01','2026-03-01')


def test_pdf_text_and_image(staged):
    data=staged[0].read_bytes()
    assert documents.read(data,'test')['pages']==1
    assert isinstance(documents.read(data,'test',as_image=True),documents.Image)
    with pytest.raises(auth.FolioError): documents.read(data,'test',page=2)


def test_attachment_ownership(monkeypatch):
    monkeypatch.setattr(server,'folio_get_event',lambda *a:{'event':{'attachments':[]}})
    with pytest.raises(auth.FolioError): server.folio_read_attachment(EVENT,ATTACHMENT)


def test_real_stdio():
    async def run():
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','folio_mcp.cli'])) as (reader,writer):
            async with ClientSession(reader,writer) as session:
                await session.initialize()
                tools={t.name:t for t in (await session.list_tools()).tools}
                assert len(tools)==12
                assert tools['folio_attach_invoice'].annotations.readOnlyHint is False
                assert not any('payment' in name or 'approve' in name for name in tools)
                result=await session.call_tool('folio_attach_invoice',{'proposal_id':'invalid'})
                assert result.isError
    asyncio.run(run())


def test_parallel_preparations_cannot_upload_same_file_twice(staged, monkeypatch):
    first = approved(monkeypatch, staged)
    second = approved(monkeypatch, staged)
    calls = []
    monkeypatch.setattr(client, 'upload_attachment', lambda *args: calls.append(args) or {'id': ATTACHMENT})
    assignments.attach(first)
    with pytest.raises(auth.FolioError): assignments.attach(second)
    assert len(calls) == 1


def test_success_without_attachment_id_is_unknown(staged, monkeypatch):
    plan_id = approved(monkeypatch, staged)
    monkeypatch.setattr(client, 'upload_attachment', lambda *args: {})
    with pytest.raises(auth.FolioError): assignments.attach(plan_id)
    assert assignments.load(plan_id)[2]['status'] == 'unknown'
