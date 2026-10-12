"""Fictional profiles from docs/scenarios.md; never stores disease names."""
import argparse
from src.db.database import Database

PROFILES = (
    dict(profile_id='profile-01', age=84, lives_alone=True, has_condition=True, mobility_limited=True, area='서울시 강남구'),
    dict(profile_id='profile-02', age=78, lives_alone=True, has_condition=False, mobility_limited=False, area='서울시 송파구'),
    dict(profile_id='profile-03', age=70, lives_alone=True, has_condition=False, mobility_limited=False, area='서울시 서초구'),
    # 기화 10/12: 시연 영상의 네 번째 보호자 계정(자녀 D)이 보는 어르신 D. 취약도 상
    dict(profile_id='profile-04', age=86, lives_alone=True, has_condition=True, mobility_limited=True, area='서울시 강남구'),
)


def seed_profiles(db, *, overwrite=False):
    db.seed_profiles(PROFILES, overwrite=overwrite)
    # Only fill missing areas of known demo profiles; keep existing custom regions.
    with db.connect() as conn:
        for profile in PROFILES:
            conn.execute("UPDATE profiles SET area=? WHERE profile_id=? AND (area IS NULL OR trim(area)='')",
                         (profile['area'], profile['profile_id']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Seed fictional demonstration profiles')
    parser.add_argument('--overwrite', action='store_true', help='Explicitly refresh the four demo profiles')
    seed_profiles(Database(), overwrite=parser.parse_args().overwrite)
