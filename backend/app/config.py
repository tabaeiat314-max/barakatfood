import os


class Settings:
    APP_NAME = "Barakat Food System"
    APP_VERSION = "1.0.0"
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://barakat:barakat_dev_password@localhost:5432/barakat"
    )
    BALE_BOT_TOKEN = os.getenv("BALE_BOT_TOKEN", "")


settings = Settings()
