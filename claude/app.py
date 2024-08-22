#!/home/jkitchin/claude-light/.venv/bin/python

import os
from flask import Flask, request, jsonify, render_template
from gpiozero import RGBLED 
import time
import board
from adafruit_as7341 import AS7341
import jsonlines

i2c = board.I2C()  # uses board.SCL and board.SDA
sensor = AS7341(i2c)

app = Flask(__name__)


def measure(R, G, B):
    t0 = time.time()
    led = RGBLED(red=19, green=18, blue=12)
    led.color = (R, G, B)
    
    data = sensor.all_channels
    
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
    
    return jsonify(measure(R, G, B))

@app.route('/gm', methods=['GET', 'POST'])
def greenmachine1():
    """This is a form for browser use. It is not the most secure, and has none
    of the WTFform protections. It is unclear how much that matters.
    """
    data = None
    if request.method == 'POST':
        G = G = min(max(float(request.form['G']) / 100, 0.0), 1.0)
        data = measure(0, G, 0)
        green = data['out']['515nm']
    return render_template("green-machine1.html",
                           value=G * 100,
                           Ginput=G,
                           data=green)

def run():
    """This is used to run the server."""
    from waitress import serve
    serve(app, host='0.0.0.0', port=5000)
    
if __name__ == '__main__':
    run()
