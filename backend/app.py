from __future__ import annotations

import base64
import cgi
import hashlib
import json
import mimetypes
import os
import secrets
import shutil
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image

from backend.auth.cognito.jwt_validator import AuthError, validate_cognito_jwt


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "ecolens.sqlite3"
STORAGE_DIR = DATA_DIR / "storage"
ORIGINALS_DIR = STORAGE_DIR / "originals"
THUMBNAILS_DIR = STORAGE_DIR / "thumbnails"
QUERY_TMP_DIR = STORAGE_DIR / "query_tmp"
LABELS_PATH = ROOT / "assets" / "labels.txt"
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_PUBLIC_DIR = FRONTEND_DIR / "public"
FRONTEND_SRC_DIR = FRONTEND_DIR / "src"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
AUTH_COOKIE = "ecolens_token"

COGNITO_REGION = os.environ.get("COGNITO_REGION", "us-east-1")
COGNITO_USER_POOL_ID = os.environ.get("COGNITO_USER_POOL_ID", "us-east-1_ahvGMB95O")
COGNITO_APP_CLIENT_ID = os.environ.get("COGNITO_APP_CLIENT_ID", "2scr7btsqhli8d0hcchdltvnf5")
COGNITO_DOMAIN = os.environ.get("COGNITO_DOMAIN", "us-east-1ahvgmb95o.auth.us-east-1.amazoncognito.com")
COGNITO_REDIRECT_URI = os.environ.get("COGNITO_REDIRECT_URI", "http://localhost:8000/")
JWKS_URL = os.environ.get(
    "JWKS_URL",
    f"https://cognito-idp.{COGNITO_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}/.well-known/jwks.json",
)


def now() -> int:
    return int(time.time())


def ensure_dirs() -> None:
    for path in [DATA_DIR, ORIGINALS_DIR, THUMBNAILS_DIR, QUERY_TMP_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    ensure_dirs()
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_type TEXT NOT NULL,
                checksum TEXT NOT NULL,
                original_url TEXT NOT NULL,
                thumbnail_url TEXT,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(owner_id) REFERENCES users(id)
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_files_owner_checksum
            ON files(owner_id, checksum);

            CREATE TABLE IF NOT EXISTS tags (
                file_id INTEGER NOT NULL,
                tag TEXT NOT NULL,
                count INTEGER NOT NULL,
                source TEXT NOT NULL,
                PRIMARY KEY(file_id, tag),
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                tag TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                UNIQUE(user_id, email, tag),
                FOREIGN KEY(user_id) REFERENCES users(id)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                email TEXT NOT NULL,
                tag TEXT NOT NULL,
                file_url TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            );
            """
        )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    salt, expected = encoded.split("$", 1)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return secrets.compare_digest(digest.hex(), expected)


def b64url_json(segment: str) -> dict[str, Any]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded.encode()).decode("utf-8"))


def decode_jwt_unverified(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT")
    return b64url_json(parts[1])

def get_or_create_cognito_user(conn: sqlite3.Connection, claims: dict[str, Any]) -> sqlite3.Row:
    """Map verified Cognito claims to the local demo user table.

    The local prototype still uses SQLite users/sessions. After Cognito verifies
    the identity, we create or reuse a local user row so existing owner-scoped
    storage logic can continue to work.
    """
    subject = claims.get("sub")
    email = (claims.get("email") or f"{subject}@cognito.local").strip().lower()
    first_name = claims.get("given_name") or "Cognito"
    last_name = claims.get("family_name") or "User"

    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if user is None:
        conn.execute(
            """
            INSERT INTO users(email, first_name, last_name, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                email,
                first_name,
                last_name,
                hash_password(secrets.token_urlsafe(24)),
                now(),
            ),
        )
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    return user

def cognito_login_url() -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": COGNITO_APP_CLIENT_ID,
            "response_type": "code",
            "scope": "email openid phone",
            "redirect_uri": COGNITO_REDIRECT_URI,
        },
        quote_via=urllib.parse.quote,
    )
    return f"https://{COGNITO_DOMAIN}/login?{query}"


