import os
try:
    from pydantic_settings import BaseSettings
except ImportError:
    from pydantic import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Service configuration
    APP_NAME: str = "Benchmark Evaluation Service"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    
    # Server configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    
    # External services
    BENCHMARK_DEPLOY_URL: str = "" #"http://benchmark-deploy:8002"
    
    # GitHub configuration
    GITHUB_OWNER: str = ""
    GITHUB_REPO: str = ""
    GITHUB_CONFIG_PATH: str = ""
    GITHUB_TOKEN: str = ""  # Optional for public repos
    
    # Evaluation configuration
    EVALUATION_DELAY_MINUTES: int = 1
    
    # Logging configuration
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = Settings() 