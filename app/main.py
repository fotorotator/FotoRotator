"""Vstupny bod - spusti okno programu.

Volitelny argument: cesta k priecinku s fotkami (spracovanie sa potom
spusti automaticky - hodi sa napr. pri pretiahnuti priecinka na .exe).
Prepinac --use-claude-api zostava len kvoli kompatibilite - AI kontrola
sa teraz zapina automaticky, ked je ulozeny API kluc (v okne programu).
"""

import argparse
from pathlib import Path

from . import gui


def parse_args():
    parser = argparse.ArgumentParser(
        description="Otoci fotky z merania do landscape a vytiahne ID cisla zo stitku."
    )
    parser.add_argument("folder", nargs="?", help="Priecinok s fotkami (spusti spracovanie hned)")
    parser.add_argument("--use-claude-api", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main():
    args = parse_args()
    folder = Path(args.folder) if args.folder else None
    gui.run(initial_folder=folder, auto_start=folder is not None)


if __name__ == "__main__":
    main()
