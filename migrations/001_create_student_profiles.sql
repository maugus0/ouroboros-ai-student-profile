-- Migration 001: Student Profiles table
-- Stores parsed student profile data with confidence metadata

CREATE TABLE IF NOT EXISTS student_profiles (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',

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

    -- Profile JSON (full structured data)
    profile_json JSON NOT NULL COMMENT 'Complete profile with all extracted fields',
    confidence_map JSON NULL COMMENT 'Per-field confidence scores',
    evidence_map JSON NULL COMMENT 'Per-field evidence snippets from documents',
    contradiction_flags JSON NULL COMMENT 'Conflicting data between CV and transcript',
    missing_critical_fields JSON NULL COMMENT 'List of critical fields that are null',
    clarification_queue JSON NULL COMMENT 'Fields requiring user clarification',

    -- Metadata
    llm_model_used VARCHAR(100) NULL COMMENT 'e.g., gpt-4, claude-sonnet-4',
    llm_fallback_used BOOLEAN DEFAULT FALSE,
    llm_fallback_reason VARCHAR(255) NULL,
    total_processing_time_ms INT NULL,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_email (email),
    INDEX idx_target_degree (target_degree_level),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
