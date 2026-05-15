"""Spin up an ephemeral PostgreSQL cluster for the lifetime of a test.

The Elliot DB-source code path (``elliot_core/sources/db_connector.py``)
talks to Postgres via SQLAlchemy + psycopg2. To exercise it end-to-end we
need a real server. This module uses the system's ``postgresql-16``
binaries to initdb into a temp dir, start a server on a free TCP port,
and yield the DSN. Cluster + data dir are wiped on context exit.

Skip gracefully when the binaries aren't on the host so the e2e suite
stays runnable on developer laptops without postgres installed.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

import psycopg2


def _find_pg_binaries() -> Path | None:
    """Return the ``.../postgresql/<ver>/bin`` directory containing initdb+pg_ctl.

    Ubuntu installs them under ``/usr/lib/postgresql/<version>/bin``. The
    binaries are not on PATH by default so plain ``which initdb`` fails.
    """
    for version in ("16", "15", "14"):
        candidate = Path(f"/usr/lib/postgresql/{version}/bin")
        if (candidate / "initdb").exists() and (candidate / "pg_ctl").exists():
            return candidate
    on_path = shutil.which("initdb")
    if on_path:
        return Path(on_path).parent
    return None


def postgres_available() -> bool:
    return _find_pg_binaries() is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass(frozen=True)
class LocalPostgres:
    """Handle returned by :func:`ephemeral_postgres`."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"


@contextmanager
def ephemeral_postgres(*, database: str = "elliot_e2e") -> Iterator[LocalPostgres]:
    """Yield a freshly-initialized, locally-running PostgreSQL cluster.

    The cluster is initdb'd into a temp dir, listens on a random loopback
    port, accepts trust auth (no password) so the test doesn't need to
    manage one, and is killed + removed on exit.
    """
    bindir = _find_pg_binaries()
    if bindir is None:
        raise RuntimeError("PostgreSQL binaries not found — install postgresql-16 to enable")

    port = _free_port()
    data_dir = Path(mkdtemp(prefix="elliot-pg-"))
    os.chmod(data_dir, 0o700)
    log_path = data_dir / "pg.log"

    # initdb needs to run as a non-root user; running as root errors out.
    # In CI/sandbox containers we are typically root, so initdb as the
    # `postgres` system user that the apt package created.
    initdb_user = "postgres" if os.geteuid() == 0 else os.environ.get("USER", "")
    sudo_prefix = ["sudo", "-u", "postgres"] if initdb_user == "postgres" else []

    # Postgres needs the data dir owned by the user running it.
    if sudo_prefix:
        subprocess.run(["chown", "-R", "postgres:postgres", str(data_dir)], check=True)

    subprocess.run(
        [
            *sudo_prefix,
            str(bindir / "initdb"),
            "-D",
            str(data_dir),
            "--auth=trust",
            "--username=postgres",
            "--no-locale",
            "--encoding=UTF8",
        ],
        check=True,
        capture_output=True,
    )

    proc = subprocess.Popen(
        [
            *sudo_prefix,
            str(bindir / "postgres"),
            "-D",
            str(data_dir),
            "-p",
            str(port),
            "-h",
            "127.0.0.1",
            "-c",
            "logging_collector=off",
            "-c",
            "log_min_messages=warning",
        ],
        stdout=log_path.open("wb"),
        stderr=subprocess.STDOUT,
    )

    try:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                conn = psycopg2.connect(
                    host="127.0.0.1",
                    port=port,
                    user="postgres",
                    database="postgres",
                )
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(f'CREATE DATABASE "{database}"')
                conn.close()
                break
            except psycopg2.OperationalError:
                time.sleep(0.2)
        else:
            raise RuntimeError(f"postgres did not come up on :{port} in 20s")

        yield LocalPostgres(
            host="127.0.0.1",
            port=port,
            user="postgres",
            password="",
            database=database,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        # Run rm -rf as the same user that owns the dir; postgres re-chowned.
        shutil.rmtree(data_dir, ignore_errors=True)