def exchange_cognito_code(code: str) -> dict[str, Any]:
    body = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": COGNITO_APP_CLIENT_ID,
            "code": code,
            "redirect_uri": COGNITO_REDIRECT_URI,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://{COGNITO_DOMAIN}/oauth2/token",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def file_checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_species_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    if LABELS_PATH.exists():
        for line in LABELS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = line.split(";")
            if len(parts) >= 6:
                genus = parts[4].strip().capitalize()
                species_name = parts[5].strip().lower()
                scientific = f"{genus}_{species_name}".strip("_")
                common = parts[6] if len(parts) > 6 else scientific
                labels[scientific.lower()] = scientific
                if common:
                    labels[common.lower().replace(" ", "_")] = scientific
    return labels


SPECIES_LABELS = load_species_labels()


def detect_species_from_name(filename: str) -> dict[str, int]:
    """Demo detector.

    The supplied test set uses species names in filenames. This keeps the local
    app runnable without heavyweight GPU/Torch dependencies. In cloud deployment,
    replace this function with the provided model.pt inference pipeline.
    """
    normalized = Path(filename).stem.lower()
    hits: dict[str, int] = {}
    for key, species in SPECIES_LABELS.items():
        if key and key in normalized:
            hits[species] = hits.get(species, 0) + 1
    if not hits:
        chunks = normalized.split("_")
        if len(chunks) >= 2:
            hits[f"{chunks[0].capitalize()}_{chunks[1]}"] = 1
        else:
            hits["unknown_species"] = 1
    return hits


def create_thumbnail(source: Path, target: Path) -> bool:
    try:
        with Image.open(source) as img:
            img = img.convert("RGB")
            img.thumbnail((360, 360))
            target.parent.mkdir(parents=True, exist_ok=True)
            img.save(target, "JPEG", quality=82, optimize=True)
        return True
    except Exception:
        return False


def public_url(path: Path) -> str:
    relative = path.relative_to(STORAGE_DIR)
    return f"/media/{urllib.parse.quote(str(relative))}"


def row_to_file(row: sqlite3.Row, tags: dict[str, int]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "originalName": row["original_name"],
        "fileType": row["file_type"],
        "checksum": row["checksum"],
        "originalUrl": row["original_url"],
        "thumbnailUrl": row["thumbnail_url"],
        "createdAt": row["created_at"],
        "tags": tags,
    }


