import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs):
        return False


load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(os.getenv("PROJECT_ROOT") or os.getenv("DIR_WORK") or _REPO_ROOT).expanduser()
PROJECT_ROOT = PROJECT_ROOT.resolve()

DIR_WORK = PROJECT_ROOT
DATA_DIR = Path(os.getenv("DATA_DIR") or PROJECT_ROOT / "data").expanduser().resolve()
DOCS_DIR = Path(os.getenv("DOCS_DIR") or PROJECT_ROOT / "docs").expanduser().resolve()
PAPER_DIR = Path(
    os.getenv("PAPER_DIR") or os.getenv("DOC_DIR") or PROJECT_ROOT / "doc"
).expanduser()
PAPER_DIR = PAPER_DIR.resolve()
DOC_DIR = PAPER_DIR
DIR_MANUSCRIPT = Path(
    os.getenv("DIR_MANUSCRIPT") or PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_manuscript"
).expanduser()
DIR_MANUSCRIPT = DIR_MANUSCRIPT.resolve()
ARTIFACTS_DIR = (
    Path(os.getenv("ARTIFACTS_DIR") or PROJECT_ROOT / "artifacts").expanduser().resolve()
)
PUBLIC_DATA_DIR = Path(os.getenv("PUBLIC_DATA_DIR") or DATA_DIR / "public").expanduser().resolve()
SEC_DATA_DIR = Path(os.getenv("SEC_DATA_DIR") or PUBLIC_DATA_DIR / "sec").expanduser().resolve()
PCAOB_DATA_DIR = (
    Path(os.getenv("PCAOB_DATA_DIR") or PUBLIC_DATA_DIR / "pcaob").expanduser().resolve()
)
DEFAULT_CONFIG_PATH = (
    Path(os.getenv("DEFAULT_CONFIG_PATH") or PROJECT_ROOT / "config" / "data_prep.yaml")
    .expanduser()
    .resolve()
)
RAW_DATASET_PATH = (
    Path(os.getenv("RAW_DATASET_PATH") or DATA_DIR / "raw_dataset_misstatement.csv")
    .expanduser()
    .resolve()
)
SAMPLE_DATASET_PATH = (
    Path(os.getenv("SAMPLE_DATASET_PATH") or ARTIFACTS_DIR / "sample_dataset_misstatement.csv")
    .expanduser()
    .resolve()
)
SEED_DEFAULT = int(os.getenv("SEED_DEFAULT", "42"))


if __name__ == "__main__":
    print("PROJECT_ROOT:", PROJECT_ROOT)
    print("DIR_WORK:", DIR_WORK)
    print("DATA_DIR:", DATA_DIR)
    print("DOCS_DIR:", DOCS_DIR)
    print("PAPER_DIR:", PAPER_DIR)
    print("DIR_MANUSCRIPT:", DIR_MANUSCRIPT)
    print("ARTIFACTS_DIR:", ARTIFACTS_DIR)
    print("PUBLIC_DATA_DIR:", PUBLIC_DATA_DIR)
    print("SEC_DATA_DIR:", SEC_DATA_DIR)
    print("PCAOB_DATA_DIR:", PCAOB_DATA_DIR)
    print("SAMPLE_DATASET_PATH:", SAMPLE_DATASET_PATH)
    print("DEFAULT_CONFIG_PATH:", DEFAULT_CONFIG_PATH)
    print("SEED_DEFAULT:", SEED_DEFAULT)
