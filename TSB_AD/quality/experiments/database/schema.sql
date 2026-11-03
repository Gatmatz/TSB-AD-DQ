-- experiments: one row per successful run (dataset, detector, pollution setting); pollution = 'clean' is the baseline.
-- errors: the runs that failed.
-- Safe to run repeatedly: it only creates what is missing.
CREATE TABLE IF NOT EXISTS experiments (
    id BIGSERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    detector TEXT NOT NULL,
    pollution TEXT NOT NULL,            -- e.g. 'white_noise'; 'clean' for the baseline
    params JSONB NOT NULL DEFAULT '{}', -- e.g. {"snr_db": 10}
    seed INTEGER NOT NULL,
    imputation TEXT NOT NULL,           -- 'none' unless the pollution creates missing points
    applicability TEXT,                 -- points polluted: 'global', 'normal_only', 'anomalies_only'; 'none' for clean
    execution_profile TEXT,             -- EXECUTION_PROFILE from .env
    window_length INTEGER,              -- window of the window-based metrics
    -- TSB_AD.evaluation.metrics.get_metrics()
    auc_pr DOUBLE PRECISION,
    auc_roc DOUBLE PRECISION,
    vus_pr DOUBLE PRECISION,
    vus_roc DOUBLE PRECISION,
    standard_f1 DOUBLE PRECISION,
    pa_f1 DOUBLE PRECISION,
    event_based_f1 DOUBLE PRECISION,
    r_based_f1 DOUBLE PRECISION,
    affiliation_f DOUBLE PRECISION,
    execution_time DOUBLE PRECISION,    -- seconds the detector took
    imputation_rmse DOUBLE PRECISION,   -- RMSE of the imputed points vs. the original ones; NULL unless imputed
    -- what the pollution was asked to do vs. what it did (TSB_AD.quality.report), e.g. {"affected": 402, "swaps": 201}
    desired JSONB,
    actual JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT experiments_run_key UNIQUE (dataset, detector, pollution, params, seed, imputation, applicability)
);

CREATE TABLE IF NOT EXISTS errors (
    id BIGSERIAL PRIMARY KEY,
    dataset TEXT NOT NULL,
    detector TEXT NOT NULL,
    pollution TEXT NOT NULL,
    params JSONB NOT NULL DEFAULT '{}',
    seed INTEGER NOT NULL,
    imputation TEXT NOT NULL,
    applicability TEXT,
    error TEXT NOT NULL,                -- 'ExceptionType: message'
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT errors_run_key UNIQUE (dataset, detector, pollution, params, seed, imputation, applicability)
);

CREATE INDEX IF NOT EXISTS experiments_lookup
    ON experiments (detector, pollution, dataset);