def get_file_with_tags(
    conn: sqlite3.Connection,
    file_id: int,
    owner_id: int | None = None,
) -> dict[str, Any] | None:
    if owner_id is None:
        row = conn.execute(
            "SELECT * FROM files WHERE id = ?",
            (file_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM files WHERE id = ? AND owner_id = ?",
            (file_id, owner_id),
        ).fetchone()

    if row is None: 
        return None

    tag_rows = conn.execute(
        "SELECT tag, count FROM tags WHERE file_id = ?",
        (file_id,),
    ).fetchall()

    return row_to_file(row, {r["tag"]: r["count"] for r in tag_rows})


def parse_cookies(header: str | None) -> dict[str, str]:
    cookies: dict[str, str] = {}
    if not header:
        return cookies
    for part in header.split(";"):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            cookies[key] = urllib.parse.unquote(value)
    return cookies


class EcoLensHandler(BaseHTTPRequestHandler):
    server_version = "AussieEcoLens/1.0"

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)

        # Local demo UI. The merged frontend stores the entry page in
        # frontend/public/index.html and browser modules/styles under frontend/src.
        if parsed.path in ("/", "/index.html"):
            self.serve_frontend_public("index.html")
            return

        if parsed.path.startswith("/src/"):
            self.serve_frontend_src(parsed.path)
            return

        if parsed.path.startswith("/static/"):
            self.serve_static(parsed.path)
            return

        if parsed.path.startswith("/media/"):
            self.require_auth(lambda user: self.serve_media(user, parsed.path))
        elif parsed.path == "/api/me":
            self.handle_me()
        elif parsed.path == "/api/config":
            self.handle_config()
        elif parsed.path == "/api/files":
            self.require_auth(lambda user: self.handle_list_files(user, parsed.query))
        elif parsed.path == "/api/notifications":
            self.require_auth(self.handle_notifications)
        else:
            self.not_found()

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        routes = {
            "/api/auth/signup": self.handle_signup,
            "/api/auth/login": self.handle_login,
            "/api/auth/logout": self.handle_logout,
            "/api/auth/cognito/exchange": self.handle_cognito_exchange,
        }
        if parsed.path in routes:
            routes[parsed.path]()
        elif parsed.path == "/api/upload":
            self.require_auth(self.handle_upload)
        elif parsed.path == "/api/query/tags":
            self.require_auth(self.handle_query_tags)
        elif parsed.path == "/api/query/species":
            self.require_auth(self.handle_query_species)
        elif parsed.path == "/api/query/thumbnail":
            self.require_auth(self.handle_query_thumbnail)
        elif parsed.path == "/api/query/by-file":
            self.require_auth(self.handle_query_by_file)
        elif parsed.path == "/api/tags/bulk":
            self.require_auth(self.handle_bulk_tags)
        elif parsed.path == "/api/files/delete":
            self.require_auth(self.handle_delete_files)
        elif parsed.path == "/api/subscribe":
            self.require_auth(self.handle_subscribe)
        else:
            self.not_found()

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, data: Any, status: int = 200, cookies: list[str] | None = None) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", self.headers.get("Origin", "*"))
        self.send_header("Access-Control-Allow-Credentials", "true")
        for cookie in cookies or []:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(payload)

    def serve_file(self, path: Path, content_type: str | None = None) -> None:
        if not path.exists() or not path.is_file():
            self.not_found()
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_frontend_public(self, filename: str) -> None:
        target = (FRONTEND_PUBLIC_DIR / filename).resolve()

        # Block path traversal and serve only files inside frontend/public.
        if FRONTEND_PUBLIC_DIR != target.parent and FRONTEND_PUBLIC_DIR not in target.parents:
            self.not_found()
            return

        self.serve_file(target)


    def serve_frontend_src(self, url_path: str) -> None:
        rel = urllib.parse.unquote(url_path.removeprefix("/src/"))
        target = (FRONTEND_SRC_DIR / rel).resolve()

        # Block path traversal and serve only files inside frontend/src.
        if FRONTEND_SRC_DIR not in target.parents:
            self.not_found()
            return

        self.serve_file(target)


    def serve_static(self, url_path: str) -> None:
        rel = urllib.parse.unquote(url_path.removeprefix("/static/"))
        target = (FRONTEND_DIR / rel).resolve()
        if FRONTEND_DIR not in target.parents:
            self.not_found()
            return
        self.serve_file(target)

    def serve_media(self, user: sqlite3.Row, url_path: str) -> None:
            rel = urllib.parse.unquote(url_path.removeprefix("/media/"))
            target = (STORAGE_DIR / rel).resolve()

            # Block path traversal, for example /media/../../secret.
            if STORAGE_DIR not in target.parents:
                self.not_found()
                return

            media_url = public_url(target)

            with connect() as conn:
                row = conn.execute(
                    """
                    SELECT id FROM files
                    WHERE owner_id = ?
                    AND (original_url = ? OR thumbnail_url = ?)
                    """,
                    (user["id"], media_url, media_url),
                ).fetchone()

            # Return 404 instead of 403 to avoid leaking whether another user's file exists.
            if row is None:
                self.not_found()
                return

            self.serve_file(target)

    def not_found(self) -> None:
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def current_user(self) -> sqlite3.Row | None:
            cookie_token = parse_cookies(self.headers.get("Cookie")).get(AUTH_COOKIE)
            bearer_token = None

            auth = self.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                bearer_token = auth.removeprefix("Bearer ").strip()

            with connect() as conn:
                # Local demo session cookie.
                if cookie_token:
                    user = conn.execute(
                        """
                        SELECT users.* FROM users
                        JOIN sessions ON sessions.user_id = users.id
                        WHERE sessions.token = ?
                        """,
                        (cookie_token,),
                    ).fetchone()
                    if user is not None:
                        return user

                # Bearer may be a local session token returned by /api/auth/login.
                if bearer_token:
                    user = conn.execute(
                        """
                        SELECT users.* FROM users
                        JOIN sessions ON sessions.user_id = users.id
                        WHERE sessions.token = ?
                        """,
                        (bearer_token,),
                    ).fetchone()
                    if user is not None:
                        return user

                    # Cognito JWT path: verify signature, issuer, audience/client_id and expiry.
                    try:
                        validated = validate_cognito_jwt(bearer_token, expected_token_use=None)
                    except AuthError:
                        return None

                    return get_or_create_cognito_user(conn, validated.raw_claims)

            return None



    def require_auth(self, handler) -> None:
        user = self.current_user()
        if user is None:
            self.send_json({"error": "Authentication required"}, HTTPStatus.UNAUTHORIZED)
            return
        handler(user)

    def handle_me(self) -> None:
        user = self.current_user()
        if user is None:
            self.send_json({"authenticated": False})
            return
        self.send_json({
            "authenticated": True,
            "user": {
                "email": user["email"],
                "firstName": user["first_name"],
                "lastName": user["last_name"],
            },
        })

    def handle_config(self) -> None:
        self.send_json(
            {
                "authMode": os.environ.get("AUTH_MODE", "local"),
                "cognito": {
                    "region": COGNITO_REGION,
                    "userPoolId": COGNITO_USER_POOL_ID,
                    "appClientId": COGNITO_APP_CLIENT_ID,
                    "domain": COGNITO_DOMAIN,
                    "redirectUri": COGNITO_REDIRECT_URI,
                    "jwksUrl": JWKS_URL,
                    "loginUrl": cognito_login_url(),
                },
            }
        )

    def handle_signup(self) -> None:
        data = self.read_json()
        required = ["email", "firstName", "lastName", "password"]
        if any(not data.get(key) for key in required):
            self.send_json({"error": "Missing signup fields"}, HTTPStatus.BAD_REQUEST)
            return
        try:
            with connect() as conn:
                conn.execute(
                    "INSERT INTO users(email, first_name, last_name, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        data["email"].strip().lower(),
                        data["firstName"].strip(),
                        data["lastName"].strip(),
                        hash_password(data["password"]),
                        now(),
                    ),
                )
            self.send_json({"message": "Account created. In AWS deployment Cognito sends the verification email."}, 201)
        except sqlite3.IntegrityError:
            self.send_json({"error": "Email already registered"}, HTTPStatus.CONFLICT)

    def handle_login(self) -> None:
        data = self.read_json()
        with connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE email = ?", (data.get("email", "").strip().lower(),)).fetchone()
            if user is None or not verify_password(data.get("password", ""), user["password_hash"]):
                self.send_json({"error": "Invalid email or password"}, HTTPStatus.UNAUTHORIZED)
                return
            token = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions(token, user_id, created_at) VALUES (?, ?, ?)", (token, user["id"], now()))
        cookie = f"{AUTH_COOKIE}={urllib.parse.quote(token)}; Path=/; SameSite=Lax"
        self.send_json({"message": "Logged in", "token": token}, cookies=[cookie])

    def handle_cognito_exchange(self) -> None:
            data = self.read_json()
            code = data.get("code")
            if not code:
               self.send_json({"error": "Cognito authorisation code is required"}, HTTPStatus.BAD_REQUEST)
               return

            try:
               tokens = exchange_cognito_code(code)
               id_token = tokens.get("id_token")
               if not id_token:
                  self.send_json({"error": "Cognito id_token was not returned"}, HTTPStatus.BAD_REQUEST)
                  return

               validated = validate_cognito_jwt(id_token, expected_token_use="id")
               claims = validated.raw_claims
            except AuthError as exc:
                self.send_json({"error": f"Cognito token validation failed: {exc.message}"}, HTTPStatus.UNAUTHORIZED)
                return
            except Exception as exc:
                self.send_json({"error": f"Cognito token exchange failed: {exc}"}, HTTPStatus.BAD_REQUEST)
                return

            with connect() as conn:
                user = get_or_create_cognito_user(conn, claims)
                token = secrets.token_urlsafe(32)
                conn.execute(
                    "INSERT INTO sessions(token, user_id, created_at) VALUES (?, ?, ?)",
                    (token, user["id"], now()),
                )

            cookie = f"{AUTH_COOKIE}={urllib.parse.quote(token)}; Path=/; HttpOnly; SameSite=Lax"
            self.send_json(
                {
                    "message": "Logged in with Cognito",
                    "token": token,
                    "cognitoClaims": {
                        "ownerId": claims.get("sub"),
                        "email": claims.get("email", ""),
                    },
                },
                cookies=[cookie],
            )

    def handle_logout(self) -> None:
        token = parse_cookies(self.headers.get("Cookie")).get(AUTH_COOKIE)
        if token:
            with connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self.send_json({"message": "Logged out"}, cookies=[f"{AUTH_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax"])

    def handle_upload(self, user: sqlite3.Row) -> None:
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        item = form["file"] if "file" in form else None
        if item is None or not getattr(item, "filename", ""):
            self.send_json({"error": "File is required"}, HTTPStatus.BAD_REQUEST)
            return
        original_name = Path(item.filename).name
        suffix = Path(original_name).suffix.lower()
        tmp_path = QUERY_TMP_DIR / f"upload-{secrets.token_hex(8)}{suffix}"
        with tmp_path.open("wb") as f:
            shutil.copyfileobj(item.file, f)
        checksum = file_checksum(tmp_path)
        with connect() as conn:
            existing = conn.execute(
                "SELECT id FROM files WHERE checksum = ? AND owner_id = ?",
                (checksum, user["id"]),
            ).fetchone()
            if existing:
               tmp_path.unlink(missing_ok=True)
               self.send_json({
                   "duplicate": True,
                   "file": get_file_with_tags(conn, existing["id"], user["id"]),
               })
               return

            file_type = "image" if suffix in IMAGE_EXTENSIONS else "video" if suffix in VIDEO_EXTENSIONS else "other"
            stored_name = f"{checksum[:16]}-{original_name}"
            final_path = ORIGINALS_DIR / stored_name
            shutil.move(str(tmp_path), final_path)
            thumb_url = None
            if file_type == "image":
                thumb_path = THUMBNAILS_DIR / f"{Path(stored_name).stem}.jpg"
                if create_thumbnail(final_path, thumb_path):
                    thumb_url = public_url(thumb_path)
            tags = detect_species_from_name(original_name)
            cursor = conn.execute(
                """
                INSERT INTO files(owner_id, original_name, stored_name, file_type, checksum, original_url, thumbnail_url, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (user["id"], original_name, stored_name, file_type, checksum, public_url(final_path), thumb_url, now()),
            )
            file_id = cursor.lastrowid
            for tag, count in tags.items():
                conn.execute("INSERT INTO tags(file_id, tag, count, source) VALUES (?, ?, ?, ?)", (file_id, tag, count, "auto"))
            self.create_notifications(conn, tags, public_url(final_path))
            created = get_file_with_tags(conn, file_id, user["id"])
        self.send_json({"duplicate": False, "file": created}, 201)

    def create_notifications(self, conn: sqlite3.Connection, tags: dict[str, int], file_url: str) -> None:
        for tag in tags:
            rows = conn.execute("SELECT user_id, email, tag FROM subscriptions WHERE tag = ?", (tag,)).fetchall()
            for row in rows:
                conn.execute(
                    "INSERT INTO notifications(user_id, email, tag, file_url, created_at) VALUES (?, ?, ?, ?, ?)",
                    (row["user_id"], row["email"], row["tag"], file_url, now()),
                )

    def handle_list_files(self, user: sqlite3.Row, query: str) -> None:
        with connect() as conn:
           rows = conn.execute(
               "SELECT * FROM files WHERE owner_id = ? ORDER BY created_at DESC",
               (user["id"],),
           ).fetchall()
           files = [get_file_with_tags(conn, row["id"], user["id"]) for row in rows]
        self.send_json({"files": files})

    def matching_files(self, user: sqlite3.Row, requested: dict[str, int]) -> list[dict[str, Any]]:
        with connect() as conn:
           rows = conn.execute(
               "SELECT * FROM files WHERE owner_id = ? ORDER BY created_at DESC",
               (user["id"],),
        ).fetchall()
        results = []
        for row in rows:
            file_obj = get_file_with_tags(conn, row["id"], user["id"])
            if file_obj is None:
                continue
            tags = file_obj["tags"]
            if all(tags.get(tag, 0) >= count for tag, count in requested.items()):
                results.append(file_obj)
        return results

    def handle_query_tags(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        requested = {str(k): int(v) for k, v in data.get("tags", data).items()}
        self.send_json({"results": self.matching_files(user, requested)})

    def handle_query_species(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        species = data.get("species") or data.get("tag")
        if not species:
            self.send_json({"error": "species is required"}, HTTPStatus.BAD_REQUEST)
            return
        self.send_json({"results": self.matching_files(user, {species: 1})})

    def handle_query_thumbnail(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        thumb_url = data.get("thumbnailUrl")
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM files WHERE thumbnail_url = ? AND owner_id = ?",
                (thumb_url, user["id"]),
            ).fetchone()
            if not row:
                self.send_json({"error": "Thumbnail not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_json({"file": get_file_with_tags(conn, row["id"], user["id"])})

    def handle_query_by_file(self, user: sqlite3.Row) -> None:
        form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST"})
        item = form["file"] if "file" in form else None
        if item is None or not getattr(item, "filename", ""):
            self.send_json({"error": "File is required"}, HTTPStatus.BAD_REQUEST)
            return
        tags = detect_species_from_name(Path(item.filename).name)
        self.send_json({
            "detectedTags": tags,
            "results": self.matching_files(user, {tag: 1 for tag in tags}),
        })

    def handle_bulk_tags(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        urls = data.get("urls", [])
        tags = data.get("tags", [])
        operation = int(data.get("operation", 1))
        with connect() as conn:
            changed = 0
            for url in urls:
                row = conn.execute(
                    "SELECT id FROM files WHERE owner_id = ? AND (original_url = ? OR thumbnail_url = ?)",
                    (user["id"], url, url),
                ).fetchone()
                if not row:
                    continue
                for tag in tags:
                    if operation == 1:
                        conn.execute(
                            """
                            INSERT INTO tags(file_id, tag, count, source) VALUES (?, ?, 1, 'manual')
                            ON CONFLICT(file_id, tag) DO UPDATE SET count = count + 1, source = 'manual'
                            """,
                            (row["id"], tag),
                        )
                    else:
                        conn.execute("DELETE FROM tags WHERE file_id = ? AND tag = ?", (row["id"], tag))
                    changed += 1
        self.send_json({"message": "Tags updated", "changes": changed})

    def handle_delete_files(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        urls = data.get("urls", [])
        deleted = 0
        with connect() as conn:
            for url in urls:
                row = conn.execute(
                    "SELECT * FROM files WHERE owner_id = ? AND (original_url = ? OR thumbnail_url = ?)",
                    (user["id"], url, url),
                ).fetchone()
                if not row:
                    continue
                for media_url in [row["original_url"], row["thumbnail_url"]]:
                    if media_url:
                        rel = urllib.parse.unquote(media_url.removeprefix("/media/"))
                        (STORAGE_DIR / rel).unlink(missing_ok=True)
                conn.execute("DELETE FROM tags WHERE file_id = ?", (row["id"],))
                conn.execute("DELETE FROM files WHERE id = ?", (row["id"],))
                deleted += 1
        self.send_json({"message": "Files deleted", "deleted": deleted})

    def handle_subscribe(self, user: sqlite3.Row) -> None:
        data = self.read_json()
        email = data.get("email") or user["email"]
        tag = data.get("tag")
        if not tag:
            self.send_json({"error": "tag is required"}, HTTPStatus.BAD_REQUEST)
            return
        with connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO subscriptions(user_id, email, tag, created_at) VALUES (?, ?, ?, ?)",
                (user["id"], email, tag, now()),
            )
        self.send_json({"message": "Subscription saved. In AWS deployment this maps to SNS email subscription."})

    def handle_notifications(self, user: sqlite3.Row) -> None:
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
                (user["id"],),
            ).fetchall()
        self.send_json({"notifications": [dict(row) for row in rows]})


def main() -> None:
    init_db()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer((host, port), EcoLensHandler)
    print(f"Aussie EcoLens running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
