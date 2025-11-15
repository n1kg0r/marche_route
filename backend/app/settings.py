from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    MISTRAL_API_KEY: str

    class Config:
        env_file = ".env"   # dotenv is one level up

settings = Settings()
