-- Migration 002: Documents table
-- Stores metadata for uploaded CV/transcript files

CREATE TABLE IF NOT EXISTS documents (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NOT NULL,

    document_type ENUM('cv', 'transcript', 'unknown') NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_extension VARCHAR(10) NOT NULL,
    file_size_bytes INT NOT NULL,
    mime_type VARCHAR(100) NULL,

    -- Storage
    file_path VARCHAR(500) NULL COMMENT 'S3 path or local file path',
    file_hash VARCHAR(64) NULL COMMENT 'SHA-256 hash for deduplication',

    -- Processing metadata
    extracted_text_length INT NULL,
    ocr_used BOOLEAN DEFAULT FALSE,
    extraction_method ENUM('digital_pdf', 'docx', 'ocr', 'unknown') DEFAULT 'unknown',
    extraction_time_ms INT NULL,

    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    INDEX idx_profile_id (profile_id),
    INDEX idx_document_type (document_type),
    INDEX idx_file_hash (file_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
