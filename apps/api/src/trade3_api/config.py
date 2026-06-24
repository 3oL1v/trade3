from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_MARKET_ALLOWED_BASE_COINS = (
    "BTC",
    "ETH",
    "SOL",
    "XRP",
    "BNB",
    "DOGE",
    "ADA",
    "TRX",
    "HYPE",
    "LINK",
    "BCH",
    "XLM",
    "SUI",
    "AVAX",
    "LTC",
    "TON",
    "DOT",
    "UNI",
    "NEAR",
    "AAVE",
    "XMR",
    "ZEC",
    "ETC",
    "ONDO",
    "TAO",
    "WLD",
    "ENA",
    "1000PEPE",
    "APT",
    "ARB",
    "OP",
    "FIL",
    "ICP",
    "POL",
    "ATOM",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRADE3_",
        extra="ignore",
    )

    bybit_base_url: str = "https://api.bybit.com"
    bybit_ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    bybit_request_timeout_seconds: float = Field(default=10, gt=0, le=30)
    bybit_max_retries: int = Field(default=2, ge=0, le=5)
    bybit_http_proxy: str | None = None
    market_max_spread_bps: float = Field(default=15, gt=0, le=100)
    market_min_turnover_24h_usdt: float = Field(default=15_000_000, ge=0)
    market_min_open_interest_usdt: float = Field(default=5_000_000, ge=0)
    market_min_listing_age_days: int = Field(default=180, ge=0, le=3650)
    market_max_abs_funding_rate_pct: float = Field(default=0.10, gt=0, le=5)
    market_max_abs_price_change_24h_pct: float = Field(default=15, gt=0, le=100)
    market_allowed_base_coins: str = ",".join(DEFAULT_MARKET_ALLOWED_BASE_COINS)
    market_max_source_age_seconds: float = Field(default=120, gt=0, le=300)
    market_universe_size: int = Field(default=20, ge=1, le=50)
    live_market_data_enabled: bool = True
    live_max_message_age_seconds: float = Field(default=15, gt=0, le=120)
    live_max_clock_skew_seconds: float = Field(default=5, gt=0, le=60)
    intraday_max_candidate_spread_bps: float = Field(default=5, gt=0, le=25)
    intraday_candle_limit: int = Field(default=300, ge=60, le=500)
    intraday_universe_refresh_seconds: int = Field(default=1800, ge=300, le=86400)
    intraday_max_backfill_concurrency: int = Field(default=4, ge=1, le=10)
    journal_enabled: bool = False
    journal_database_path: str = "data/trade3_journal.sqlite3"
    journal_scan_seconds: float = Field(default=5, ge=2, le=60)
    journal_pending_expiry_hours: float = Field(default=6, gt=0, le=48)
    journal_active_expiry_hours: float = Field(default=24, gt=0, le=168)
    journal_taker_fee_rate_pct: float = Field(default=0.055, ge=0, le=1)
    journal_slippage_bps: float = Field(default=2, ge=0, le=100)
    journal_minimum_sample_size: int = Field(default=100, ge=20, le=1000)
    manual_journal_enabled: bool = True
    manual_journal_database_path: str = "data/trade3_manual_journal.sqlite3"
    decision_benchmark_symbol: str = "BTCUSDT"
    decision_horizon_hours: float = Field(default=8, gt=0, le=168)
    auto_signal_enabled: bool = True
    auto_signal_database_path: str = "data/trade3_auto_signals.sqlite3"
    auto_signal_universe_size: int = Field(default=15, ge=1, le=50)
    auto_signal_scan_seconds: float = Field(default=1800, ge=300, le=86400)
    auto_signal_horizon_hours: float = Field(default=8, gt=0, le=168)
    auto_signal_startup_delay_seconds: float = Field(default=60, ge=0, le=600)
    carry_test_enabled: bool = True
    carry_test_database_path: str = "data/trade3_carry_positions.sqlite3"
    carry_test_top_n: int = Field(default=5, ge=1, le=25)
    carry_test_scan_seconds: float = Field(default=28800, ge=3600, le=172800)
    carry_test_horizon_hours: float = Field(default=48, gt=0, le=336)
    carry_test_startup_delay_seconds: float = Field(default=90, ge=0, le=600)
    ollama_enabled: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:4b"
    ollama_timeout_seconds: float = Field(default=90, gt=0, le=300)
    ollama_analysis_cache_seconds: float = Field(default=60, ge=0, le=600)

    @field_validator("market_allowed_base_coins")
    @classmethod
    def normalize_market_allowed_base_coins(cls, value: str) -> str:
        coins = [coin.strip().upper() for coin in value.split(",") if coin.strip()]
        invalid = [coin for coin in coins if not coin.isalnum()]
        if invalid:
            raise ValueError(f"invalid base coin identifiers: {', '.join(invalid)}")
        return ",".join(dict.fromkeys(coins))

    def market_allowed_base_coin_set(self) -> set[str] | None:
        if not self.market_allowed_base_coins:
            return None
        return set(self.market_allowed_base_coins.split(","))


@lru_cache
def get_settings() -> Settings:
    return Settings()
