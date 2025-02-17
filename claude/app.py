import base64
import os
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, request, render_template, session, flash, redirect, make_response
from gpiozero import RGBLED 
import time
import board
from adafruit_as7341 import AS7341
import jsonlines
import matplotlib.pyplot as plt
import datetime
import pandas as pd
from retry import retry
import requests
import subprocess

i2c = board.I2C()  # uses board.SCL and board.SDA
sensor = AS7341(i2c)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

from dotenv import load_dotenv
load_dotenv()

app.secret_key = os.environ.get('CLAUDE_LIGHT_SECRET', 'claude-light')

import io
from picamera2 import Picamera2
pc = Picamera2()

# It seems like there could be some issues with concurrent requests that come
# too fast, resulting in GPIO busy errors. I only see this in Google sheets so
# far, where it seems all the requests come in at once. This adds a retry
# option. The numbers are all heuristic. I put a "largish" number of retries to
# avoid a potential infinite loop.
@retry(tries=50, delay=1)    
def measure(R, G, B, origin=None):
    """Perform a measurement at the RGB settings. Returns a dictionary of data
    that includes the measurements, inputs, time, elapsed time and remote ip
    address.

    origin is just a string indicating where the measure call came from.
    """
    t0 = time.time()
    
    led = RGBLED(red=19, green=13, blue=12)
    led.color = (R, G, B)
    
    data = list(sensor.all_channels) + [sensor.channel_clear, sensor.channel_nir]
    
    results = {        
        'in': [R, G, B],
        'out': {key:val for key, val in
                zip([
                    '415nm', '445nm', '480nm',
                    '515nm', '555nm', '590nm',
                    '630nm', '680nm', 'clear',
                    'nir'], data)}}

    led.color = (0, 0, 0)
    # I explicitly close so that it is clean to restart. Otherwise, it
    # seems like the gpio ports are in use and you have to
    # reboot. there might be some cli way to clear it, but I don't
    # know what it is.
    led.close()

    # I had to modify this when I started using nginx. That was making the
    # remote_addr all be 127.0.0.1. This seems to get a different IP than that.
    # I only want this as a way to track individual users, and see where in the
    # world they are from (see /statistics). This also required updating the
    # nginx conf. [[/etc/nginx/sites-available/claude-light.cheme.cmu.edu.conf]]
    ip = request.headers.get('X-Real-Ip', request.remote_addr)
    
    
    with jsonlines.open(os.path.expanduser('~/results.jsonl'), 'a') as f:
        d = results.copy()
        d.update({'t0': t0,
                  'elapsed_time': time.time() - t0,
                  'ip': ip,
                  'origin': origin})
        f.write(d)

    return results


@app.route('/')
def home():
    return redirect('https://github.com/jkitchin/claude-light?tab=readme-ov-file#Usage', code=302)


@app.route('/api')
def api():
    
    R = float(request.args.get('R') or 0)
    R = min(max(R, 0.0), 1.0)
    
    G = float(request.args.get('G') or 0)
    G = min(max(G, 0.0), 1.0)
    
    B = float(request.args.get('B') or 0)
    B = min(max(B, 0.0), 1.0)
    
    return measure(R, G, B, origin='api')

@app.route('/csv', methods=['GET', 'POST'])
def csv(G=0):
    """Return the 515nm result as a number.
    This function is for use in Google sheets.
    """
    
    G = float(request.args.get('G', 0))

    result = measure(0, G, 0)['out']['515nm']
    time.sleep(1)
    resp = make_response(str(result))
    resp.mimetype='text/csv'
    return resp

@app.route('/gm', methods=['GET', 'POST'])
def greenmachine1():
    """This is a form for browser use. It is not the most secure, and has none
    of the WTFform protections. It is unclear how much that matters.
    """
    
    if request.method == 'POST':
        try:
            Gs = [v.strip() or '0' for v in request.form['G'].split(',')]
            Gin = [min(max(float(x), 0.0), 1.0) for x in Gs]
        except ValueError:
            flash('There was an error parsing your input. Try again. Make sure they are proper floats separated by commas.')
            return render_template("green-machine1.html",                           
                                   data=())
        
        Gout = [measure(0, x, 0, origin='greenmachine1')['out']['515nm'] for x in Gin]

        output = list(zip(Gin, Gout))
        csv = '\n'.join([','.join([str(x) for x in row]) for row in output])
        b64 = base64.b64encode(csv.encode('utf-8')).decode("utf8")

        pc.start()
        data = io.BytesIO()
        pc.capture_file(data, format='png')
        imgb64 = base64.b64encode(data.getvalue()).decode('utf-8')

        
        return render_template("green-machine1.html",
                               data=output,
                               imgb64=imgb64,
                               b64=b64)
    # this is from GET
    return render_template("green-machine1.html",
                           imgb64=None,
                           data=())


