"""Paths and the hand-edited configuration living in ``info/``."""

from __future__ import annotations

import os
import shutil
import sys
import threading
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on 3.10
    import tomli as tomllib

CONFIG_FILENAME = "config.toml"
DB_FILENAME = "pamela.sqlite3"


@dataclass(frozen=True)
class Settings:
    """Filesystem locations used by the app.

    Defaults are ``./local`` and ``./info`` relative to the working directory,
    overridable with the ``PAMELA_LOCAL_DIR`` / ``PAMELA_INFO_DIR`` env vars.
    """

    local_dir: Path
    info_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        cwd = Path.cwd()
        return cls(
            local_dir=Path(os.environ.get("PAMELA_LOCAL_DIR", cwd / "local")),
            info_dir=Path(os.environ.get("PAMELA_INFO_DIR", cwd / "info")),
        )

    @property
    def db_path(self) -> Path:
        return self.local_dir / DB_FILENAME

    @property
    def config_path(self) -> Path:
        return self.info_dir / CONFIG_FILENAME


class Profile(BaseModel):
    name: str = "Me"
    weight_kg: float = Field(75.0, gt=0, le=500)


class Targets(BaseModel):
    kcal: float = Field(2200, ge=0)
    protein_g: float = Field(150, ge=0)
    carbs_g: float = Field(230, ge=0)
    fat_g: float = Field(70, ge=0)
    fiber_g: float = Field(30, ge=0)


class Meals(BaseModel):
    names: list[str] = Field(default_factory=lambda: ["Breakfast", "Lunch", "Snack", "Dinner"])

    @field_validator("names")
    @classmethod
    def _non_empty_unique(cls, v: list[str]) -> list[str]:
        cleaned = [n.strip() for n in v if n.strip()]
        if not cleaned:
            raise ValueError("at least one meal name is required")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("meal names must be unique")
        return cleaned


class ActivityType(BaseModel):
    name: str = Field(min_length=1)
    met: float = Field(gt=0, le=30)
    distance: bool = False


class AppConfig(BaseModel):
    profile: Profile = Field(default_factory=Profile)
    targets: Targets = Field(default_factory=Targets)
    meals: Meals = Field(default_factory=Meals)
    activity_types: list[ActivityType] = Field(default_factory=list)

    def activity_type(self, name: str) -> ActivityType | None:
        for t in self.activity_types:
            if t.name.lower() == name.lower():
                return t
        return None


class ConfigError(Exception):
    """Raised when ``info/config.toml`` cannot be parsed or validated."""


def default_config_text() -> str:
    return resources.files("pamela").joinpath("defaults", CONFIG_FILENAME).read_text("utf-8")


def ensure_config_file(path: Path) -> None:
    """Create ``path`` from the bundled template if it doesn't exist yet."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(resources.files("pamela").joinpath("defaults", CONFIG_FILENAME)) as src:
        shutil.copyfile(src, path)


def parse_config(text: str, source: str = CONFIG_FILENAME) -> AppConfig:
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{source}: invalid TOML: {e}") from e
    try:
        return AppConfig.model_validate(data)
    except ValidationError as e:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ConfigError(f"{source}: {problems}") from e


class ConfigStore:
    """Loads the config file and reloads it whenever it changes on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int] | None = None
        self._config: AppConfig | None = None

    def get(self) -> AppConfig:
        with self._lock:
            ensure_config_file(self.path)
            st = self.path.stat()
            stamp = (st.st_mtime_ns, st.st_size)
            if self._config is None or stamp != self._stamp:
                text = self.path.read_text("utf-8")
                self._config = parse_config(text, source=str(self.path))
                self._stamp = stamp
            return self._config
