from typing import Annotated

from pydantic import BaseModel


class DatabaseSchema(BaseModel):
    host: Annotated[str, "The IP address or host name of the PostgreSQL server"] = (
        "localhost"
    )
    port: Annotated[int, "The port that the PostgreSQL service is running on"] = 5432
    user: Annotated[str, "The PostgreSQL role to connect as"] = "postgres"
    password: Annotated[str, "The password for the role"] = "postgres"
    database: Annotated[str, "The database to connect to"] = "bhoonidhi"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self.user}:{self.password}@"
            f"{self.host}:{self.port}/{self.database}"
        )
