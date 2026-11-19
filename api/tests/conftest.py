import os

# 本機開發用的預設值；GitHub Actions 等環境若已設定 DATABASE_URL，不會被覆蓋
os.environ.setdefault("DATABASE_URL", "postgresql://sat:sat@localhost:5432/satplan")