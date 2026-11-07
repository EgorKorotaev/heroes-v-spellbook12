"""Convenient clean-clone entry point; requires only the pinned Python dependency."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'src'))
from spellbook12.build import main

if __name__=='__main__':main()
