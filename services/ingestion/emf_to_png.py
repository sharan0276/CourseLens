import subprocess
from pathlib import Path
import shutil

def is_libreoffice_installed():
    return shutil.which("soffice") is not None

def emf_to_png(input_path, output_dir="."):
    if not is_libreoffice_installed():
        raise EnvironmentError(
            "LibreOffice is not installed or not in PATH.\n"
            "  macOS:  brew install --cask libreoffice\n"
            "  Linux:  sudo apt install libreoffice\n"
            "  Windows: https://www.libreoffice.org/download"
        )
    subprocess.run([
        "soffice", "--headless",
        "--convert-to", "png",
        "--outdir", output_dir,
        str(input_path)
    ], check=True)
    
emf_to_png('chap01_slide_3_image_575491.emf')