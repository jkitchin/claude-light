"""The Claude-Light web server.

The URLs and response formats of /api, /csv, /gm, /rgb, /session and
/statistics are the same as the original Flask app, so existing scripts,
notebooks and spreadsheets keep working.
"""

import asyncio
import base64
import csv
import io
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import config
from .geo import Geo
from .instrument import (CHANNELS, FakeInstrument, HardwareInstrument,
                         InstrumentService, QueueFull, TooManyForIP)
from .stats import StatsCache
from .store import CH_COLS, Store, connect

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / 'templates')


def clamp(x):
    return min(max(float(x), 0.0), 1.0)


def to_csv(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator='\n').writerows(rows)
    return buf.getvalue()


def b64(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    return base64.b64encode(data).decode('utf-8')


def client_ip(request):
    # nginx sets X-Real-IP; without it we are being reached directly.
    return request.headers.get('x-real-ip') or request.client.host


def wants_html(request):
    return 'text/html' in request.headers.get('accept', '')


def create_app(instrument=None, db_path=None, geo_path=None):
    if not config.SECRET:
        raise RuntimeError('Set CLAUDE_LIGHT_SECRET in the environment or '
                           '.env (or CLAUDE_LIGHT_FAKE=1 for development).')
    if instrument is None:
        instrument = FakeInstrument(0.65) if config.FAKE else HardwareInstrument()
    db_path = Path(db_path or config.DB_PATH)

    @asynccontextmanager
    async def lifespan(app):
        store = Store(db_path, Geo(geo_path or config.GEO_DB), config.IP_SALT)
        store.start()
        service = InstrumentService(instrument, maxsize=config.QUEUE_MAX,
                                    per_ip=config.PER_IP_MAX,
                                    on_result=store.add)
        await service.start()
        app.state.store = store
        app.state.service = service
        app.state.stats = StatsCache(db_path, ttl=config.STATS_TTL)
        yield
        await service.stop()
        store.stop()

    app = FastAPI(title='Claude-Light', lifespan=lifespan, docs_url='/docs',
                  redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=config.SECRET,
                       same_site='lax')
    app.mount('/static', StaticFiles(directory=HERE / 'static'), name='static')

    def render(request, name, status_code=200, headers=None, **context):
        context.setdefault('messages', [])
        return templates.TemplateResponse(request, name, context,
                                          status_code=status_code,
                                          headers=headers)

    # ---- errors ------------------------------------------------------------

    def busy(request, status, message, retry_after):
        headers = {'Retry-After': str(retry_after)}
        if wants_html(request):
            return render(request, 'busy.html', status_code=status,
                          headers=headers, message=message,
                          retry_after=retry_after)
        return JSONResponse({'error': message}, status_code=status,
                            headers=headers)

    @app.exception_handler(QueueFull)
    async def queue_full(request, exc):
        return busy(request, 503, 'Claude-Light is busy. Please try again in '
                    'a few seconds.', 5)

    @app.exception_handler(asyncio.TimeoutError)
    async def timed_out(request, exc):
        return busy(request, 503, 'The measurement queue is long right now. '
                    'Please try again shortly.', 10)

    @app.exception_handler(TooManyForIP)
    async def too_many(request, exc):
        return busy(request, 429, 'You already have measurements waiting. '
                    'Please wait for them to finish.', 2)

    @app.exception_handler(ValueError)
    async def bad_value(request, exc):
        return JSONResponse({'error': 'R, G and B must be numbers from 0 to 1.'},
                            status_code=400)

    async def measure(request, R, G, B, origin, image=False):
        return await request.app.state.service.measure(
            R, G, B, origin, client_ip(request), image=image,
            timeout=config.TIMEOUT)

    # ---- the instrument API --------------------------------------------------

    @app.get('/api')
    async def api(request: Request, R: str = '', G: str = '', B: str = ''):
        """Measure at the given RGB settings (0 to 1). Returns
        {"in": [R, G, B], "out": {channel: counts}}."""
        result = await measure(request, clamp(R or 0), clamp(G or 0),
                               clamp(B or 0), 'api')
        return result

    @app.api_route('/csv', methods=['GET', 'POST'])
    async def csv_(request: Request, G: str = '0'):
        """The 515nm reading as plain text, for Google Sheets IMPORTDATA."""
        result = await measure(request, 0, clamp(G or 0), 0, 'csv')
        return PlainTextResponse(str(result['out']['515nm']),
                                 media_type='text/csv')

    # ---- browser pages -------------------------------------------------------

    @app.get('/', response_class=HTMLResponse)
    async def home(request: Request):
        return render(request, 'home.html')

    @app.get('/about', response_class=HTMLResponse)
    async def about(request: Request):
        return render(request, 'about.html')

    @app.get('/gm', response_class=HTMLResponse)
    async def gm_form(request: Request):
        return render(request, 'green-machine1.html', data=(), imgb64=None,
                      G='')

    @app.post('/gm', response_class=HTMLResponse)
    async def gm(request: Request, G: str = Form('')):
        try:
            Gin = [clamp(v.strip() or '0') for v in G.split(',')]
        except ValueError:
            return render(request, 'green-machine1.html', data=(),
                          imgb64=None, G=G, messages=[
                              'There was an error parsing your input. Try '
                              'again. Make sure they are proper floats '
                              'separated by commas.'])
        if len(Gin) > config.GM_MAX_POINTS:
            return render(request, 'green-machine1.html', data=(),
                          imgb64=None, G=G, messages=[
                              f'Please use at most {config.GM_MAX_POINTS} '
                              'values at a time.'])
        Gout, img = [], None
        for i, x in enumerate(Gin):
            last = i == len(Gin) - 1
            result = await measure(request, 0, x, 0, 'greenmachine1',
                                   image=last)
            Gout.append(result['out']['515nm'])
            img = result.get('image') if last else img
        output = list(zip(Gin, Gout))
        return render(request, 'green-machine1.html', data=output, G=G,
                      b64=b64(to_csv(output)),
                      imgb64=b64(img) if img else None)

    @app.get('/rgb', response_class=HTMLResponse)
    async def rgb_form(request: Request):
        return render(request, 'rgb.html', RGB=(0, 0, 0), imgb64=None)

    @app.post('/rgb', response_class=HTMLResponse)
    async def rgb(request: Request, R: str = Form(''), G: str = Form(''),
                  B: str = Form('')):
        R, G, B = clamp(R or 0), clamp(G or 0), clamp(B or 0)
        result = await measure(request, R, G, B, 'rgb', image=True)
        out = result['out']
        keys = ['R', 'G', 'B'] + list(out)
        vals = [R, G, B] + list(out.values())
        img = result.get('image')
        return render(request, 'rgb.html', RGB=(R, G, B), keys=keys,
                      vals=vals, out=out, b64=b64(to_csv(zip(keys, vals))),
                      imgb64=b64(img) if img else None)

    @app.get('/session', response_class=HTMLResponse)
    async def session_form(request: Request):
        return render(request, 'session.html',
                      rows=request.session.get('ip', []), b64=None)

    @app.post('/session', response_class=HTMLResponse)
    async def session(request: Request, G: str = Form('')):
        Gin = clamp(G or 0)
        result = await measure(request, 0, Gin, 0, 'session')
        rows = request.session.get('ip', []) + [[Gin, result['out']['515nm']]]
        request.session['ip'] = rows
        return render(request, 'session.html', rows=rows, b64=b64(to_csv(rows)))

    @app.get('/clear_session')
    async def clear_session(request: Request):
        request.session.pop('ip', None)
        return RedirectResponse('/session', status_code=303)

    # ---- statistics and data -------------------------------------------------

    @app.get('/statistics', response_class=HTMLResponse)
    @app.get('/stats', response_class=HTMLResponse)
    async def stats_page(request: Request):
        return render(request, 'stats.html')

    @app.get('/stats/data.json')
    async def stats_data(request: Request):
        data = await asyncio.to_thread(request.app.state.stats.get)
        return JSONResponse(data, headers={
            'Cache-Control': f'public, max-age={int(config.STATS_TTL)}'})

    @app.get('/status')
    async def status(request: Request):
        """Live instrument status: queue depth and the last measurement time."""
        s = request.app.state.service
        return {'busy': s.busy, 'queue': s.depth, 'last_t0': s.last_t0,
                'max_queue': s.maxsize}

    @app.get('/health')
    async def health():
        return {'ok': True}

    @app.get('/health/instrument')
    async def health_instrument(request: Request):
        """Reports on the most recent measurement; does not measure."""
        s = request.app.state.service
        ok = s.last_ok is not False
        return JSONResponse({'ok': ok, 'last_t0': s.last_t0},
                            status_code=200 if ok else 503)

    @app.get('/data/export.csv')
    async def export(since: float = Query(0, description='Unix time'),
                     until: float = Query(None, description='Unix time')):
        """Anonymized measurements as CSV (no IP addresses)."""
        cols = (['t0', 'elapsed', 'origin', 'R', 'G', 'B'] + CH_COLS
                + ['ip_hash', 'country', 'country_name', 'region', 'city'])
        header = (['t0', 'elapsed', 'origin', 'R', 'G', 'B'] + CHANNELS
                  + ['user', 'country', 'country_name', 'region', 'city'])

        def rows():
            con = connect(db_path, readonly=True)
            try:
                cur = con.execute(
                    f'SELECT {", ".join(cols)} FROM measurements '
                    'WHERE t0 >= ? AND t0 < ? ORDER BY t0',
                    (since, until if until is not None else time.time() + 1))
                yield to_csv([header])
                while chunk := cur.fetchmany(5000):
                    yield to_csv(chunk)
            finally:
                con.close()

        return StreamingResponse(rows(), media_type='text/csv', headers={
            'Content-Disposition': 'attachment; filename="claude-light.csv"'})

    return app


def run():
    """Entry point for the `claude-light` command (used by systemd)."""
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host='127.0.0.1', port=8000,
                proxy_headers=True, forwarded_allow_ips='127.0.0.1')


if __name__ == '__main__':
    run()
