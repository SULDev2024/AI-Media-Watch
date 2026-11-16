"""Start the local API, applying packaged database migrations first."""
import os
from pathlib import Path

from dotenv import load_dotenv

if __name__ == "__main__":
    os.chdir(Path(__file__).resolve().parent)
    load_dotenv()
    from aimw.core.config import get_settings
    from aimw.db.migrate import upgrade
    from aimw.api.server import main

    get_settings().resolved_data_dir.mkdir(parents=True, exist_ok=True)
    upgrade("head")
    main(reload=False)
