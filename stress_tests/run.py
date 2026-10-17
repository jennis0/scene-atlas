"""CLI entry point, server lifecycle management, and results collection.

Usage:
    python -m stress_tests run --all
    python -m stress_tests run --scenario concurrent-imports
    python -m stress_tests run --scenario concurrent-imports --quick
    python -m stress_tests run --all --large
    python -m stress_tests generate-fixtures
    python -m stress_tests list
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO

import httpx

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
STRESS_DIR = Path(__file__).parent
FIXTURES_DIR = STRESS_DIR / ".fixtures"
RESULTS_DIR = STRESS_DIR / "results"
# ONNX models are a download cache shared by every stress server (linked into each
# server's isolated APP_DATA_DIR). Override with STRESS_MODELS_DIR.
MODELS_DIR = Path(os.environ.get("STRESS_MODELS_DIR", REPO_ROOT / "data" / "models"))

# ---------------------------------------------------------------------------
# ANSI colours (disabled on Windows without ANSI support, or in non-TTY)
# ---------------------------------------------------------------------------

_USE_COLOUR = (sys.stdout.isatty() and sys.platform != "win32") or (
    sys.platform == "win32" and os.environ.get("TERM") == "xterm"
)


def _green(s: str) -> str:
    return f"\033[92m{s}\033[0m" if _USE_COLOUR else s


def _red(s: str) -> str:
    return f"\033[91m{s}\033[0m" if _USE_COLOUR else s


def _yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m" if _USE_COLOUR else s


def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m" if _USE_COLOUR else s


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class RequestStats:
    """Aggregate metrics for a batch of HTTP requests within a scenario."""

    count: int = 0
    errors: int = 0
    times: list[float] = field(default_factory=list)

    def record(self, elapsed: float, ok: bool) -> None:
        self.count += 1
        self.times.append(elapsed)
        if not ok:
            self.errors += 1

    def _percentile(self, p: float) -> float | None:
        if not self.times:
            return None
        sorted_times = sorted(self.times)
        idx = int(len(sorted_times) * p / 100)
        return sorted_times[min(idx, len(sorted_times) - 1)]

    @property
    def p50(self) -> float | None:
        return self._percentile(50)

    @property
    def p95(self) -> float | None:
        return self._percentile(95)

    @property
    def p99(self) -> float | None:
        return self._percentile(99)

    def summary_str(self) -> str:
        parts = [f"{self.count} requests, {self.errors} errors"]
        if self.p50 is not None:
            parts.append(f"p50={self.p50:.2f}s p95={self.p95:.2f}s")
        return ", ".join(parts)


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    message: str
    elapsed: float
    stats: RequestStats | None = None
    failure_details: str | None = None


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------


def _link_dir(source: Path, dest: Path) -> None:
    """Link ``dest`` to the directory ``source`` (a junction on Windows if symlinks need admin)."""
    try:
        os.symlink(source, dest, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(source), str(dest))


class StressTestServer:
    """Manages a uvicorn subprocess with isolated storage.

    The backend's storage roots are APP_DATA_DIR and IMAGE_LIBRARY_DIR
    (backend/app/config.py); without them it would use the repo's ./data and
    ./images. Both are set to ``{storage_dir}/data`` and ``{storage_dir}/images``.
    """

    def __init__(self, work_dir: Path, *, storage_dir: Path | None = None) -> None:
        self.work_dir = work_dir
        self.log_path = work_dir / "server.log"
        # Callers can share storage across restarts (server_restart_recovery).
        self.storage_dir = storage_dir if storage_dir is not None else work_dir
        self.data_dir = self.storage_dir / "data"
        self.library_dir = self.storage_dir / "images"
        self.port: int | None = None
        self.base_url: str | None = None
        self._proc: subprocess.Popen | None = None
        self._log_fh: IO | None = None
        self._port_sock: socket.socket | None = None  # held until uvicorn binds

    def _reserve_port(self) -> int:
        """Bind to port 0, record the assigned port, and hold the socket open.

        The socket is kept in self._port_sock to prevent OS port reuse until
        uvicorn has actually bound the port.  Both sockets use SO_REUSEADDR so
        uvicorn can bind the same address without conflict.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        self._port_sock = s
        return port

    def start(self, timeout: float = 90) -> str:
        """Start the server and wait for it to signal readiness.

        The server prints ``SCENE_ATLAS_READY port=N`` to stdout once the DB,
        vector store and job runner are up.  We capture that line as our ready signal
        then drain remaining stdout to the log file.

        Returns the base URL, e.g. ``http://127.0.0.1:18423``.
        """
        self.port = self._reserve_port()
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.library_dir.mkdir(parents=True, exist_ok=True)
        models_link = self.data_dir / "models"
        if not models_link.exists() and MODELS_DIR.is_dir():
            _link_dir(MODELS_DIR.resolve(), models_link)

        env = os.environ.copy()
        env["APP_DATA_DIR"] = str(self.data_dir)
        env["IMAGE_LIBRARY_DIR"] = str(self.library_dir)
        env["API_PORT"] = str(self.port)
        # DEBUG=true enables debug-level logging in the server
        env["DEBUG"] = "true"
        env["PYTHONUNBUFFERED"] = "1"

        # Disable scheduled maintenance tasks during stress tests — they run every
        # 6h+ anyway and won't fire, but the scheduler_interference scenario
        # will enable them explicitly by patching the scheduler interval.
        # We keep the scheduler *running* so the interference scenario works.

        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        # Held open for the server's lifetime; closed in stop().
        self._log_fh = open(self.log_path, "w", encoding="utf-8", errors="replace")  # noqa: SIM115

        # Run uvicorn with this interpreter (the project venv under `uv run`), not via
        # `uv run`: SIGKILL can't be forwarded through the uv wrapper, so a "killed"
        # server kept running and raced its replacement on the same storage.
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
        ]

        kwargs: dict = {}
        if sys.platform == "win32":
            # CREATE_NEW_PROCESS_GROUP allows us to kill the entire process tree
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            # Own process group, so stop() can signal the server and any children.
            kwargs["start_new_session"] = True

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=self._log_fh,
            env=env,
            cwd=str(REPO_ROOT),
            text=True,
            bufsize=1,
            **kwargs,
        )

        # Wait for ready signal in stdout
        deadline = time.monotonic() + timeout
        ready = False
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                self._log_fh.flush()
                raise RuntimeError(
                    f"Server exited prematurely (code {self._proc.returncode}). "
                    f"Check {self.log_path}"
                )
            # readline() blocks until a line is available or EOF
            # We use a timeout via select on Unix; on Windows we just poll
            line = self._proc.stdout.readline()
            if not line:
                time.sleep(0.05)
                continue
            if "SCENE_ATLAS_READY" in line:
                # Uvicorn has bound the port — release our reservation socket
                if self._port_sock:
                    self._port_sock.close()
                    self._port_sock = None
                ready = True
                break

        if not ready:
            self.stop(force=True)
            raise RuntimeError(
                f"Server did not become ready within {timeout}s. Check {self.log_path}"
            )

        self.base_url = f"http://127.0.0.1:{self.port}"

        # Drain remaining stdout to log in background (server also logs to stderr/log_fh).
        # Capture local refs so stop() setting self._log_fh=None doesn't cause AttributeError,
        # and guard against ValueError if stop() closes the file while we're still draining.
        def _drain(proc_stdout=self._proc.stdout, log_fh=self._log_fh) -> None:
            for line in proc_stdout:
                try:
                    log_fh.write(f"[stdout] {line}")
                    log_fh.flush()
                except ValueError:
                    break  # File closed by stop() — nothing more to do

        threading.Thread(target=_drain, daemon=True, name="stdout-drain").start()

        # The backend prints the ready line from its lifespan, just before uvicorn
        # binds the socket, so wait until it actually accepts connections.
        while True:
            try:
                httpx.get(f"{self.base_url}/health", timeout=5)
                break
            except httpx.TransportError:
                if time.monotonic() > deadline or self._proc.poll() is not None:
                    self.stop(force=True)
                    raise RuntimeError(
                        f"Server printed its ready line but isn't accepting connections. "
                        f"Check {self.log_path}"
                    ) from None
                time.sleep(0.1)

        return self.base_url

    def wait_for_clip(self, timeout: float = 120) -> None:
        """Block until the CLIP model is loaded by making a warm-up search request.

        The search endpoint calls get_clip_service() which blocks on _clip_ready.wait().
        Once this returns, CLIP is guaranteed ready for all subsequent requests.
        """
        assert self.base_url is not None
        deadline = time.monotonic() + timeout
        with httpx.Client(base_url=self.base_url, timeout=timeout) as client:
            while time.monotonic() < deadline:
                try:
                    # A non-empty query triggers CLIP; empty queries skip it
                    r = client.get(
                        "/api/v1/search",
                        params={"q": "stress test warm up", "limit": 1},
                        timeout=timeout,
                    )
                    if r.status_code < 500:
                        return  # CLIP loaded (even 400 means we got through)
                except httpx.RequestError:
                    time.sleep(1)
        raise RuntimeError(f"CLIP did not load within {timeout}s. Check {self.log_path}")

    def stop(self, force: bool = False) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is not None:
            # Already dead
            if self._port_sock:
                self._port_sock.close()
                self._port_sock = None
            if self._log_fh:
                self._log_fh.close()
                self._log_fh = None
            self._proc = None
            return

        if sys.platform == "win32":
            if force:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                    capture_output=True,
                )
            else:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                        capture_output=True,
                    )
        else:
            import signal

            def _signal_group(sig: int) -> None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(self._proc.pid, sig)

            if force:
                _signal_group(signal.SIGKILL)
                self._proc.wait()
            else:
                _signal_group(signal.SIGTERM)
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    _signal_group(signal.SIGKILL)
                    self._proc.wait()

        if self._port_sock:
            self._port_sock.close()
            self._port_sock = None
        if self._log_fh:
            self._log_fh.flush()
            self._log_fh.close()
            self._log_fh = None
        self._proc = None

    def copy_artifacts(self, dest: Path) -> None:
        """Copy server log and DB snapshot to a results directory."""
        dest.mkdir(parents=True, exist_ok=True)
        if self.log_path.exists():
            shutil.copy2(self.log_path, dest / "server.log")
        db_path = self.data_dir / "battlemap.db"
        if db_path.exists():
            shutil.copy2(db_path, dest / "db.sqlite")


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------


