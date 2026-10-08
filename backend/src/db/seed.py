"""Fictional profiles from docs/scenarios.md; never stores disease names."""
import argparse
from src.db.database import Database

PROFILES = (
    dict(profile_id='profile-01', age=84, lives_alone=True, has_condition=True, mobility_limited=True),
    dict(profile_id='profile-02', age=78, lives_alone=True, has_condition=False, mobility_limited=False),
    dict(profile_id='profile-03', age=70, lives_alone=True, has_condition=False, mobility_limited=False),
)


def seed_profiles(db, *, overwrite=False):
    db.seed_profiles(PROFILES, overwrite=overwrite)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seed fictional demonstration profiles')
    parser.add_argument('--overwrite', action='store_true', help='Explicitly refresh the three demo profiles')
    seed_profiles(Database(), overwrite=parser.parse_args().overwrite)
