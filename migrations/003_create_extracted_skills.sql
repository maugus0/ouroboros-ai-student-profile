-- Migration 003: Extracted Skills (normalized queryable skill storage)
-- Depends on: student_profiles, documents

CREATE TABLE IF NOT EXISTS extracted_skills (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,
    raw_skill VARCHAR(255) NOT NULL,
    normalized_skill VARCHAR(255) NOT NULL,
    confidence_score DECIMAL(3,2) NULL,
    source_document_id VARCHAR(36) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE SET NULL,
    UNIQUE KEY uq_profile_skill (profile_id, normalized_skill),
    INDEX idx_profile_skill (profile_id),
    INDEX idx_normalized_skill (normalized_skill)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
