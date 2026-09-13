"""Persistent, local Start/Stop monitor service.

The Streamlit UI starts this module in a separate Python process.  It runs an
initial sweep immediately, then polls on a bounded interval.  State is stored
in a small local JSON file so the UI can display progress even after its own
process has rerun or the browser has been refreshed.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from submission.config import config


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _state_path() -> Path:
    path = Path(config.monitor_state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _default_state() -> dict[str, Any]:
    return {
        "desired_running": False,
        "running": False,
        "pid": None,
        "warehouse_id": None,
        "interval_seconds": config.monitor_interval_seconds,
        # Stable monitor-session start time.  This is distinct from
        # last_started_at, which changes at the beginning of every sweep.
        "monitor_started_at": None,
        "started_at": None,
        "last_started_at": None,
        "last_completed_at": None,
        "next_run_at": None,
        "last_result": None,
        "last_error": None,
        "stopped_at": None,
    }


def _read_state() -> dict[str, Any]:
    path = _state_path()
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        saved = {}
    return {**_default_state(), **saved}


def _write_state(state: dict[str, Any]) -> dict[str, Any]:
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return state


def _process_is_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    return True


def get_monitor_status() -> dict[str, Any]:
    """Return persisted state, marking a dead worker as stopped for the UI."""
    state = _read_state()
    if state["running"] and not _process_is_alive(state.get("pid")):
        state.update({
            "desired_running": False,
            "running": False,
            "pid": None,
            "next_run_at": None,
            "stopped_at": _timestamp(),
            "last_error": state.get("last_error") or "Monitor process stopped unexpectedly.",
        })
        _write_state(state)
    return state


def start_monitor(warehouse_id: str | None = None, interval_seconds: int | None = None) -> tuple[dict[str, Any], bool]:
    """Start one local worker, returning (state, started_new_worker)."""
    state = get_monitor_status()
    if state["desired_running"] and _process_is_alive(state.get("pid")):
        return state, False

    interval = max(30, int(interval_seconds or config.monitor_interval_seconds))
    started_at = _timestamp()
    state.update({
        "desired_running": True,
        "running": False,
        "pid": None,
        "warehouse_id": warehouse_id,
        "interval_seconds": interval,
        "monitor_started_at": started_at,
        "started_at": started_at,
        "last_started_at": None,
        "last_completed_at": None,
        "next_run_at": _timestamp(),
        "last_result": None,
        "last_error": None,
        "stopped_at": None,
    })
    _write_state(state)

    command = [sys.executable, "-m", "submission.monitor.service", "--worker", "--interval", str(interval)]
    if warehouse_id:
        command.extend(["--warehouse", warehouse_id])
    kwargs: dict[str, Any] = {
        "cwd": str(Path(__file__).resolve().parents[2]),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(command, **kwargs)
    state = _read_state()
    state["pid"] = process.pid
    _write_state(state)
    return state, True


def stop_monitor() -> dict[str, Any]:
    """Request a graceful stop; a scan already in progress is allowed to finish."""
    state = _read_state()
    state["desired_running"] = False
    state["next_run_at"] = None
    state["stopped_at"] = _timestamp()
    _write_state(state)
    return state


def restart_monitor(warehouse_id: str | None = None, interval_seconds: int | None = None) -> tuple[dict[str, Any], bool]:
    """Replace the currently recorded local worker with code from disk.

    Streamlit's reload only replaces the web process; the monitor deliberately
    survives it.  This explicit control is therefore the safe, visible way to
    apply an application update to a running monitor.  It targets only the PID
    recorded in this monitor's state file and refuses to launch a second worker
    if that exact process cannot be stopped.
    """
    state = get_monitor_status()
    old_pid = state.get("pid")
    if old_pid and _process_is_alive(old_pid):
        state.update({"desired_running": False, "next_run_at": None, "stopped_at": _timestamp()})
        _write_state(state)
        try:
            os.kill(int(old_pid), signal.SIGTERM)
        except OSError as exc:
            raise RuntimeError(f"Could not stop the recorded monitor worker (PID {old_pid}): {exc}") from exc

        deadline = time.monotonic() + 10
        while _process_is_alive(old_pid) and time.monotonic() < deadline:
            time.sleep(0.1)
        if _process_is_alive(old_pid):
            raise RuntimeError(
                f"Monitor worker PID {old_pid} did not stop; no replacement was started to avoid duplicate sweeps."
            )

    state = _read_state()
    if state.get("pid") == old_pid:
        state.update({"running": False, "pid": None, "next_run_at": None})
        _write_state(state)
    return start_monitor(warehouse_id, interval_seconds)


def _result_summary(run) -> dict[str, Any]:
    return {
        "sweep_id": run.sweep_id,
        "pairs_examined": run.pairs_examined,
        "candidates_found": run.candidates_found,
        "parked_count": run.parked_count,
        "deferred_for_budget_count": run.deferred_for_budget_count,
        "cases_opened": run.cases_opened,
        "reminders_sent": run.reminders_sent,
    }


def run_worker(warehouse_id: str | None, interval_seconds: int) -> None:
    """Run immediately, then wait in one-second increments for a graceful stop."""
    worker_pid = os.getpid()
    interval = max(30, int(interval_seconds))
    try:
        while True:
            state = _read_state()
            if not state.get("desired_running"):
                break
            state.update({
                "running": True,
                "pid": worker_pid,
                "warehouse_id": warehouse_id,
                "interval_seconds": interval,
                "last_started_at": _timestamp(),
                "next_run_at": None,
                "last_error": None,
            })
            _write_state(state)
            try:
                from submission.app import run_sweep

                result = run_sweep(warehouse_id)
                state = _read_state()
                state["last_result"] = _result_summary(result)
                state["last_completed_at"] = _timestamp()
            except Exception as exc:  # A later poll is safer than a crashed monitor.
                state = _read_state()
                state["last_error"] = f"{type(exc).__name__}: {exc}"
                state["last_completed_at"] = _timestamp()

            next_run = _now() + timedelta(seconds=interval)
            state.update({"running": True, "pid": worker_pid, "next_run_at": _timestamp(next_run)})
            _write_state(state)

            for _ in range(interval):
                time.sleep(1)
                if not _read_state().get("desired_running"):
                    break
            if not _read_state().get("desired_running"):
                break
    finally:
        state = _read_state()
        # Do not revive a newer worker if one was started after this process.
        if state.get("pid") == worker_pid:
            state.update({"running": False, "pid": None, "next_run_at": None})
            _write_state(state)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventra continuous local monitor")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--warehouse")
    parser.add_argument("--interval", type=int, default=config.monitor_interval_seconds)
    args = parser.parse_args()
    if not args.worker:
        parser.error("This module is launched by the Agent Console; use --worker.")
    run_worker(args.warehouse, args.interval)


if __name__ == "__main__":
    main()
