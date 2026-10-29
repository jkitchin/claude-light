"""The instrument is used by one request at a time, and overload is rejected
quickly instead of piling up."""

import asyncio
import time

import pytest

from claude.instrument import (FakeInstrument, InstrumentService, QueueFull,
                               TooManyForIP)


def run(coro):
    return asyncio.run(coro)


def test_serialized():
    async def main():
        inst = FakeInstrument(delay=0.01)
        records = []
        s = InstrumentService(inst, maxsize=100, per_ip=100,
                              on_result=records.append)
        await s.start()
        results = await asyncio.gather(*[
            s.measure(0, i / 50, 0, 'api', f'10.0.0.{i}') for i in range(50)])
        await s.stop()
        return inst, results, records

    inst, results, records = run(main())
    assert inst.overlaps == 0
    assert len(results) == len(records) == 50
    # Results go back to the right caller.
    assert [r['in'][1] for r in results] == [i / 50 for i in range(50)]
    assert all(r['queue_wait'] >= 0 for r in records)


def test_queue_full_is_fast():
    async def main():
        s = InstrumentService(FakeInstrument(delay=0.05), maxsize=3, per_ip=100)
        await s.start()
        tasks = [asyncio.create_task(s.measure(0, 0, 0, 'api', 'first'))]
        await asyncio.sleep(0.01)  # the first job is now running
        tasks += [asyncio.create_task(s.measure(0, 0, 0, 'api', f'ip{i}'))
                  for i in range(3)]
        await asyncio.sleep(0)  # and 3 are queued
        t = time.time()
        with pytest.raises(QueueFull):
            await s.measure(0, 0, 0, 'api', 'late')
        rejected_in = time.time() - t
        await asyncio.gather(*tasks)
        await s.stop()
        return rejected_in

    assert run(main()) < 0.01


def test_per_ip_limit():
    async def main():
        s = InstrumentService(FakeInstrument(delay=0.05), maxsize=30, per_ip=2)
        await s.start()
        tasks = [asyncio.create_task(s.measure(0, 0, 0, 'api', 'same'))
                 for _ in range(2)]
        await asyncio.sleep(0)
        with pytest.raises(TooManyForIP):
            await s.measure(0, 0, 0, 'api', 'same')
        # A different client is still served.
        await s.measure(0, 0, 0, 'api', 'other')
        await asyncio.gather(*tasks)
        # Slots are released once jobs finish.
        await s.measure(0, 0, 0, 'api', 'same')
        await s.stop()

    run(main())


def test_timeout():
    async def main():
        s = InstrumentService(FakeInstrument(delay=0.2), maxsize=30, per_ip=30)
        await s.start()
        with pytest.raises(asyncio.TimeoutError):
            await s.measure(0, 0, 0, 'api', 'a', timeout=0.05)
        await s.stop()

    run(main())


def test_led_off_after_failure():
    class Broken(FakeInstrument):
        def read(self):
            raise RuntimeError('sensor unplugged')

    async def main():
        inst = Broken()
        s = InstrumentService(inst)
        await s.start()
        with pytest.raises(RuntimeError):
            await s.measure(1, 1, 1, 'api', 'a')
        await s.stop()
        return inst, s

    inst, s = run(main())
    assert inst.rgb == (0, 0, 0)
    assert s.last_ok is False
