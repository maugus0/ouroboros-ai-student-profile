"""Seed sample student profiles for local development.

The seeded ``user_id`` values match ``orchestrator/scripts/seed_users.py`` so
local login accounts have ready-to-use discovery profiles.
"""

import json
import sys
from pathlib import Path

import aiomysql
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings  # noqa: E402

load_dotenv(ROOT_DIR / ".env")


async def get_connection():
    return await aiomysql.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        db=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
        charset="utf8mb4",
        autocommit=False,
    )


SAMPLE_PROFILES = [
    {
        "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "version_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
        "user_id": "11111111-1111-4111-8111-111111111111",
        "full_name": "Ahan Jaiswal",
        "email": "ahanjaiswal12@gmail.com",
        "nationality": "India",
        "current_degree_level": "bachelor",
        "target_degree_level": "master",
        "target_degree_confidence": 1.0,
        "target_degree_source": "user_input",
        "gpa": 3.7,
        "gpa_scale": 4.0,
        "gpa_normalized": 3.7,
        "profile_json": {
            "full_name": "Ahan Jaiswal",
            "email": "ahanjaiswal12@gmail.com",
            "nationality": "India",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
            "intended_field_of_study": "Computer Science",
            "target_study_country": "United States",
            "enrollment_timeline": "Fall 2026",
            "funding_source": "scholarship",
            "technical_skills": ["Python", "Machine Learning", "SQL"],
            "education": [{"institution": "State University", "degree": "BSc Computer Science", "gpa": 3.7}],
            "confidence_map": {
                "full_name": 1.0,
                "email": 1.0,
                "nationality": 1.0,
                "current_degree_level": 1.0,
                "target_degree_level": 1.0,
                "gpa": 1.0,
                "gpa_scale": 1.0,
                "intended_field_of_study": 1.0,
                "target_study_country": 1.0,
                "enrollment_timeline": 1.0,
                "funding_source": 1.0,
            },
            "clarification_queue": [],
        },
    },
    {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "version_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "user_id": "22222222-2222-4222-8222-222222222222",
        "full_name": "Phu Truong Nguyen",
        "email": "phu@gmail.com",
        "nationality": "Singapore",
        "current_degree_level": "bachelor",
        "target_degree_level": "master",
        "target_degree_confidence": 1.0,
        "target_degree_source": "user_input",
        "gpa": 3.85,
        "gpa_scale": 4.0,
        "gpa_normalized": 3.85,
        "profile_json": {
            "full_name": "Phu Truong Nguyen",
            "email": "phu@gmail.com",
            "nationality": "Singapore",
            "current_degree_level": "bachelor",
            "target_degree_level": "master",
            "intended_field_of_study": "Artificial Intelligence",
            "target_study_country": "United Kingdom",
            "enrollment_timeline": "Fall 2026",
            "funding_source": "self_funded",
            "technical_skills": ["Python", "Deep Learning", "Data Engineering"],
            "education": [{"institution": "Local University", "degree": "BSc Computer Science", "gpa": 3.85}],
            "confidence_map": {
                "full_name": 1.0,
                "email": 1.0,
                "nationality": 1.0,
                "current_degree_level": 1.0,
                "target_degree_level": 1.0,
                "gpa": 1.0,
                "gpa_scale": 1.0,
                "intended_field_of_study": 1.0,
                "target_study_country": 1.0,
                "enrollment_timeline": 1.0,
                "funding_source": 1.0,
            },
            "clarification_queue": [],
        },
    },
]


async def upsert_profile(cursor, profile: dict) -> str:
    await cursor.execute("SELECT id FROM student_profiles WHERE user_id = %s LIMIT 1", (profile["user_id"],))
    row = await cursor.fetchone()
    profile_id = row[0] if row else profile["id"]

    if row:
        await cursor.execute(
            """
            UPDATE student_profiles
            SET full_name = %s,
                email = %s,
                nationality = %s,
                current_degree_level = %s,
                target_degree_level = %s,
                target_degree_confidence = %s,
                target_degree_source = %s,
                target_degree_needs_clarification = FALSE,
                gpa = %s,
                gpa_scale = %s,
                gpa_normalized = %s,
                profile_version = 1,
                profile_prompt_version = 'seed_test_data_v1',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (
                profile["full_name"],
                profile["email"],
                profile["nationality"],
                profile["current_degree_level"],
                profile["target_degree_level"],
                profile["target_degree_confidence"],
                profile["target_degree_source"],
                profile["gpa"],
                profile["gpa_scale"],
                profile["gpa_normalized"],
                profile_id,
            ),
        )
    else:
        await cursor.execute(
            """
            INSERT INTO student_profiles (
                id, user_id, full_name, email, nationality,
                current_degree_level, target_degree_level, target_degree_confidence,
                target_degree_source, target_degree_needs_clarification,
                gpa, gpa_scale, gpa_normalized, profile_version, profile_prompt_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s, %s, %s, 1, 'seed_test_data_v1')
            """,
            (
                profile_id,
                profile["user_id"],
                profile["full_name"],
                profile["email"],
                profile["nationality"],
                profile["current_degree_level"],
                profile["target_degree_level"],
                profile["target_degree_confidence"],
                profile["target_degree_source"],
                profile["gpa"],
                profile["gpa_scale"],
                profile["gpa_normalized"],
            ),
        )

    await cursor.execute(
        """
        INSERT INTO profile_versions (id, profile_id, version_number, profile_json, change_reason)
        VALUES (%s, %s, 1, %s, 'seed_test_data')
        ON DUPLICATE KEY UPDATE profile_json = VALUES(profile_json), change_reason = VALUES(change_reason)
        """,
        (
            profile["version_id"],
            profile_id,
            json.dumps(profile["profile_json"]),
        ),
    )
    return profile_id


async def seed():
    conn = await get_connection()
    cursor = await conn.cursor()

    for profile in SAMPLE_PROFILES:
        profile_id = await upsert_profile(cursor, profile)
        print(f"  Seeded profile id: {profile_id} for user_id: {profile['user_id']}")

    await conn.commit()
    await cursor.close()
    conn.close()
    print("\nSeed data inserted successfully.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(seed())
