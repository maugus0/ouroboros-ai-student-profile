-- Migration 005: Experience Entries (normalized queryable work/research records)
-- Depends on: student_profiles, documents

CREATE TABLE IF NOT EXISTS experience_entries (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,
    experience_type ENUM('work', 'research') NOT NULL,
    organization VARCHAR(255) NULL,
    title VARCHAR(255) NOT NULL,
    role VARCHAR(255) NULL,
    start_date VARCHAR(40) NULL,
    end_date VARCHAR(40) NULL,
    description TEXT NULL,
    skills_used JSON NULL,
    publication_venue VARCHAR(255) NULL,
    evidence_snippet TEXT NULL,
    confidence_score DECIMAL(3,2) NULL,
    source_document_id VARCHAR(36) NULL,
    sort_index INT DEFAULT 0,
    entry_fingerprint CHAR(64) NULL COMMENT 'Deterministic hash for dedupe',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE SET NULL,
    UNIQUE KEY uq_profile_experience_fingerprint (profile_id, entry_fingerprint),
    INDEX idx_profile_experience (profile_id),
    INDEX idx_profile_experience_type (profile_id, experience_type),
    INDEX idx_profile_experience_sort (profile_id, sort_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
