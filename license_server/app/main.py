import calendar
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Annotated, Iterator

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from .config import Settings
from .database import (
    Activation, AdminSession, AdminUser, AuditEvent, Database, License, RefreshToken, Release, utc_now,
)
from .schemas import (
    ActivationRequest, ActivationResponse, AdminLoginRequest, AdminSessionResponse, HeartbeatRequest,
    HeartbeatResponse, LicenseCodeResponse, LicenseCreateRequest, LicenseCreatedResponse, LicenseResponse, RefreshRequest,
    ReleaseCreateRequest, ReleaseManifestResponse, ReleaseResponse, SubadminCreateRequest, SubadminResponse,
    ServerTimeResponse, TokenBundleResponse,
)
from .security import (
    TicketSigner, access_payload, decrypt_license_code, encrypt_license_code, hash_secret, license_lookup,
    new_license_code, new_opaque_token, normalize_license_code, offline_payload, timestamp, token_hash, verify_secret,
)


def _uuid() -> str:
    return str(uuid.uuid4())


def _json(value: str) -> dict:
    try:
        parsed = json.loads(value or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _add_calendar_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _semver(value: str) -> tuple[int, int, int]:
    try:
        core = value.split("-", 1)[0].split("+", 1)[0]
        major, minor, patch = core.split(".", 2)
        return int(major), int(minor), int(patch)
    except Exception:
        return 0, 0, 0


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    return forwarded or (request.client.host if request.client else "")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    signer = TicketSigner(settings.signing_private_key)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.create_all()
        yield

    app = FastAPI(
        title="xianyuxian Personal License API",
        version="0.1.0",
        docs_url="/docs" if settings.environment != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.database = database
    app.state.signer = signer
    if settings.environment != "production":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=False,
        )

    def get_db() -> Iterator[Session]:
        with database.session() as session:
            yield session

    Db = Annotated[Session, Depends(get_db)]

    def bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        return authorization.split(" ", 1)[1].strip()

    def current_admin(db: Db, token: Annotated[str, Depends(bearer_token)]) -> AdminUser:
        now = utc_now()
        session_row = db.scalar(
            select(AdminSession).where(
                AdminSession.token_hash == token_hash(token),
                AdminSession.revoked_at.is_(None),
                AdminSession.expires_at > now,
            )
        )
        if not session_row or not session_row.admin.enabled:
            raise HTTPException(status_code=401, detail="invalid or expired admin session")
        return session_row.admin

    CurrentAdmin = Annotated[AdminUser, Depends(current_admin)]

    def current_activation(db: Db, token: Annotated[str, Depends(bearer_token)]) -> Activation:
        try:
            payload = signer.verify(token, purpose="access")
        except Exception as exc:
            raise HTTPException(status_code=401, detail="invalid or expired access token") from exc
        activation = db.get(Activation, payload.get("activation_id"))
        if not activation or activation.device_id != payload.get("device_id"):
            raise HTTPException(status_code=401, detail="activation not found")
        _ensure_active(activation.license, activation)
        return activation

    CurrentActivation = Annotated[Activation, Depends(current_activation)]

    def audit(
        db: Session, request: Request, action: str, object_type: str, object_id: str,
        actor: AdminUser | None = None, details: dict | None = None,
    ) -> None:
        db.add(AuditEvent(
            id=_uuid(), actor_admin_id=actor.id if actor else None, action=action,
            object_type=object_type, object_id=object_id, source_ip=_client_ip(request),
            details_json=json.dumps(details or {}, separators=(",", ":"), ensure_ascii=False),
        ))

    def _release_policy(db: Session, channel: str, current_version: str) -> tuple[str | None, str | None, bool, str | None]:
        releases = list(db.scalars(select(Release).where(Release.channel == channel, Release.published.is_(True))))
        latest = max((r.version for r in releases if not r.blocked), key=_semver, default=None)
        minimum = max((r.version for r in releases if r.minimum), key=_semver, default=None)
        blocked = any(r.blocked and r.version == current_version for r in releases)
        update_required = blocked or bool(minimum and _semver(current_version) < _semver(minimum))
        latest_row = next((r for r in releases if r.version == latest and not r.blocked), None)
        return latest, minimum, update_required, latest_row.download_url if latest_row else None

    def _ensure_active(license_row: License, activation: Activation | None = None) -> None:
        now = utc_now()
        if license_row.status != "active" or license_row.revoked_at:
            raise HTTPException(status_code=403, detail="license revoked or disabled")
        if license_row.expires_at and license_row.expires_at <= now:
            raise HTTPException(status_code=403, detail="license expired")
        if activation and (activation.status != "active" or activation.revoked_at):
            raise HTTPException(status_code=403, detail="device activation revoked")

    def _start_license_if_needed(license_row: License) -> None:
        if license_row.starts_at:
            return
        now = utc_now()
        license_row.starts_at = now
        if license_row.expiry_type == "days":
            license_row.expires_at = now + timedelta(days=int(license_row.duration_value or 0))
        elif license_row.expiry_type == "calendar_months":
            license_row.expires_at = _add_calendar_months(now, int(license_row.duration_value or 0))

    def _issue_bundle(db: Session, activation: Activation, channel: str) -> TokenBundleResponse:
        license_row = activation.license
        _ensure_active(license_row, activation)
        now = utc_now()
        latest, minimum, update_required, download_url = _release_policy(db, channel, activation.app_version)
        if update_required:
            raise HTTPException(status_code=426, detail={
                "code": "client_version_not_allowed", "minimum_version": minimum, "latest_version": latest,
                "download_url": download_url,
            })
        access_expires = now + timedelta(seconds=settings.access_token_seconds)
        access_token = signer.sign(access_payload(activation.id, activation.device_id, settings.access_token_seconds))
        refresh_raw = new_opaque_token(48)
        refresh_expires = now + timedelta(days=settings.refresh_token_days)
        db.add(RefreshToken(
            id=_uuid(), activation_id=activation.id, token_hash=token_hash(refresh_raw),
            expires_at=refresh_expires,
        ))
        offline_expires = now + timedelta(hours=settings.offline_grace_hours)
        if license_row.expires_at and license_row.expires_at < offline_expires:
            offline_expires = license_row.expires_at
        entitlements = _json(license_row.entitlements_json)
        entitlements.setdefault("max_accounts", license_row.max_accounts)
        offline_ticket = signer.sign(offline_payload(
            activation_id=activation.id, license_id=license_row.id, device_id=activation.device_id,
            expires_at=offline_expires, license_expires_at=license_row.expires_at,
            entitlements=entitlements, minimum_version=minimum,
        ))
        return TokenBundleResponse(
            activation_id=activation.id, license_status=license_row.status,
            access_token=access_token, access_expires_at=access_expires,
            refresh_token=refresh_raw, refresh_expires_at=refresh_expires,
            offline_ticket=offline_ticket, offline_expires_at=offline_expires,
            license_expires_at=license_row.expires_at, entitlements=entitlements,
            heartbeat_seconds=settings.heartbeat_seconds, minimum_version=minimum,
            latest_version=latest, update_required=False, server_time=now,
        )

    @app.get("/health/live")
    def health_live() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready(db: Db) -> dict:
        db.execute(select(1))
        return {"status": "ready"}

    @app.get("/v1/public-key")
    def public_key() -> dict:
        return {"algorithm": "Ed25519", "kid": "license-v1", "public_key": signer.public_key_base64()}

    @app.post("/admin/v1/session", response_model=AdminSessionResponse)
    def admin_login(body: AdminLoginRequest, request: Request, db: Db) -> AdminSessionResponse:
        admin = db.scalar(select(AdminUser).where(AdminUser.username == body.username))
        if not admin or not admin.enabled or not verify_secret(body.password, admin.password_hash):
            raise HTTPException(status_code=401, detail="invalid username or password")
        raw = new_opaque_token(48)
        expires = utc_now() + timedelta(hours=settings.admin_session_hours)
        db.add(AdminSession(
            id=_uuid(), admin_id=admin.id, token_hash=token_hash(raw), expires_at=expires,
        ))
        audit(db, request, "admin.login", "admin_user", admin.id, admin)
        return AdminSessionResponse(access_token=raw, expires_at=expires, role=admin.role)

    @app.post("/admin/v1/admins", response_model=SubadminResponse, status_code=201)
    def create_subadmin(body: SubadminCreateRequest, request: Request, db: Db, admin: CurrentAdmin) -> SubadminResponse:
        if admin.role != "owner":
            raise HTTPException(status_code=403, detail="owner role required")
        if db.scalar(select(AdminUser).where(AdminUser.username == body.username)):
            raise HTTPException(status_code=409, detail="username already exists")
        row = AdminUser(
            id=_uuid(), username=body.username, password_hash=hash_secret(body.password), role="subadmin",
            parent_id=admin.id, active_license_limit=body.active_license_limit,
        )
        db.add(row)
        db.flush()
        audit(db, request, "subadmin.create", "admin_user", row.id, admin, {"limit": row.active_license_limit})
        return SubadminResponse.model_validate(row, from_attributes=True)

    @app.get("/admin/v1/admins", response_model=list[SubadminResponse])
    def list_subadmins(db: Db, admin: CurrentAdmin) -> list[SubadminResponse]:
        if admin.role != "owner":
            raise HTTPException(status_code=403, detail="owner role required")
        rows = db.scalars(select(AdminUser).where(AdminUser.role == "subadmin").order_by(AdminUser.created_at.desc()))
        return [SubadminResponse.model_validate(row, from_attributes=True) for row in rows]

    @app.get("/admin/v1/server-time", response_model=ServerTimeResponse)
    def admin_server_time(
        admin: CurrentAdmin,
        calendar_months: int = Query(default=1, ge=1, le=120),
    ) -> ServerTimeResponse:
        now = utc_now()
        return ServerTimeResponse(
            server_time=now,
            calendar_months=calendar_months,
            calendar_month_expires_at=_add_calendar_months(now, calendar_months),
        )

    @app.post("/admin/v1/licenses", response_model=LicenseCreatedResponse, status_code=201)
    def create_license(body: LicenseCreateRequest, request: Request, db: Db, admin: CurrentAdmin) -> LicenseCreatedResponse:
        creator = admin
        if body.assigned_admin_id:
            if admin.role != "owner":
                raise HTTPException(status_code=403, detail="only owner can assign licenses")
            creator = db.get(AdminUser, body.assigned_admin_id)
            if not creator or not creator.enabled:
                raise HTTPException(status_code=404, detail="assigned admin not found")
        if creator.role == "subadmin":
            now = utc_now()
            candidates = db.scalars(select(License).where(License.created_by == creator.id, License.status == "active"))
            active_count = sum(1 for item in candidates if not item.expires_at or item.expires_at > now)
            if active_count >= creator.active_license_limit:
                raise HTTPException(status_code=409, detail="subadmin active license limit reached")
        now = utc_now()
        raw_code = new_license_code()
        starts_at = now if body.expiry_type == "calendar_months" else None
        expires_at = _add_calendar_months(now, int(body.duration_value or 0)) if starts_at else None
        row = License(
            id=_uuid(), code_lookup=license_lookup(raw_code, settings.hmac_secret),
            code_hash=hash_secret(normalize_license_code(raw_code)),
            code_ciphertext=encrypt_license_code(raw_code, settings.hmac_secret),
            expiry_type=body.expiry_type, duration_value=body.duration_value, max_devices=1,
            starts_at=starts_at, expires_at=expires_at,
            max_accounts=body.max_accounts, note=body.note,
            entitlements_json=json.dumps(body.entitlements, separators=(",", ":"), ensure_ascii=False),
            created_by=creator.id, created_at=now, updated_at=now,
        )
        db.add(row)
        db.flush()
        audit(db, request, "license.create", "license", row.id, admin, {"assigned_admin_id": creator.id})
        return LicenseCreatedResponse(
            id=row.id, license_code=raw_code, expiry_type=row.expiry_type,
            duration_value=row.duration_value, max_devices=1, max_accounts=row.max_accounts,
            starts_at=row.starts_at, expires_at=row.expires_at,
            created_at=row.created_at, server_time=now,
        )

    @app.get("/admin/v1/licenses", response_model=list[LicenseResponse])
    def list_licenses(db: Db, admin: CurrentAdmin) -> list[LicenseResponse]:
        query = select(License).order_by(License.created_at.desc())
        if admin.role != "owner":
            query = query.where(License.created_by == admin.id)
        rows = db.scalars(query)
        return [LicenseResponse(
            id=row.id, masked_code=f"XY-*****-*****-{row.id[-5:].upper()}",
            can_reveal=bool(row.code_ciphertext), status=row.status,
            expiry_type=row.expiry_type, duration_value=row.duration_value, starts_at=row.starts_at,
            expires_at=row.expires_at, max_devices=row.max_devices, max_accounts=row.max_accounts,
            note=row.note, created_by=row.created_by, created_at=row.created_at,
        ) for row in rows]

    @app.get("/admin/v1/licenses/{license_id}/code", response_model=LicenseCodeResponse)
    def reveal_license_code(
        license_id: str, request: Request, response: Response, db: Db, admin: CurrentAdmin,
    ) -> LicenseCodeResponse:
        row = db.get(License, license_id)
        if not row or (admin.role != "owner" and row.created_by != admin.id):
            raise HTTPException(status_code=404, detail="license not found")
        if not row.code_ciphertext:
            raise HTTPException(status_code=409, detail="license code was created before reveal support")
        try:
            raw_code = decrypt_license_code(row.code_ciphertext, settings.hmac_secret)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="license code decrypt failed") from exc
        revealed_at = utc_now()
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        audit(db, request, "license.reveal", "license", row.id, admin)
        return LicenseCodeResponse(license_code=raw_code, revealed_at=revealed_at)

    @app.post("/admin/v1/licenses/{license_id}/revoke", status_code=204, response_model=None)
    def revoke_license(license_id: str, request: Request, db: Db, admin: CurrentAdmin) -> None:
        row = db.get(License, license_id)
        if not row or (admin.role != "owner" and row.created_by != admin.id):
            raise HTTPException(status_code=404, detail="license not found")
        now = utc_now()
        row.status = "revoked"
        row.revoked_at = now
        activation_ids = list(db.scalars(select(Activation.id).where(Activation.license_id == row.id)))
        db.execute(
            Activation.__table__.update().where(Activation.license_id == row.id).values(status="revoked", revoked_at=now)
        )
        if activation_ids:
            db.execute(
                RefreshToken.__table__.update().where(RefreshToken.activation_id.in_(activation_ids)).values(revoked_at=now)
            )
        audit(db, request, "license.revoke", "license", row.id, admin)

    @app.get("/admin/v1/activations", response_model=list[ActivationResponse])
    def list_activations(db: Db, admin: CurrentAdmin) -> list[ActivationResponse]:
        query = select(Activation).join(License).order_by(Activation.last_seen_at.desc())
        if admin.role != "owner":
            query = query.where(License.created_by == admin.id)
        return [ActivationResponse.model_validate(row, from_attributes=True) for row in db.scalars(query)]

    @app.post("/admin/v1/activations/{activation_id}/revoke", status_code=204, response_model=None)
    def revoke_activation(activation_id: str, request: Request, db: Db, admin: CurrentAdmin) -> None:
        row = db.get(Activation, activation_id)
        if not row or (admin.role != "owner" and row.license.created_by != admin.id):
            raise HTTPException(status_code=404, detail="activation not found")
        now = utc_now()
        row.status = "revoked"
        row.revoked_at = now
        db.execute(RefreshToken.__table__.update().where(RefreshToken.activation_id == row.id).values(revoked_at=now))
        audit(db, request, "activation.revoke", "activation", row.id, admin)

    @app.post("/admin/v1/releases", response_model=ReleaseResponse, status_code=201)
    def create_release(body: ReleaseCreateRequest, request: Request, db: Db, admin: CurrentAdmin) -> ReleaseResponse:
        if admin.role != "owner":
            raise HTTPException(status_code=403, detail="owner role required")
        row = Release(id=_uuid(), **body.model_dump())
        db.add(row)
        db.flush()
        audit(db, request, "release.create", "release", row.id, admin, {"version": row.version})
        return ReleaseResponse.model_validate(row, from_attributes=True)

    @app.get("/v1/releases/latest", response_model=ReleaseManifestResponse | None)
    def latest_release(db: Db, channel: str = "stable") -> ReleaseManifestResponse | None:
        releases = list(db.scalars(select(Release).where(Release.channel == channel, Release.published.is_(True))))
        if not releases:
            return None
        row = max(releases, key=lambda item: _semver(item.version))
        release = ReleaseResponse.model_validate(row, from_attributes=True)
        now = utc_now()
        manifest_ticket = signer.sign({
            "purpose": "release_manifest",
            "iat": timestamp(now),
            "exp": timestamp(now + timedelta(minutes=10)),
            "release": release.model_dump(mode="json"),
        })
        return ReleaseManifestResponse(release=release, manifest_ticket=manifest_ticket)

    @app.post("/v1/licenses/activate", response_model=TokenBundleResponse)
    def activate(body: ActivationRequest, request: Request, db: Db) -> TokenBundleResponse:
        lookup = license_lookup(body.license_code, settings.hmac_secret)
        license_row = db.scalar(select(License).where(License.code_lookup == lookup))
        if not license_row or not verify_secret(normalize_license_code(body.license_code), license_row.code_hash):
            raise HTTPException(status_code=401, detail="invalid license code")
        _ensure_active(license_row)
        latest, minimum, update_required, download_url = _release_policy(db, body.channel, body.app_version)
        if update_required:
            raise HTTPException(status_code=426, detail={
                "code": "client_version_not_allowed", "minimum_version": minimum, "latest_version": latest,
                "download_url": download_url,
            })
        _start_license_if_needed(license_row)
        _ensure_active(license_row)
        activation = db.scalar(select(Activation).where(
            Activation.license_id == license_row.id, Activation.device_id == body.device_id,
        ))
        if activation and activation.status == "revoked":
            raise HTTPException(status_code=403, detail="device activation revoked")
        if not activation:
            active_count = db.scalar(select(func.count()).select_from(Activation).where(
                Activation.license_id == license_row.id, Activation.status == "active",
            )) or 0
            if active_count >= license_row.max_devices:
                raise HTTPException(status_code=409, detail="license device limit reached")
            activation = Activation(
                id=_uuid(), license=license_row, device_id=body.device_id,
                device_name=body.device_name, os_version=body.os_version,
                architecture=body.architecture, app_version=body.app_version,
            )
            db.add(activation)
            db.flush()
        else:
            activation.status = "active"
            activation.revoked_at = None
            activation.device_name = body.device_name
            activation.os_version = body.os_version
            activation.architecture = body.architecture
            activation.app_version = body.app_version
            activation.last_seen_at = utc_now()
        audit(db, request, "license.activate", "activation", activation.id, details={"license_id": license_row.id})
        return _issue_bundle(db, activation, body.channel)

    @app.post("/v1/licenses/refresh", response_model=TokenBundleResponse)
    def refresh(body: RefreshRequest, request: Request, db: Db) -> TokenBundleResponse:
        now = utc_now()
        row = db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == token_hash(body.refresh_token),
            RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now,
        ))
        if not row:
            raise HTTPException(status_code=401, detail="invalid or expired refresh token")
        activation = db.get(Activation, row.activation_id)
        if not activation or activation.device_id != body.device_id:
            raise HTTPException(status_code=401, detail="refresh token device mismatch")
        _ensure_active(activation.license, activation)
        row.revoked_at = now
        activation.app_version = body.app_version
        activation.last_seen_at = now
        audit(db, request, "license.refresh", "activation", activation.id)
        return _issue_bundle(db, activation, body.channel)

    @app.post("/v1/licenses/heartbeat", response_model=HeartbeatResponse)
    def heartbeat(body: HeartbeatRequest, request: Request, db: Db, activation: CurrentActivation) -> HeartbeatResponse:
        activation.app_version = body.app_version
        activation.last_seen_at = utc_now()
        latest, minimum, update_required, download_url = _release_policy(db, body.channel, body.app_version)
        if update_required:
            raise HTTPException(status_code=426, detail={
                "code": "client_version_not_allowed", "minimum_version": minimum, "latest_version": latest,
                "download_url": download_url,
            })
        license_row = activation.license
        offline_expires = utc_now() + timedelta(hours=settings.offline_grace_hours)
        if license_row.expires_at and license_row.expires_at < offline_expires:
            offline_expires = license_row.expires_at
        ticket = signer.sign(offline_payload(
            activation_id=activation.id, license_id=license_row.id, device_id=activation.device_id,
            expires_at=offline_expires, license_expires_at=license_row.expires_at,
            entitlements={**_json(license_row.entitlements_json), "max_accounts": license_row.max_accounts},
            minimum_version=minimum,
        ))
        audit(db, request, "license.heartbeat", "activation", activation.id)
        return HeartbeatResponse(
            status="active", license_expires_at=license_row.expires_at, offline_ticket=ticket,
            offline_expires_at=offline_expires, heartbeat_seconds=settings.heartbeat_seconds,
            minimum_version=minimum, latest_version=latest, update_required=False, server_time=utc_now(),
        )

    @app.get("/v1/licenses/status", response_model=HeartbeatResponse)
    def license_status(request: Request, db: Db, activation: CurrentActivation) -> HeartbeatResponse:
        return heartbeat(HeartbeatRequest(app_version=activation.app_version), request, db, activation)

    @app.post("/v1/licenses/deactivate", status_code=204, response_model=None)
    def deactivate(request: Request, db: Db, activation: CurrentActivation) -> None:
        now = utc_now()
        recent_count = db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "license.deactivate",
            AuditEvent.object_type == "activation",
            AuditEvent.object_id == activation.id,
            AuditEvent.created_at > now - timedelta(days=30),
        )) or 0
        if recent_count >= 2:
            raise HTTPException(status_code=429, detail="self-service deactivation limit reached")
        activation.status = "deactivated"
        db.execute(RefreshToken.__table__.update().where(RefreshToken.activation_id == activation.id).values(revoked_at=now))
        audit(db, request, "license.deactivate", "activation", activation.id)

    return app
