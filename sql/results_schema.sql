-- Schema for this project's own data_quality database: run metadata,
-- per-rule results, and a sample of failing records per rule (for the
-- "drill down to failed records" dashboard requirement). Safe to re-run:
-- drops and recreates all 3 tables.
--
-- Run as: mysql -u dq_app -p data_quality < sql/results_schema.sql

DROP TABLE IF EXISTS dq_exceptions;
DROP TABLE IF EXISTS dq_results;
DROP TABLE IF EXISTS dq_runs;

CREATE TABLE dq_runs (
    run_id        INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_timestamp DATETIME NOT NULL,
    source        ENUM('original', 'defect_copy') NOT NULL,
    rules_file    VARCHAR(255) NOT NULL
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

CREATE TABLE dq_results (
    result_id   INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id      INT UNSIGNED NOT NULL,
    rule_id     VARCHAR(20) NOT NULL,
    table_name  VARCHAR(64) NOT NULL,
    check_type  VARCHAR(30) NOT NULL,
    severity    VARCHAR(10) NOT NULL,
    description TEXT NOT NULL,
    total_rows  INT UNSIGNED NOT NULL,
    failed_rows INT UNSIGNED NOT NULL,
    fail_rate   DECIMAL(9, 6) NOT NULL,
    threshold   DECIMAL(9, 6) NOT NULL,
    passed      BOOLEAN NOT NULL,
    FOREIGN KEY (run_id) REFERENCES dq_runs (run_id),
    INDEX idx_results_run (run_id),
    INDEX idx_results_rule (rule_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;

CREATE TABLE dq_exceptions (
    exception_id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    run_id       INT UNSIGNED NOT NULL,
    rule_id      VARCHAR(20) NOT NULL,
    record_key   VARCHAR(255) NOT NULL,
    detail       VARCHAR(500) NOT NULL,
    FOREIGN KEY (run_id) REFERENCES dq_runs (run_id),
    INDEX idx_exceptions_run_rule (run_id, rule_id)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4;
