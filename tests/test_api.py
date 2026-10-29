"""The public endpoints must keep the original Flask app's behavior."""

import base64
import sqlite3

from claude.instrument import CHANNELS


def test_api_shape(client):
    r = client.get('/api', params={'R': 0.12, 'G': 0.45, 'B': 1})
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {'in', 'out'}
    assert data['in'] == [0.12, 0.45, 1.0]
    assert list(data['out']) == CHANNELS
    assert all(isinstance(v, int) for v in data['out'].values())


def test_api_defaults_and_clamping(client):
    assert client.get('/api').json()['in'] == [0.0, 0.0, 0.0]
    assert client.get('/api?R=&G=&B=').json()['in'] == [0.0, 0.0, 0.0]
    assert client.get('/api?R=2&G=-1&B=0.5').json()['in'] == [1.0, 0.0, 0.5]


def test_api_bad_value(client):
    r = client.get('/api?R=abc')
    assert r.status_code == 400


def test_csv(client):
    r = client.get('/csv?G=0.5')
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/csv')
    assert int(r.text) > 0
    assert client.post('/csv?G=0.5').status_code == 200


def test_gm(client):
    assert client.get('/gm').status_code == 200
    r = client.post('/gm', data={'G': '0, 0.5,, 1'})
    assert r.status_code == 200
    assert r.text.count('<tr><td>') == 4
    csv = base64.b64decode(r.text.split('base64,')[1].split('"')[0]).decode()
    assert csv.splitlines()[0].startswith('0.0,')


def test_gm_bad_input(client):
    r = client.post('/gm', data={'G': '0, x'})
    assert 'error parsing your input' in r.text


def test_rgb(client):
    assert client.get('/rgb').status_code == 200
    r = client.post('/rgb', data={'R': '0.2', 'G': '', 'B': '1'})
    assert r.status_code == 200
    assert '515nm' in r.text


def test_session(client):
    client.post('/session', data={'G': '0.1'})
    r = client.post('/session', data={'G': '0.2'})
    assert r.text.count('<tr><td>') == 2
    r = client.get('/clear_session', follow_redirects=True)
    assert r.text.count('<tr><td>') == 0
    # Clearing an empty session is not an error.
    assert client.get('/clear_session').status_code in (200, 303)


def test_pages(client):
    for path in ['/', '/about', '/stats', '/statistics', '/health',
                 '/health/instrument', '/status']:
        assert client.get(path).status_code == 200, path


def test_measurements_recorded_without_ip(client, tmp_path):
    client.get('/api?G=0.5', headers={'X-Real-IP': '203.0.113.7'})
    client.app.state.store.flush()
    con = sqlite3.connect(tmp_path / 'test.db')
    row = con.execute('SELECT origin, G, ch515, ip_hash FROM measurements'
                      ).fetchone()
    assert row[0] == 'api' and row[1] == 0.5 and row[2] > 0
    assert row[3] and '203.0.113.7' not in row[3]
    dump = '\n'.join(con.iterdump())
    assert '203.0.113.7' not in dump


def test_stats_data(client):
    for g in (0.1, 0.2, 0.3):
        client.get(f'/api?G={g}')
    client.app.state.store.flush()
    data = client.get('/stats/data.json').json()
    assert data['totals']['experiments'] == 3
    assert data['totals']['users'] == 1
    assert sum(data['daily']['n']) == 3
    assert data['recent']['n'] == 3


def test_export(client):
    client.get('/api?G=0.5')
    client.app.state.store.flush()
    lines = client.get('/data/export.csv').text.splitlines()
    assert lines[0].startswith('t0,elapsed,origin,R,G,B,415nm')
    assert len(lines) == 2