def _check_disk_space(path: Path, warn_below_gb: float = 10.0) -> None:
    try:
        usage = shutil.disk_usage(path)
        free_gb = usage.free / (1024**3)
        if free_gb < warn_below_gb:
            print(
                _yellow(
                    f"  Warning: Only {free_gb:.1f} GB free on disk. "
                    f"Large fixtures require ~200 MB (default) or ~7 GB (--large)."
                )
            )
    except Exception:
        pass  # Non-fatal


def _check_ffmpeg() -> bool:
    """Return True if ffmpeg is available on PATH."""
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ---------------------------------------------------------------------------
# Results display
# ---------------------------------------------------------------------------


def _print_banner() -> None:
    print()
    print(_bold("Scene Atlas — Import Pipeline Stress Testing"))
    print("=" * 52)
    print()


def _print_result(result: ScenarioResult) -> None:
    status = _green("PASS") if result.passed else _red("FAIL")
    elapsed = f"({result.elapsed:.0f}s)"
    detail = result.message
    if result.stats:
        detail = result.stats.summary_str()
    name = result.name.ljust(30)
    print(f"  {status}  {name} {elapsed:>6}  {detail}")
    if not result.passed and result.failure_details:
        for line in result.failure_details.strip().splitlines():
            print(f"           {_red('->')} {line}")


