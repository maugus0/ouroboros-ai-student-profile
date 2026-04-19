-- Migration 006: Profile Versions (source of truth for complete profile state)
-- Depends on: student_profiles

CREATE TABLE IF NOT EXISTS profile_versions (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,
    version_number INT NOT NULL,
    profile_json JSON NOT NULL COMMENT 'Complete profile: confidence_map, evidence_map, react_decision_trace, clarification_queue, etc.',
    change_reason VARCHAR(100) NULL COMMENT 'initial_parse, profile_update, clarification_submit',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    UNIQUE KEY uq_profile_version (profile_id, version_number),
    INDEX idx_profile_versions (profile_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
