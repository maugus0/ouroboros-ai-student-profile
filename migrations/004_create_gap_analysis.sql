-- Migration 004: Gap Analysis Results
-- Lightweight readiness scan against baseline expectations

CREATE TABLE IF NOT EXISTS gap_analysis (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,
    target_degree_level ENUM('bachelor', 'master', 'phd') NOT NULL,

    -- Analysis results
    readiness_score DECIMAL(3,2) NULL COMMENT 'Overall readiness 0.00-1.00',
    gaps_identified JSON NOT NULL COMMENT 'List of missing/weak signals',
    recommendations JSON NULL COMMENT 'Actionable suggestions',

    -- Metadata
    baseline_template VARCHAR(100) NULL COMMENT 'e.g., baseline_bachelor_v1',
    analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    INDEX idx_profile_degree (profile_id, target_degree_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
