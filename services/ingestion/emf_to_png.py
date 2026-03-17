import subprocess
from pathlib import Path
import shutil
import os
import platform
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def get_libreoffice_path():
    """Finds the LibreOffice executable depending on OS."""
    if shutil.which("soffice"):
        return "soffice"
    # MAC paths if not foudn in PATH
    if platform.system() == "Darwin":
        mac_paths = [
            "/opt/homebrew/bin/soffice",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        ]
        for path in mac_paths:
            if os.path.exists(path):
                return path
    return None

def convert_all_emfs_in_directory(images_dir: str):
    """
    Finds all .emf files in the given directory, converts them to .png 
    using LibreOffice, and then deletes the original .emf files.
    """
    soffice_cmd = get_libreoffice_path()
    if not soffice_cmd:
        raise EnvironmentError(
            "LibreOffice is not installed or not in PATH.\n"
            "  macOS:  brew install --cask libreoffice\n"
            "  Linux:  apt-get install -y libreoffice\n"
        )
    
    dir_path = Path(images_dir)
    if not dir_path.exists() or not dir_path.is_dir():
        logger.error(f"Directory not found: {images_dir}")
        return

    # Find all .emf files in the directory
    emf_files = list(dir_path.glob("*.emf"))
    
    if not emf_files:
        logger.info(f"No .emf files found in {images_dir} to convert.")
        return

    logger.info(f"Found {len(emf_files)} .emf files. Starting batch conversion...")

    # LibreOffice's --convert-to command actually accepts a glob pattern or multiple files directly
    # e.g., soffice --headless --convert-to png --outdir out/ *.emf
    try:
        # We pass the individual files to LibreOffice so it boots up its engine exactly once, 
        # converts all the files, and then closes. This is 10x faster than a python loop.
        logger.info("Running LibreOffice engine (this may take a moment to spin up)...")
        
        # Build the command using unpacked arguments instead of a shell wildcard
        command = [
            soffice_cmd, "--headless",
            "--convert-to", "png",
            "--outdir", str(dir_path)
        ] + [str(f) for f in emf_files]
        
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # After batch conversion, we verify and delete the original EMFs

        deleted = [f for f in emf_files if (dir_path / f"{f.stem}.png").exists()]
        failed = [f for f in emf_files if not (dir_path / f"{f.stem}.png").exists()]

        for emf_file in deleted:
            emf_file.unlink()
            
        logger.info(f"Deleted {len(deleted)} original .emf files.")
        
        if failed:
            logger.warning(f"Failed to convert {len(failed)} .emf files to .png for {[f.stem for f in failed]}")
               
    except subprocess.CalledProcessError as e:
        logger.error(f"Batch conversion failed with error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error during batch process: {e}")

    logger.info("Batch conversion complete.")

if __name__ == "__main__":
    # Point this to your images directory
    images_folder = "/Users/sharan/Desktop/CourseLens/CourseLens/CourseLens_data/images"
    convert_all_emfs_in_directory(images_folder)