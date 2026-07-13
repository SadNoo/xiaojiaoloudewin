from __future__ import annotations

import argparse
import base64
import getpass
import os
import secrets
import sys
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select

from .config import Settings
from .database import AdminUser, Database
from .security import hash_secret


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def generate_env(path: Path) -> None:
    if path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    private = Ed25519PrivateKey.generate().private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    content = "\n".join([
        "LICENSE_ENV=development",
        "LICENSE_DOMAIN=localhost",
        "LICENSE_DATABASE_URL=sqlite:///./data/license.db",
        f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}",
        f"LICENSE_HMAC_SECRET={_b64(secrets.token_bytes(32))}",
        f"LICENSE_SIGNING_PRIVATE_KEY={_b64(private)}",
        "LICENSE_PUBLIC_BASE_URL=http://127.0.0.1:8090",
        "LICENSE_OFFLINE_GRACE_HOURS=72",
        "LICENSE_HEARTBEAT_SECONDS=900",
        "LICENSE_SUBADMIN_LIMIT=100",
        "",
    ])
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)
    print(f"Created {path} with mode 0600")


def bootstrap_owner(username: str, *, password_stdin: bool = False) -> None:
    if password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        confirm = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("Owner password: ")
        confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters")
    settings = Settings.from_env()
    database = Database(settings.database_url)
    database.create_all()
    with database.session() as session:
        if session.scalar(select(AdminUser).where(AdminUser.username == username)):
            raise SystemExit("Username already exists")
        if session.scalar(select(AdminUser).where(AdminUser.role == "owner")):
            raise SystemExit("An owner already exists")
        session.add(AdminUser(
            id=str(uuid.uuid4()), username=username, password_hash=hash_secret(password),
            role="owner", active_license_limit=0,
        ))
    print(f"Owner created: {username}")


def main() -> None:
    parser = argparse.ArgumentParser(description="xianyuxian license server administration")
    subparsers = parser.add_subparsers(dest="command", required=True)
    env_parser = subparsers.add_parser("generate-env", help="create local secrets in a .env file")
    env_parser.add_argument("--path", default=".env")
    owner_parser = subparsers.add_parser("bootstrap-owner", help="create the first owner account")
    owner_parser.add_argument("--username", default="owner")
    owner_parser.add_argument(
        "--password-stdin", action="store_true",
        help="read password and confirmation from two stdin lines (for secure deployment automation)",
    )
    args = parser.parse_args()
    if args.command == "generate-env":
        generate_env(Path(args.path))
    elif args.command == "bootstrap-owner":
        bootstrap_owner(args.username, password_stdin=args.password_stdin)


if __name__ == "__main__":
    main()
