import time
import jsonlines
from claude_light import GreenMachine1

gm = GreenMachine1()

with open('gm.jsonl', 'a') as f:
    for g in [0, 0.5, 1.0]:
        for i in range(5):        
            d = {'G': g, 'result': gm(g), 'time': time.time()}
            f.write(d)
