-- Migration 005: LLM Call Logs
-- Audit trail for all LLM API calls

CREATE TABLE IF NOT EXISTS llm_call_logs (
    id VARCHAR(36) PRIMARY KEY COMMENT 'UUID v4',
    profile_id VARCHAR(36) NULL COMMENT 'Related profile if applicable',

    operation VARCHAR(100) NOT NULL COMMENT 'e.g., profile_extraction, gap_analysis',
    llm_provider ENUM('openai', 'anthropic') NOT NULL,
    model_name VARCHAR(100) NOT NULL,

    -- Request/Response
    input_tokens INT NULL,
    output_tokens INT NULL,
    total_cost_usd DECIMAL(10,6) NULL,
    latency_ms INT NULL,

    success BOOLEAN NOT NULL,
    error_message TEXT NULL,
    retry_count INT DEFAULT 0,

    -- Audit
    trace_id VARCHAR(36) NOT NULL COMMENT 'Request trace ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (profile_id) REFERENCES student_profiles(id) ON DELETE CASCADE,
    INDEX idx_profile_id (profile_id),
    INDEX idx_trace_id (trace_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
