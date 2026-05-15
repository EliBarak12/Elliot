"""Spin up an ephemeral MariaDB / MySQL server for the lifetime of a test.

Mirrors ``local_postgres.py``: ``mariadb-install-db`` into a temp dir,
start ``mariadbd`` on a random loopback port, yield a DSN that
Elliot's ``source_type="mysql"`` path can use (Elliot speaks the MySQL
wire protocol via SQLAlchemy + ``pymysql``).

Skip gracefully when the binaries aren't on the host so the e2e suite
stays runnable on developer laptops without a MySQL/MariaDB install.
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

import pymysql


def _find_mariadb_binaries() -> tuple[Path, Path] | None:
    """Return ``(install_db_bin, mariadbd_bin)`` if both are on the host."""
    install_db = shutil.which("mariadb-install-db") or shutil.which("mysql_install_db")
    server = shutil.which("mariadbd") or shutil.which("mysqld")
    if install_db and server:
        return Path(install_db), Path(server)
    return None


def mysql_available() -> bool:
    return _find_mariadb_binaries() is not None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass(frozen=True)
class LocalMySQL:
    """Handle returned by :func:`ephemeral_mysql`."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @property
    def dsn(self) -> str:
        # SQLAlchemy + pymysql expects ``mysql+pymysql://``. Elliot's
        # ``db_connector.py`` accepts that scheme directly.
        return (
            f"mysql+pymysql://{self.user}:{self.password}@{self.host}:{self.port}/{self.database}"
        )


@contextmanager
def ephemeral_mysql(*, database: str = "elliot_e2e") -> Iterator[LocalMySQL]:
    """Yield a freshly-initialised MariaDB cluster on loopback.

    ``mariadb-install-db`` bootstraps a system tablespace under a temp
    dir; ``mariadbd`` then starts on a random port with skip-networking
    disabled and skip-grant-tables enabled so the test doesn't manage a
    password. Everything under the data dir is wiped on context exit.
    """
    bins = _find_mariadb_binaries()
    if bins is None:
        raise RuntimeError("mariadb / mysql binaries not found — install mariadb-server to enable")
    install_db_bin, server_bin = bins

    port = _free_port()
    base_dir = Path(mkdtemp(prefix="elliot-mysql-"))
    data_dir = base_dir / "data"
    socket_path = base_dir / "mysqld.sock"
    log_path = base_dir / "mysqld.log"

    # mariadb-install-db / mysqld refuse to run as root in most distros;
    # under the apt-shipped MariaDB the system user is ``mysql``. Detect
    # the situation and prefix with ``sudo -u mysql`` so initdb + start
    # both run as that user. The base dir is chown'd to match.
    use_mysql_user = (
        os.geteuid() == 0
        and subprocess.run(["id", "mysql"], capture_output=True, check=False).returncode == 0
    )
    sudo_prefix = ["sudo", "-u", "mysql"] if use_mysql_user else []
    if use_mysql_user:
        subprocess.run(
            ["chown", "-R", "mysql:mysql", str(base_dir)],
            check=True,
            capture_output=True,
        )

    subprocess.run(
        [
            *sudo_prefix,
            str(install_db_bin),
            f"--datadir={data_dir}",
            "--auth-root-authentication-method=normal",
            "--skip-test-db",
        ],
        check=True,
        capture_output=True,
    )

    pid_path = base_dir / "mysqld.pid"
    proc = subprocess.Popen(
        [
            *sudo_prefix,
            str(server_bin),
            f"--datadir={data_dir}",
            f"--socket={socket_path}",
            f"--pid-file={pid_path}",
            f"--port={port}",
            "--bind-address=127.0.0.1",
            "--skip-networking=OFF",
            # No password setup needed; ``skip-grant-tables`` lets the
            # test connect as root without credentials.
            "--skip-grant-tables",
            "--skip-name-resolve",
            "--log-warnings=1",
            # mariadbd defaults to /run/mysqld for several runtime files,
            # which doesn't exist when running unprivileged. Pinning the
            # pid + socket above plus disabling external auth-plugin dirs
            # keeps everything under the temp data dir.
        ],
        stdout=log_path.open("wb"),
        stderr=subprocess.STDOUT,
    )

    try:
        deadline = time.monotonic() + 30
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            try:
                conn = pymysql.connect(
                    host="127.0.0.1",
                    port=port,
                    user="root",
                    autocommit=True,
                )
                with conn.cursor() as cur:
                    cur.execute(f"CREATE DATABASE `{database}`")
                conn.close()
                break
            except Exception as exc:
                last_err = exc
                time.sleep(0.3)
        else:
            tail = log_path.read_text(errors="replace")[-1000:]
            raise RuntimeError(
                f"mariadbd did not come up on :{port} in 30s "
                f"(last: {last_err!r})\n--- log tail ---\n{tail}"
            )

        yield LocalMySQL(
            host="127.0.0.1",
            port=port,
            user="root",
            password="",
            database=database,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(base_dir, ignore_errors=True)
