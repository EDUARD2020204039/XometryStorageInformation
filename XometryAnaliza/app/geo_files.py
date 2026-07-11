from __future__ import annotations

from pathlib import PureWindowsPath

import paramiko

from . import settings


def _sftp_path(windows_path: str) -> str:
    normalized = windows_path.replace("\\", "/")
    drive = PureWindowsPath(windows_path).drive
    if drive and not normalized.startswith("/"):
        return f"/{normalized}"
    return normalized


def read_remote_file(windows_path: str) -> bytes:
    key = paramiko.Ed25519Key.from_private_key_file(settings.GEO_SFTP_KEY_PATH)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(
            settings.GEO_SFTP_HOST,
            port=settings.GEO_SFTP_PORT,
            username=settings.GEO_SFTP_USER,
            pkey=key,
            timeout=10,
            auth_timeout=10,
            banner_timeout=10,
        )
        with ssh.open_sftp() as sftp:
            with sftp.open(_sftp_path(windows_path), "rb") as remote_file:
                return remote_file.read()
    finally:
        ssh.close()


def read_remote_geo_file(windows_path: str) -> bytes:
    return read_remote_file(windows_path)
