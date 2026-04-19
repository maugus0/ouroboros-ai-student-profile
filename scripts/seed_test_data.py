"""Seed the database with sample student profile data for development."""

import json
import sys
import uuid
from pathlib import Path

import mysql.connector
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import settings  # noqa: E402

load_dotenv(ROOT_DIR / ".env")


def get_connection():
    return mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
        charset="utf8mb4",
        collation="utf8mb4_unicode_ci",
    )


SAMPLE_PROFILES = [
    {
        "full_name": "Alice Johnson",
        "email": "alice.johnson@example.com",
        "target_degree_level": "master",
        "target_degree_confidence": 0.85,
        "target_degree_source": "cv_explicit",
        "gpa": 3.7,
        "gpa_scale": 4.0,
        "profile_json": {
            "full_name": "Alice Johnson",
            "email": "alice.johnson@example.com",
            "education": [
                {"institution": "State University", "degree": "BSc Computer Science", "gpa": 3.7}
            ],
            "technical_skills": ["Python", "Machine Learning", "SQL"],
        },
    },
    {
        "full_name": "Bob Chen",
        "email": "bob.chen@example.com",
        "target_degree_level": "phd",
        "target_degree_confidence": 0.72,
        "target_degree_source": "trajectory_inference",
        "gpa": 3.9,
        "gpa_scale": 4.0,
        "profile_json": {
            "full_name": "Bob Chen",
            "email": "bob.chen@example.com",
            "education": [
                {"institution": "Tech University", "degree": "MSc AI", "gpa": 3.9}
            ],
            "research_experience": [
                {"title": "NLP for Low-Resource Languages", "role": "Research Assistant"}
            ],
        },
    },
]


def seed():
    conn = get_connection()
    cursor = conn.cursor()

    for profile in SAMPLE_PROFILES:
        pid = str(uuid.uuid4())
        cursor.execute(
            """
            INSERT INTO student_profiles (
                id, full_name, email, target_degree_level,
                target_degree_confidence, target_degree_source,
                gpa, gpa_scale, profile_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                pid,
                profile["full_name"],
                profile["email"],
                profile["target_degree_level"],
                profile["target_degree_confidence"],
                profile["target_degree_source"],
                profile["gpa"],
                profile["gpa_scale"],
                json.dumps(profile["profile_json"]),
            ),
        )
        print(f"  Seeded profile id: {pid}")

    conn.commit()
    cursor.close()
    conn.close()
    print("\nSeed data inserted successfully.")


if __name__ == "__main__":
    seed()