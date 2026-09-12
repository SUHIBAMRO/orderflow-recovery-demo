import os
from .db import Database

if __name__ == "__main__":
    Database(os.environ["DATABASE_URL"]).initialize()
    print("Initial demo schema ready")