def _print_summary(results: list[ScenarioResult], results_dir: Path | None) -> None:
    print()
    print("=" * 52)
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    if passed == total:
        verdict = _green(f"All {total} scenarios passed")
    else:
        verdict = _red(f"{passed}/{total} scenarios passed")
    print(f"  {verdict}")
    if results_dir and any(not r.passed for r in results):
        print(f"  Artifacts -> {results_dir}")
    print()


def _save_summary(results: list[ScenarioResult], dest: Path) -> None:
    summary = {
        "timestamp": datetime.now().isoformat(),
        "passed": sum(1 for r in results if r.passed),
        "total": len(results),
        "scenarios": [
            {
                "name": r.name,
                "passed": r.passed,
                "message": r.message,
                "elapsed": round(r.elapsed, 2),
                "stats": (
                    {
                        "count": r.stats.count,
                        "errors": r.stats.errors,
                        "p50": r.stats.p50,
                        "p95": r.stats.p95,
                        "p99": r.stats.p99,
                    }
                    if r.stats
                    else None
                ),
                "failure_details": r.failure_details,
            }
            for r in results
        ],
    }
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "summary.json").write_text(json.dumps(summary, indent=2))


# ---------------------------------------------------------------------------
# Run a single scenario
# ---------------------------------------------------------------------------


