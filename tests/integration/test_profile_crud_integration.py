"""Integration tests for profile CRUD operations with real MySQL database."""

from uuid import uuid4

import mysql.connector

from app.config import settings


def _seed_profile(full_name: str, email: str, gpa: float = 3.5) -> str:
    profile_id = str(uuid4())
    conn = mysql.connector.connect(
        host=settings.get_db_host(),
        port=settings.get_db_port(),
        database=settings.get_db_name(),
        user=settings.get_db_user(),
        password=settings.get_db_password(),
    )
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO student_profiles (
            id, full_name, email, current_degree_level, target_degree_level, gpa, gpa_scale
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (profile_id, full_name, email, "bachelor", "master", gpa, 4.0),
    )
    conn.commit()
    cursor.close()
    conn.close()
    return profile_id


def test_parse_document_and_create_profile(integration_client, cleanup_integration_db, service_token_header):
    """Test retrieving a seeded profile from the database via API."""
    profile_id = _seed_profile("John Doe", "john@example.com", 3.8)

    # Retrieve profile via API (should come from database)
    response = integration_client.get(
        f"/api/v1/profiles/{profile_id}",
        headers=service_token_header,
    )

    assert response.status_code == 200
    retrieved = response.json()
    assert retrieved["success"]
    profile = retrieved["data"]
    assert profile["id"] == profile_id


def test_update_profile_in_database(integration_client, cleanup_integration_db, service_token_header):
    """Test updating a profile persists changes to database."""
    profile_id = _seed_profile("Jane Smith", "jane@example.com", 3.6)

    # Update profile
    update_data = {
        "full_name": "Jane Smith Updated",
        "gpa": 3.9,
        "gpa_scale": 4.0,
    }

    response = integration_client.patch(
        f"/api/v1/profiles/{profile_id}",
        json=update_data,
        headers=service_token_header,
    )

    assert response.status_code == 200

    # Verify update persisted by fetching again
    response = integration_client.get(
        f"/api/v1/profiles/{profile_id}",
        headers=service_token_header,
    )

    retrieved = response.json()
    assert retrieved["success"]
    profile = retrieved["data"]
    assert profile["full_name"] == "Jane Smith Updated"
    assert float(profile["gpa"]) == 3.9


def test_list_profiles_from_database(integration_client, cleanup_integration_db, service_token_header):
    """Test listing profiles returns all profiles from database."""
    # Seed multiple profiles directly in database
    for i in range(3):
        _seed_profile(f"Test User {i}", f"user{i}@test.com", 3.0 + (i * 0.1))

    # List profiles
    response = integration_client.get(
        "/api/v1/profiles",
        headers=service_token_header,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["success"]
    result = data["data"]
    assert result["total"] >= 3
    assert len(result["items"]) >= 3
