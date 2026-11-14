CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE plan_files (
  id          SERIAL PRIMARY KEY,
  platform    TEXT NOT NULL,          -- 例如 S1D、S2B
  sensor      TEXT NOT NULL,          -- 'SAR' 或 'MSI'
  filename    TEXT NOT NULL,
  source_url  TEXT NOT NULL,
  valid_from  TIMESTAMPTZ NOT NULL,   -- 計畫涵蓋期間，從檔名解析
  valid_to    TIMESTAMPTZ NOT NULL,
  sha256      TEXT NOT NULL UNIQUE,
  fetched_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE acquisitions (
  id             BIGSERIAL PRIMARY KEY,
  plan_file_id   INT REFERENCES plan_files(id) ON DELETE CASCADE,
  platform       TEXT NOT NULL,
  sensor         TEXT NOT NULL,
  start_time     TIMESTAMPTZ NOT NULL,
  end_time       TIMESTAMPTZ NOT NULL,
  mode           TEXT,
  orbit_relative INT,
  pass_direction TEXT,              -- S1 為推算值
  footprint      GEOMETRY(MultiPolygon, 4326) NOT NULL,
  attrs          JSONB,
  UNIQUE (platform, start_time)
);

CREATE INDEX acquisitions_footprint_gix ON acquisitions USING GIST (footprint);
CREATE INDEX acquisitions_start_idx ON acquisitions (start_time);

CREATE TABLE weather_cache (
  lat        NUMERIC(5,1),
  lon        NUMERIC(5,1),
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  hourly     JSONB NOT NULL,
  PRIMARY KEY (lat, lon)
);