@app.route('/rgb', methods=['GET', 'POST'])
def rgbmachine():
    """This is a form for browser use. It is not the most secure, and has none
    of the WTFform protections. It is unclear how much that matters.
    """
    
    if request.method == 'POST':        
        R = min(max(float(request.form['R'] or 0), 0.0), 1.0)
        G = min(max(float(request.form['G'] or 0), 0.0), 1.0)
        B = min(max(float(request.form['B'] or 0), 0.0), 1.0)

        out = measure(R, G, B, origin='rgb')['out']
        keys = ['R', 'G', 'B'] + list(out.keys())
        vals = [R, G, B] + list(out.values())
        
        csv = '\n'.join([','.join([str(x) for x in row]) for row in zip(keys, vals)])
        b64 = base64.b64encode(csv.encode('utf-8')).decode("utf8")

        # Get a picture
        led = RGBLED(red=19, green=18, blue=12)
        led.color = (R, G, B)
    

        pc.start()
        data = io.BytesIO()
        pc.capture_file(data, format='png')
        imgb64 = base64.b64encode(data.getvalue()).decode('utf-8')
    

        led.color = (0, 0, 0)
        # I explicitly close so that it is clean to restart. Otherwise, it
        # seems like the gpio ports are in use and you have to
        # reboot. there might be some cli way to clear it, but I don't
        # know what it is.
        led.close()
        
        return render_template("rgb.html",
                               keys=keys, vals=vals,
                               imgb64=imgb64,
                               RGB=(R,G,B),
                               b64=b64)
    # this is from GET
    return render_template("rgb.html",
                           RGB=(0, 0, 0),
                           imgb64=None,
                           data=())


@app.route('/about')
def about():
    return render_template("about.html")


@app.route('/session', methods=['GET', 'POST'])
def sesh():
    """This is a form for browser use. It is not the most secure, and has none
    of the WTFform protections. It is unclear how much that matters.
    """
    
    if request.method == 'POST':

        Gin = min(max(float(request.form['G'] or 0), 0.0), 1.0)
        Gout = measure(0, Gin, 0, origin='session')['out']['515nm']

        if 'ip' in session:
            session['ip'] += [[Gin, Gout]]
        else:
            session['ip'] =[[Gin, Gout]]

        csv = '\n'.join([','.join([str(x) for x in row]) for row in session['ip']])
        b64 = base64.b64encode(csv.encode('utf-8')).decode("utf8")

        return render_template("session.html", b64=b64)

    # this is from GET
    return render_template("session.html", b64=None)

@app.route('/clear_session')
def clear_sesh():
    del session['ip']
    return render_template("session.html")




@app.route('/statistics')
def stats():
    """Return some results on usage."""
    N = 0
    ips = set()

    timestamps = []
    elapsed_times = []
    with jsonlines.open(os.path.expanduser('~/results.jsonl')) as f:
        for entry in f:
            N += 1
            ips.add(entry.get('ip', None))
            timestamps += [datetime.datetime.fromtimestamp(entry['t0'])]
            elapsed_times += [entry['elapsed_time']]

    img = io.BytesIO()
    plt.plot(timestamps, elapsed_times, 'b.')
    plt.xlabel('time')
    plt.ylabel('Elapsed measurement time (sec)')
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(img, format='png')
    imgb64 = base64.b64encode(img.getvalue()).decode('utf-8')
    plt.close()

    counts = {}
    for ts in timestamps:
        m = (ts.year, ts.month, ts.day)
        if m in counts:
            counts[m] += 1
        else:
            counts[m] = 1

    plt.plot([datetime.datetime(*ts) for ts in counts],
             counts.values())
    plt.ylim([0, max(counts.values())])
    plt.xlabel('date')
    plt.ylabel('count')
    img = io.BytesIO()
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(img, format='png')
    plt.close()
    img2b64 = base64.b64encode(img.getvalue()).decode('utf-8')

    ips = list(set(ips))
    req = requests.post('https://ipinfo.io/tools/summarize-ips?cli=1',
                        data={'ips': ips})

#    try:
#        url = req.json()['reportUrl']
#    except:
#        url = "<error>"

    # [2024-10-05 Sat] this seems dumb, but I guess there is a limit of 1000 ips
    # in the API, but not when I run it this way. I hit 1000 IPs, and it seemed
    # to quit working
    with open(os.path.expanduser('~/ips'), 'w') as f:
        for ip in ips:
            f.write(f'{ip}\n')

    cmd = 'cat ~/ips | curl -s -XPOST --data-binary @- "ipinfo.io/tools/summarize-ips?cli=1" | jq .reportUrl'
    url = subprocess.check_output(cmd, shell=True, text=True)        
    

    return f'''<html><body>
    {N} experiments run by {len(ips)} users. <a href={url}>Map of IP addresses</a>
    <br>
    <br>
    <img src="data:image/png;base64, {imgb64}">
    <br>
    <br>
    <img src="data:image/png;base64, {img2b64}">

    </body>
    </html>'''


def run():
    """This is used to run the server."""
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
    
if __name__ == '__main__':
    run()
