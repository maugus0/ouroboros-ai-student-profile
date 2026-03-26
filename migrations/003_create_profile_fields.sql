-- Migration 003: Profile Fields table
-- Granular field-level storage for flexible updates

CREATE TABLE IF NOT EXISTS profile_fields (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,

    field_category ENUM('personal', 'academic', 'experience', 'skills', 'research', 'other') NOT NULL,
    field_name VARCHAR(100) NOT NULL COMMENT 'e.g., gpa, skills, work_experience',
    field_value JSON NOT NULL COMMENT 'Flexible payload for different field types',

    confidence_score DECIMAL(3,2) NULL,
    evidence_snippet TEXT NULL COMMENT 'Supporting text from document',
    source_document_id VARCHAR(36) NULL COMMENT 'Which document this field came from',

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    FOREIGN KEY (source_document_id) REFERENCES documents(id) ON DELETE SET NULL,
    INDEX idx_profile_category (profile_id, field_category),
    INDEX idx_field_name (field_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
