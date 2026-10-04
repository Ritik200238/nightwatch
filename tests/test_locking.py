import threading
import time

from nightwatch.api.locking import RequestFirstLock


def test_background_waits_for_a_waiting_request():
    lock = RequestFirstLock()
    order: list[str] = []
    request_in = threading.Event()

    def request() -> None:
        with lock:
            request_in.set()
            time.sleep(0.2)
            order.append("request")

    def warm() -> None:
        request_in.wait(2)
        with lock.background():
            order.append("warm")

    threads = [threading.Thread(target=request), threading.Thread(target=warm)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert order == ["request", "warm"]
    assert lock.wanted == 0


def test_request_queued_behind_warm_goes_next():
    """A request that arrives while one warm step runs goes before the next warm step."""
    lock = RequestFirstLock()
    order: list[str] = []
    step_running = threading.Event()
    request_queued = threading.Event()

    def warm() -> None:
        with lock.background():
            step_running.set()
            request_queued.wait(2)
            time.sleep(0.05)
            order.append("warm1")
        time.sleep(0.01)  # the warm loop moving to the next token
        with lock.background():
            order.append("warm2")

    def request() -> None:
        step_running.wait(2)
        request_queued.set()
        with lock:
            order.append("request")

    threads = [threading.Thread(target=warm), threading.Thread(target=request)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert order == ["warm1", "request", "warm2"]


def test_background_gives_up_waiting_after_max_wait():
    lock = RequestFirstLock()
    lock._wanted = 1  # a request that never finishes asking
    start = time.monotonic()
    with lock.background(max_wait_s=0.1):
        pass
    assert time.monotonic() - start < 1


def test_a_failed_request_still_releases():
    lock = RequestFirstLock()
    try:
        with lock:
            raise ValueError("boom")
    except ValueError:
        pass
    assert lock.wanted == 0
    with lock.background(max_wait_s=0.5):
        pass
