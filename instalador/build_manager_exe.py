from pathlib import Path
import os

import PyInstaller.__main__


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DIST_DIR = Path(os.getenv("HOMEWASH_MANAGER_DIST_DIR", str(SCRIPT_DIR / "dist"))).resolve()
WORK_DIR = Path(os.getenv("HOMEWASH_MANAGER_WORK_DIR", str(SCRIPT_DIR / "build"))).resolve()
APP_NAME = os.getenv("HOMEWASH_MANAGER_APP_NAME", "HomeWashManager").strip() or "HomeWashManager"


def main() -> None:
    PyInstaller.__main__.run(
        [
            "--noconfirm",
            "--clean",
            "--windowed",
            "--name",
            APP_NAME,
            "--paths",
            str(PROJECT_DIR),
            "--specpath",
            str(SCRIPT_DIR),
            "--distpath",
            str(DIST_DIR),
            "--workpath",
            str(WORK_DIR),
            "--hidden-import",
            "config_env",
            "--hidden-import",
            "remote_control",
            "--hidden-import",
            "theme",
            "--exclude-module",
            "streamlit",
            "--exclude-module",
            "pandas",
            "--exclude-module",
            "reportlab",
            "--exclude-module",
            "twilio",
            "--exclude-module",
            "google",
            "--exclude-module",
            "googleapiclient",
            "--exclude-module",
            "google_auth_oauthlib",
            "--exclude-module",
            "numpy",
            "--add-data",
            f"{PROJECT_DIR / 'iniciar_sistema.bat'};.",
            "--add-data",
            f"{PROJECT_DIR / 'iniciar_cloudflare_background.ps1'};.",
            "--add-data",
            f"{PROJECT_DIR / 'configurar_automacao.bat'};.",
            "--add-data",
            f"{PROJECT_DIR / 'config_env.py'};.",
            "--add-data",
            f"{PROJECT_DIR / 'assets'};assets",
            str(SCRIPT_DIR / "homewash_manager.py"),
        ]
    )


if __name__ == "__main__":
    main()