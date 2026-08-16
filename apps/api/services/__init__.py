# services — pure generation logic, independent of HTTP routing.
# One module per concern; routes/ import these. Future pillars (Radar,
# Screener, Coach, ...) add new modules here without touching the rest.