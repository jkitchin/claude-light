"""The physical instrument and the queue that serializes access to it.

There is one LED, one sensor and one camera, so every measurement goes through
a single worker thread. Web requests wait on an asyncio future, which is cheap,
instead of holding a server thread while they retry for the GPIO pins.
"""

import asyncio
import io
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

CHANNELS = ['415nm', '445nm', '480nm', '515nm', '555nm',
            '590nm', '630nm', '680nm', 'clear', 'nir']

# BCM pin numbers for the RGB LED.
PINS = dict(red=19, green=13, blue=12)


class HardwareInstrument:
    """The real LED, AS7341 sensor and Pi camera. Imports are deferred so the
    package can be imported on machines without the hardware libraries."""

    def open(self):
        import board
        from adafruit_as7341 import AS7341
        from gpiozero import RGBLED
        from picamera2 import Picamera2

        self.sensor = AS7341(board.I2C())
        self.led = RGBLED(**PINS)
        self.camera = Picamera2()
        self.camera.configure(
            self.camera.create_still_configuration(main={'size': (640, 480)}))
        self.camera.start()

    def close(self):
        self.led.color = (0, 0, 0)
        # Closing releases the GPIO pins so a restart does not need a reboot.
        self.led.close()
        self.camera.stop()
        self.camera.close()

    def set_led(self, R, G, B):
        self.led.color = (R, G, B)

    def read(self):
        data = list(self.sensor.all_channels) + [self.sensor.channel_clear,
                                                 self.sensor.channel_nir]
        return dict(zip(CHANNELS, data))

    def capture(self):
        buf = io.BytesIO()
        self.camera.capture_file(buf, format='jpeg')
        return buf.getvalue()


class FakeInstrument:
    """A stand-in for development and tests. `delay` mimics the ~0.65 s
    measurement time. `busy` lets tests check that access is serialized."""

    def __init__(self, delay=0.0):
        self.delay = delay
        self.rgb = (0, 0, 0)
        self.busy = False
        self.overlaps = 0

    def open(self):
        pass

    def close(self):
        pass

    def set_led(self, R, G, B):
        self.rgb = (R, G, B)

    def read(self):
        if self.busy:
            self.overlaps += 1
        self.busy = True
        try:
            time.sleep(self.delay)
            R, G, B = self.rgb
            base = [1, 2, 3, 5, 7, 6, 9, 6, 45, 19]
            gain = [B, B, B + G, G, G, G + R, R, R, R + G + B, R]
            return {c: int(100 * b + 30000 * g * (1 + 0.01 * random.random()))
                    for c, b, g in zip(CHANNELS, base, gain)}
        finally:
            self.busy = False

    def capture(self):
        return b''


class QueueFull(Exception):
    """The instrument queue is full; try again later."""


class TooManyForIP(Exception):
    """This client already has the maximum number of queued measurements."""


@dataclass
class Job:
    R: float
    G: float
    B: float
    origin: str
    ip: str
    image: bool = False
    t_queued: float = field(default_factory=time.time)
    future: asyncio.Future = None


class InstrumentService:
    """Owns the instrument and processes jobs one at a time, in order.

    `on_result(record)` is called (in the worker thread) after each
    measurement, with the same fields the old results.jsonl had plus
    `queue_wait`.
    """

    def __init__(self, instrument, maxsize=30, per_ip=3, on_result=None):
        self.instrument = instrument
        self.maxsize = maxsize
        self.per_ip = per_ip
        self.on_result = on_result
        self.queue = None
        self.per_ip_count = {}
        self.busy = False
        self.last_t0 = None
        self.last_ok = None
        self._executor = ThreadPoolExecutor(max_workers=1,
                                            thread_name_prefix='instrument')
        self._task = None

    @property
    def depth(self):
        return (self.queue.qsize() if self.queue else 0) + int(self.busy)

    async def start(self):
        self.queue = asyncio.Queue(maxsize=self.maxsize)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self.instrument.open)
        self._task = asyncio.create_task(self._worker())

    async def stop(self):
        if self._task:
            self._task.cancel()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self.instrument.close)
        self._executor.shutdown(wait=True)

    async def measure(self, R, G, B, origin, ip, image=False, timeout=None):
        """Queue a measurement and wait for it. Returns a dict with 'in',
        'out' and, if image is True, 'image' (JPEG bytes)."""
        if self.per_ip_count.get(ip, 0) >= self.per_ip:
            raise TooManyForIP(ip)
        job = Job(R, G, B, origin, ip, image,
                  future=asyncio.get_running_loop().create_future())
        try:
            self.queue.put_nowait(job)
        except asyncio.QueueFull:
            raise QueueFull()
        self.per_ip_count[ip] = self.per_ip_count.get(ip, 0) + 1
        # On timeout the job still runs (and is recorded); the client just
        # stops waiting. The per-IP slot is released when the job finishes.
        return await asyncio.wait_for(asyncio.shield(job.future), timeout)

    def _release(self, ip):
        n = self.per_ip_count.get(ip, 1) - 1
        if n <= 0:
            self.per_ip_count.pop(ip, None)
        else:
            self.per_ip_count[ip] = n

    async def _worker(self):
        loop = asyncio.get_running_loop()
        while True:
            job = await self.queue.get()
            self.busy = True
            try:
                result = await loop.run_in_executor(self._executor,
                                                    self._run, job)
                if not job.future.done():
                    job.future.set_result(result)
                self.last_ok = True
            except Exception as e:
                log.exception('measurement failed')
                self.last_ok = False
                if not job.future.done():
                    job.future.set_exception(e)
            finally:
                self.busy = False
                self._release(job.ip)
                self.queue.task_done()

    def _run(self, job):
        """Runs in the instrument thread."""
        t0 = time.time()
        inst = self.instrument
        out = None
        try:
            inst.set_led(job.R, job.G, job.B)
            # Occasional I2C hiccups are retried a couple of times; anything
            # persistent is a real fault and should surface.
            for attempt in range(3):
                try:
                    out = inst.read()
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    time.sleep(0.1)
            image = inst.capture() if job.image else None
        finally:
            inst.set_led(0, 0, 0)

        self.last_t0 = t0
        result = {'in': [job.R, job.G, job.B], 'out': out}
        if self.on_result:
            try:
                self.on_result({**result,
                                't0': t0,
                                'elapsed_time': time.time() - t0,
                                'queue_wait': t0 - job.t_queued,
                                'ip': job.ip,
                                'origin': job.origin})
            except Exception:
                log.exception('could not record result')
        if image is not None:
            result['image'] = image
        return result
