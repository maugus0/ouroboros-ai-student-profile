-- Migration 004: Education Entries (normalized queryable education records)
-- Depends on: student_profiles, documents

CREATE TABLE IF NOT EXISTS education_entries (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,
    institution VARCHAR(255) NOT NULL,
    degree VARCHAR(255) NOT NULL,
    field_of_study VARCHAR(255) NULL,
    start_date VARCHAR(40) NULL,
    end_date VARCHAR(40) NULL,
    gpa DECIMAL(4,2) NULL,
    gpa_scale DECIMAL(4,2) NULL,
    achievements JSON NULL,
    evidence_snippet TEXT NULL,
    confidence_score DECIMAL(3,2) NULL,
    source_document_id VARCHAR(36) NULL,
    sort_index INT DEFAULT 0,
    entry_fingerprint CHAR(64) NULL COMMENT 'Deterministic hash for dedupe',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE SET NULL,
    UNIQUE KEY uq_profile_education_fingerprint (profile_id, entry_fingerprint),
    INDEX idx_profile_education (profile_id),
    INDEX idx_profile_education_sort (profile_id, sort_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
