"""Real-process recovery checks; children write only inside pytest temp dirs."""
import os
import json
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]


def test_forced_child_termination_reopens_committed_sqlite_rows(tmp_path):
    record = tmp_path / "meeting.json"
    ready = tmp_path / "ready.txt"
    child = r'''
import sys, time, os, json
from app.meeting_store import MeetingStore
record, ready = sys.argv[1:]
store = MeetingStore(record, {"meeting_id": "forced-exit"})
store.upsert([{"id": str(i), "start": i / 4, "source": f"row-{i}",
               "native": {"speaker": i % 2, "words": []}} for i in range(4000)])
store.checkpoint({"status": "active"})
open(ready, "w", encoding="utf-8").write(json.dumps({"committed": True, "pid": os.getpid()}))
while True:
    time.sleep(1)
'''
    process = subprocess.Popen([sys.executable, "-c", child, str(record), str(ready)],
                               cwd=ROOT, env={**os.environ, "PYTHONUTF8": "1"},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 30
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        if not ready.exists():
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(f"child failed before checkpoint: {stdout!r} {stderr!r}")

        # Windows venv launchers may own a separate runtime process. Kill the
        # actual writer, rather than only its launcher and orphaning the DB.
        import psutil
        writer_pid=json.loads(ready.read_text(encoding='utf-8'))['pid']
        psutil.Process(writer_pid).kill()
        process.wait(timeout=10)
        from app.meeting_store import load_meeting
        loaded = load_meeting(record)

        assert process.returncode != 0
        assert loaded["row_count"] == 4000
        assert len(loaded["rows"]) == 4000
        assert loaded["rows"][0]["source"] == "row-0"
        assert loaded["rows"][-1]["source"] == "row-3999"
        assert loaded["recovered"] is True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
