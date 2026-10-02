import time
from contextlib import contextmanager


class Timings(dict):
    """Per-request stage timings in ms. Usage: with t.stage('encode'): ..."""

    @contextmanager
    def stage(self, name):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self[name] = round(self.get(name, 0) + (time.perf_counter() - t0) * 1000, 1)

    def total(self):
        return round(sum(self.values()), 1)
