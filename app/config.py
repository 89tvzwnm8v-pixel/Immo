from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    # Search settings
    search_interval_minutes: int = 30
    max_price: float = 600000
    min_size: float = 50
    min_rooms: float = 2
    frankfurt_districts: str = "Sachsenhausen,Westend,Bornheim,Nordend,Ostend,Innenstadt,Gallus,Bockenheim"

    # Email notifications
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    notify_email: str = "timoblache@t-online.de"

    # App settings
    base_url: str = "http://localhost:8000"
    secret_key: str = "changeme"
    database_url: str = "sqlite:///./immo.db"

    @property
    def districts_list(self) -> List[str]:
        return [d.strip() for d in self.frankfurt_districts.split(",") if d.strip()]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