def _run_scenario(
    scenario_name: str,
    scenario_fn,
    work_dir: Path,
    fixtures_dir: Path,
    large_mode: bool,
    quick_mode: bool,
    results_dir: Path,
    wait_for_clip: bool = True,
) -> ScenarioResult:
    """Start a fresh server, run the scenario, stop the server, collect artifacts."""
    print(f"  Running {_bold(scenario_name)}...")

    server = StressTestServer(work_dir / scenario_name)
    t_start = time.monotonic()

    try:
        base_url = server.start()
        if wait_for_clip:
            print("    Waiting for CLIP model to load...")
            server.wait_for_clip()

        result = asyncio.run(
            scenario_fn(
                base_url=base_url,
                fixtures_dir=fixtures_dir,
                large_mode=large_mode,
                quick_mode=quick_mode,
            )
        )
    except Exception as exc:
        elapsed = time.monotonic() - t_start
        result = ScenarioResult(
            name=scenario_name,
            passed=False,
            message=f"Scenario raised unexpected exception: {type(exc).__name__}: {exc}",
            elapsed=elapsed,
            failure_details=traceback.format_exc(),
        )
    finally:
        server.stop()

    result.elapsed = time.monotonic() - t_start

    # Save artifacts only on failure
    if not result.passed:
        artifact_dir = results_dir / f"{_timestamp()}_{scenario_name}"
        server.copy_artifacts(artifact_dir)
        _save_summary([result], artifact_dir)
        if result.failure_details:
            result.failure_details = (
                f"Server log: {artifact_dir / 'server.log'}\n"
                f"DB snapshot: {artifact_dir / 'db.sqlite'}\n"
                f"{result.failure_details}"
            )

    return result


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


# ---------------------------------------------------------------------------
# CLI subcommands
# ---------------------------------------------------------------------------


def _cmd_list(args: argparse.Namespace) -> None:
    from stress_tests import scenarios

    print()
    print(_bold("Available stress test scenarios:"))
    print()
    header = f"  {'Scenario':<30} {'Est. time (default)':<22} {'Est. time (--quick)'}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, _fn, default_time, quick_time in scenarios.SCENARIO_REGISTRY:
        print(f"  {name:<30} {default_time:<22} {quick_time}")
    print()
    print("  Total (default): ~20-35 min   Total (--quick): ~6 min")
    print()


