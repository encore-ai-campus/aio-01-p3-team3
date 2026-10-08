"""Adapters for the ingestion API; no public HTTP model or id-generation policy."""
from src.db.vital_readings import VitalReadings


class VitalService:
    def __init__(self, db):
        self.repository = VitalReadings(db)

    def save_vital_reading(self, reading: dict) -> int:
        """Internal input: profile_id, reading_id, VitalData fields, optional scenario.

        API maps its validated DTO to this input. Retransmissions reuse reading_id.
        Returns the same database id for inserted and duplicate readings.
        """
        result = self.repository.save(reading_id=reading['reading_id'],
            profile_id=reading['profile_id'], scenario=reading.get('scenario'), data=reading)
        return result['id']

    def get_latest_vital_reading(self, profile_id: str, *, max_age_seconds: float,
                               scenario: str | None = None) -> dict | None:
        result = self.repository.latest(profile_id, scenario=scenario, max_age_s=max_age_seconds)
        return result['data'] if result is not None else None
