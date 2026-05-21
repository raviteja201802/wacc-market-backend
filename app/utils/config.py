from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "WACC Market Database API"
    generated_excel_dir: Path = DATA_DIR / "generated_excel"
    backup_dir: Path = DATA_DIR / "backups"
    workbook_name: str = "WACC_MARKET_DATABASE.xlsx"
    universe_cache_file: Path = DATA_DIR / "universe_cache.csv"
    max_company_refresh: int = 0
    default_history_years: int = 5
    request_timeout_seconds: int = 30
    yahoo_retry_count: int = 2
    allowed_origins: list[str] = ["*"]

    @property
    def workbook_path(self) -> Path:
        return self.generated_excel_dir / self.workbook_name


settings = Settings()
settings.generated_excel_dir.mkdir(parents=True, exist_ok=True)
settings.backup_dir.mkdir(parents=True, exist_ok=True)
