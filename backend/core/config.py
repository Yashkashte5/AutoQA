from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str
    postgres_url: str
    redis_url: str
    rabbitmq_url: str
    mlflow_tracking_uri: str
    secret_key: str = "changeme"

    class Config:
        env_file = ".env"

settings = Settings()
