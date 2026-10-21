# OnCall Agent API Documentation

## Current Documentation

| Document | Description |
|----------|-------------|
| [Teams Power Automate Setup](teams-power-automate-setup.md) | Microsoft Teams integration via Power Automate |

## Quick Reference

### Running the API

```bash
# Local development
./run_api_server.sh
curl http://localhost:8000/health
open http://localhost:8000/docs  # Interactive API documentation

# Docker
docker compose up -d
docker compose logs -f
```

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check |
| `/docs` | GET | OpenAPI documentation |
| `/query` | POST | Query the agent |
| `/incident` | POST | Analyze an incident |
| `/memory/health` | GET | Check incident memory status |
| `/memory/stats` | GET | Get memory statistics |

## Archive

Historical implementation plans are preserved in `archive/`:
- `HERMES_CHARTDATA_IMPLEMENTATION.md` - ChartData monitoring implementation
- `INCIDENT_MEMORY_IMPLEMENTATION_PLAN.md` - Incident memory feature implementation
- `DATABRICKS_COST_AWARENESS.md` - Databricks cost feature update

---

*Last updated: 2026-02-05*
