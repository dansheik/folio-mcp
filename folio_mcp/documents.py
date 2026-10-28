"""In-memory PDF/image reading; document content is untrusted data."""
import io
from contextlib import closing
from pathlib import Path
from mcp.server.fastmcp import Image
from pypdf import PdfReader
from .auth import FolioError
from .client import MAX_BYTES


def file_data(path):
    file = Path(path).expanduser().resolve(strict=True)
    if not file.is_file() or file.stat().st_size > MAX_BYTES:
        raise FolioError('Velg en PDF, PNG eller JPEG på maks 15 MiB.')
    with file.open('rb') as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise FolioError('Filen er for stor.')
    return data, mime_type(data), file.name


def mime_type(data):
    if data.startswith(b'%PDF-'): return 'application/pdf'
    if data.startswith(b'\x89PNG\r\n\x1a\n'): return 'image/png'
    if data.startswith(b'\xff\xd8\xff'): return 'image/jpeg'
    raise FolioError('Kun PDF, PNG og JPEG støttes.')


def read(data, source, page=1, as_image=False):
    if page < 1: raise FolioError('Sider starter på 1.')
    mime = mime_type(data)
    if mime != 'application/pdf':
        if page != 1: raise FolioError('Bilder har én side.')
        return Image(data=data, format='png' if mime == 'image/png' else 'jpeg')
    try:
        if as_image:
            import pypdfium2 as pdfium
            with closing(pdfium.PdfDocument(data)) as pdf:
                if page > len(pdf): raise FolioError('Siden finnes ikke.')
                with closing(pdf[page-1]) as pdf_page:
                    width, height = pdf_page.get_size()
                    with closing(pdf_page.render(scale=min(1.5, 2000/max(width, height)))) as bitmap:
                        out = io.BytesIO(); bitmap.to_pil().save(out, format='PNG')
                        return Image(data=out.getvalue(), format='png')
        pdf = PdfReader(io.BytesIO(data))
        if page > len(pdf.pages): raise FolioError('Siden finnes ikke.')
        text = pdf.pages[page-1].extract_text() or ''
        return {'source': source, 'page': page, 'pages': len(pdf.pages), 'text': text[:40000],
                'truncated': len(text)>40000, 'untrusted_document': True,
                'next_step': 'Les alle sider. Bruk as_image=true ved skannet/uklar PDF.'}
    except FolioError: raise
    except Exception:
        raise FolioError('PDF-en kunne ikke leses.') from None
