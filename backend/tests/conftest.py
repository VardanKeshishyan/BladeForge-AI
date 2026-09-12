import os
import tempfile
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_JWT_ISSUER", "https://example.supabase.co/auth/v1")
os.environ.setdefault(
    "SUPABASE_JWKS_URL", "https://example.supabase.co/auth/v1/.well-known/jwks.json"
)
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:65432/postgres"
)
os.environ.setdefault("WORKER_SECRET", "worker-secret-that-is-long-enough-for-tests")
os.environ.setdefault("API_KEY_PEPPER", "api-key-pepper-that-is-long-enough-for-tests")

# Some managed Windows profiles deny access to the shared %TEMP% root, which breaks
# pytest's tmp_path factory. Keep scratch files inside the git-ignored backend/var tree.
_SCRATCH_ROOT = Path(__file__).resolve().parents[1] / "var" / "pytest-scratch-v2"
try:
    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    (_SCRATCH_ROOT / ".writable").write_text("ok", encoding="utf-8")
except OSError:  # pragma: no cover - fall back to the platform default
    pass
else:
    tempfile.tempdir = str(_SCRATCH_ROOT)
    for _variable in ("TMPDIR", "TEMP", "TMP"):
        os.environ[_variable] = str(_SCRATCH_ROOT)
