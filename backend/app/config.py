"""Server-only configuration. Environment variables override the local .env file."""
from dataclasses import dataclass, field
import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent


def read_local_env(path: Path) -> dict[str, str]:
    """Small literal KEY=value loader; no interpolation or shell execution."""
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().replace("_", "").isalnum():
            raise ValueError("Invalid .env entry; expected KEY=value")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


@dataclass(frozen=True)
class Settings:
    database_path: Path = BACKEND_ROOT / "data" / "crosslink.sqlite3"
    thingo_endpoint: str = ""
    thingo_model: str = ""
    thingo_api_key: str = field(default="", repr=False)
    thingo_protocol: str = ""

    @classmethod
    def load(cls) -> "Settings":
        local = read_local_env(PROJECT_ROOT / ".env")
        values = {**local, **os.environ}
        db_path = Path(values.get("CROSSLINK_DATABASE_PATH") or "backend/data/crosslink.sqlite3")
        if not db_path.is_absolute():
            db_path = PROJECT_ROOT / db_path
        return cls(
            database_path=db_path,
            thingo_endpoint=values.get("THINGO_API_ENDPOINT", "").strip(),
            thingo_model=values.get("THINGO_MODEL", "").strip(),
            thingo_api_key=local.get("THINGO_API_KEY", "").strip(),
            thingo_protocol=values.get("THINGO_PROTOCOL", "").strip(),
        )
