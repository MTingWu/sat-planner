-- 雲量預報格點：由 GitHub Actions 定時執行 app.jobs.prefetch_weather 寫入
-- API 只讀這張表，使用者請求時不再呼叫 Open-Meteo（避免共用 IP 被限流）
CREATE TABLE IF NOT EXISTS weather_grid (
  lat        NUMERIC(6,2) NOT NULL,
  lon        NUMERIC(6,2) NOT NULL,
  fetched_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
  hourly     JSONB        NOT NULL,
  PRIMARY KEY (lat, lon)
);