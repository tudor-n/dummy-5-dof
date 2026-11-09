"""Offline serial-handshake tests - no arm, no port required.

Run with:  python test_serial.py        (or: pytest test_serial.py)

connect_serial() runs against a fake port that plays back what a real ESP32 sent when the arm was
hot-plugged: junk and watchdog reports first, the state reply somewhere inside them, or nothing.
"""
import time

import server as S


class FakePort:
    """Plays chunks back from read(); `answer` is appended after the first GET once `delay` has passed."""
    def __init__(self, chunks=(), answer=b"", delay=0.0):
        self.chunks = list(chunks); self.answer = answer; self.delay = delay
        self.t0 = time.time(); self.writes = []; self.closed = False; self.sent = False

    def read(self, n):
        if self.closed: raise OSError("closed")
        if self.chunks: return self.chunks.pop(0)
        if self.answer and not self.sent and b"GET\n" in self.writes and time.time() - self.t0 >= self.delay:
            self.sent = True; return self.answer
        time.sleep(0.01); return b""

    def write(self, b): self.writes.append(b)
    def close(self): self.closed = True


def connect(fake, wait=3.0):
    real = S.serial.Serial
    S.serial.Serial = lambda *a, **k: fake
    try: return S.connect_serial("/dev/fake", wait=wait)
    finally: S.serial.Serial = real


REPLY = b"S 90.0 16.0 10.0 72.0 90.0 100.0 E0\n"
WDT = (b"E (35318) task_wdt: Task watchdog got triggered. The following tasks/users did not reset the watchdog in time:\r\n"
       b"E (35318) task_wdt:  - IDLE0 (CPU 0)\r\n" + b"0x400D150F:0x3FFB4530\r\n\r\n" * 200)


def test_parse_state_finds_the_reply_inside_junk():
    buf = b"\xf0p\x80\x0c|\x8c" * 300 + WDT + b"S 1.5 -2.0 3 4 5 6 E1\n" + WDT
    assert S.parse_state(buf) == ([1.5, -2.0, 3.0, 4.0, 5.0, 6.0], True)


def test_parse_state_ignores_a_cut_off_reply():
    assert S.parse_state(b"S 90.0 16.0 10.0 72.0 90.0 10") is None
    assert S.parse_state(b"no reply here\n") is None


def test_parse_state_takes_the_latest_reply():
    assert S.parse_state(REPLY + b"S 1 2 3 4 5 6 E1\r\n")[0] == [1, 2, 3, 4, 5, 6]


def test_handshake_survives_a_flood_before_the_reply():
    fake = FakePort(chunks=[b"\xf0p\x80\x0c" * 1000] * 30 + [WDT] * 10, answer=WDT[:300] + REPLY + WDT[:300])
    ser, pose = connect(fake)
    assert ser is fake and pose == [90.0, 16.0, 10.0, 72.0, 90.0, 100.0]
    assert S.S.engaged is False
    fake.close()                          # stops the background reader


def test_handshake_waits_for_a_late_answer_and_resends_get():
    fake = FakePort(answer=b"S 1 2 3 4 5 6 E1\n", delay=1.2)
    ser, pose = connect(fake)
    assert pose == [1, 2, 3, 4, 5, 6] and S.S.engaged is True
    assert fake.writes.count(b"GET\n") >= 2
    fake.close()


def test_no_answer_closes_the_port_and_reports_none():
    fake = FakePort(chunks=[WDT] * 5)
    t = time.time()
    assert connect(fake, wait=1.0) == (None, None)
    assert fake.closed and time.time() - t < 2.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)
