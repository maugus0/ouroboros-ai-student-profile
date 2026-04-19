-- Migration 001: Student Profiles (base table, no dependencies)
-- Lean schema - complete profile state is sourced from profile_versions

CREATE TABLE IF NOT EXISTS student_profiles (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    user_id VARCHAR(36) NULL,

    -- Personal Information
    full_name VARCHAR(255) NULL,
    email VARCHAR(255) NULL,
    phone VARCHAR(50) NULL,
    nationality VARCHAR(100) NULL,
    date_of_birth DATE NULL,

    -- Academic Information
    current_degree_level ENUM('high_school', 'bachelor', 'master', 'phd', 'unknown') DEFAULT 'unknown',
    target_degree_level ENUM('bachelor', 'master', 'phd', 'unknown') DEFAULT 'unknown',
    target_degree_confidence DECIMAL(3,2) NULL COMMENT 'Confidence score 0.00-1.00',
    target_degree_source ENUM('user_input', 'cv_explicit', 'trajectory_inference', 'unknown') DEFAULT 'unknown',
    target_degree_needs_clarification BOOLEAN DEFAULT FALSE,

    gpa DECIMAL(4,2) NULL,
    gpa_scale DECIMAL(3,1) NULL COMMENT 'e.g., 4.0, 5.0, 100',
    gpa_normalized DECIMAL(4,2) NULL COMMENT 'Normalized to 4.0 scale',
    gpa_confidence DECIMAL(3,2) NULL,

    -- Versioning / prompt traceability
    profile_version INT NOT NULL DEFAULT 1 COMMENT 'Monotonic profile version',
    profile_prompt_version VARCHAR(64) NULL COMMENT 'Prompt template version used for extraction',

    -- Metadata
    llm_model_used VARCHAR(100) NULL COMMENT 'e.g., gpt-4, claude-sonnet-4',
    llm_fallback_used BOOLEAN DEFAULT FALSE,
    llm_fallback_reason VARCHAR(255) NULL,
    total_processing_time_ms INT NULL,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_email (email),
    INDEX idx_user_id (user_id),
    INDEX idx_target_degree (target_degree_level),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;