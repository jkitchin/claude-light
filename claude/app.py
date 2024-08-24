#!/home/jkitchin/claude-light/.venv/bin/python

import base64
import os
from flask import Flask, request, render_template
from gpiozero import RGBLED 
import time
import board
from adafruit_as7341 import AS7341
import jsonlines

i2c = board.I2C()  # uses board.SCL and board.SDA
sensor = AS7341(i2c)

app = Flask(__name__)

import io
from picamera2 import Picamera2
pc = Picamera2()

    
def measure(R, G, B):
    """Perform a measurement at the RGB settings. Returns a dictionary of data
    that includes the measurements, inputs, time, elapsed time and remote ip
    address.

    """
    t0 = time.time()
    led = RGBLED(red=19, green=18, blue=12)
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
    
    with jsonlines.open(os.path.expanduser('~/results.jsonl'), 'a') as f:
        d = results.copy()
        d.update({'t0': t0,
                  'elapsed_time': time.time() - t0,
                  'ip': request.remote_addr})
        f.write(d)

    return results
    
@app.route('/')
def rgb():
    
    R = float(request.args.get('R') or 0)
    R = min(max(R, 0.0), 1.0)
    
    G = float(request.args.get('G') or 0)
    G = min(max(G, 0.0), 1.0)
    
    B = float(request.args.get('B') or 0)
    B = min(max(B, 0.0), 1.0)
    
    return measure(R, G, B)

@app.route('/gm', methods=['GET', 'POST'])
def greenmachine1():
    """This is a form for browser use. It is not the most secure, and has none
    of the WTFform protections. It is unclear how much that matters.
    """
    
    if request.method == 'POST':
        Gs = [v.strip() or '0' for v in request.form['G'].split(',')]
        Gin = [min(max(float(x), 0.0), 1.0) for x in Gs]
        Gout = [measure(0, x, 0)['out']['515nm'] for x in Gin]

        output = list(zip(Gin, Gout))
        csv = '\n'.join([','.join([str(x) for x in row]) for row in output])
        b64 = base64.b64encode(csv.encode('utf-8')).decode("utf8")
        
        return render_template("green-machine1.html",
                               data=output,
                               b64=b64)
    # this is from GET
    return render_template("green-machine1.html",                           
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

        out = measure(R, G, B)['out']
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
                           data=())


@app.route('/about')
def about():
    return render_template("about.html")


@app.route('/img')
def img():
    pc.start()
    data = io.BytesIO()
    pc.capture_file(data, format='png')
    b64 = base64.b64encode(data.getvalue()).decode('utf-8')
    return f'<img src="data:image/png;base64, {b64}">'


@app.route('/statistics')
def stats():
    """Return some results on usage."""
    N = 0
    ips = set()
    with jsonlines.open(os.path.expanduser('~/results.jsonl')) as f:
        for entry in f:
            N += 1
            ips.add(entry.get('ip', None))

    return f'{N} experiments run by {len(ips)} users.'


def run():
    """This is used to run the server."""
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
    
if __name__ == '__main__':
    run()