def _cmd_generate_fixtures(args: argparse.Namespace) -> None:
    from stress_tests import fixtures

    has_ffmpeg = _check_ffmpeg()
    if not has_ffmpeg:
        print(_yellow("  Warning: ffmpeg not found — video fixtures will be skipped."))
        print(_yellow("  Install ffmpeg and add to PATH to enable video scenarios."))

    print(f"  Generating fixtures in {FIXTURES_DIR}...")
    _check_disk_space(FIXTURES_DIR.parent)
    fixtures.ensure_fixtures(
        fixtures_dir=FIXTURES_DIR,
        large_mode=args.large,
        has_ffmpeg=has_ffmpeg,
    )
    print(_green("  Fixtures ready."))


def _cmd_run(args: argparse.Namespace) -> None:
    from stress_tests import fixtures, scenarios

    has_ffmpeg = _check_ffmpeg()
    if not has_ffmpeg:
        print(_yellow("  Warning: ffmpeg not found — video scenarios will be skipped."))

    _check_disk_space(FIXTURES_DIR.parent)

    # Generate fixtures
    print("  Generating/verifying fixtures...")
    fixtures.ensure_fixtures(
        fixtures_dir=FIXTURES_DIR,
        large_mode=args.large,
        has_ffmpeg=has_ffmpeg,
    )

    # Select scenarios to run
    if args.all:
        selected = scenarios.SCENARIO_REGISTRY
    else:
        selected = [entry for entry in scenarios.SCENARIO_REGISTRY if entry[0] == args.scenario]
        if not selected:
            print(_red(f"  Unknown scenario: {args.scenario!r}"))
            print("  Run `python -m stress_tests list` to see available scenarios.")
            sys.exit(1)

    # Skip video scenarios if no ffmpeg
    if not has_ffmpeg:
        selected = [e for e in selected if "video" not in e[0] and "large_upload" not in e[0]]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = RESULTS_DIR / f"_work_{_timestamp()}"

    results: list[ScenarioResult] = []
    _print_banner()

    if not MODELS_DIR.is_dir():
        print(
            _yellow(
                f"  Warning: no models directory at {MODELS_DIR}. Every scenario processes "
                "images and needs the ONNX model: run `uv run python scripts/models/setup_models.py` "
                "or set STRESS_MODELS_DIR."
            )
        )

    for name, fn, _dt, _qt in selected:
        result = _run_scenario(
            scenario_name=name,
            scenario_fn=fn,
            work_dir=work_dir,
            fixtures_dir=FIXTURES_DIR,
            large_mode=getattr(args, "large", False),
            quick_mode=getattr(args, "quick", False),
            results_dir=RESULTS_DIR,
        )
        results.append(result)
        _print_result(result)

    _print_summary(results, RESULTS_DIR if any(not r.passed for r in results) else None)

    # Clean up work dir on full success
    if all(r.passed for r in results) and work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)

    sys.exit(0 if all(r.passed for r in results) else 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m stress_tests",
        description="Scene Atlas import pipeline stress testing suite",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list
    sub.add_parser("list", help="List available scenarios with estimated runtimes")

    # generate-fixtures
    gen_parser = sub.add_parser("generate-fixtures", help="Pre-generate test fixtures")
    gen_parser.add_argument(
        "--large",
        action="store_true",
        help="Generate 500MB+ variants (requires ~7 GB disk)",
    )

    # run
    run_parser = sub.add_parser("run", help="Run stress test scenarios")
    run_group = run_parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("--all", action="store_true", help="Run all scenarios")
    run_group.add_argument("--scenario", metavar="NAME", help="Run a single scenario")
    run_parser.add_argument("--quick", action="store_true", help="Reduced load, <7 min total")
    run_parser.add_argument(
        "--large",
        action="store_true",
        help="Enable 500MB+ fixture variants",
    )

    args = parser.parse_args()

    if args.command == "list":
        _cmd_list(args)
    elif args.command == "generate-fixtures":
        _cmd_generate_fixtures(args)
    elif args.command == "run":
        _cmd_run(args)


if __name__ == "__main__":
    main()
