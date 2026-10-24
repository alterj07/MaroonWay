"""Collect all pages of campus-verified RMP rosters; resume automatically."""
import argparse
from build_dataset import Client, collect_rosters

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    profs = collect_rosters(Client(), args.refresh)
    print(f'Cached {len(profs)} campus-verified professor profiles.')
