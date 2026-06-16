# Security Architecture

**Version:** 2.8
**Last Updated:** 2026-05-28
**Status:** Not implemented — planned for future

---

## Overview

IndicAgent currently runs in a trusted environment with no authentication or authorization. This document outlines the security architecture for when public exposure or multi-user access is required.

**Current state:**
- API has no authentication
- Grafana has default credentials
- Database uses default password
- All services run as single user

**Target state (when needed):**
- API key authentication
- RBAC for API access
- Secure credential management
- Audit logging for sensitive operations

---

## Threat Model

### Current Threats (Low Risk)

| Threat | Likelihood | Impact | Mitigation |
|--------|------------|--------|------------|
| Local network sniffing | Low | Medium | Use TLS (future) |
| Unauthorized API access | Low | Medium | Network isolation |
| Credential theft | Low | High | Change defaults |

### Future Threats (Public Deployment)

| Threat | Likelihood | Impact | Mitigation |
|--------|------------|--------|------------|
| API abuse/DDoS | Medium | High | Rate limiting, API keys |
| Data exfiltration | Low | High | RBAC, audit logs |
| SQL injection | Low | Critical | Parameterized queries (already done) |
| Credential stuffing | Medium | High | Strong auth, MFA |

---

## Authentication Strategies

### API Key Authentication (Recommended)

**Implementation:**
```python
from fastapi import Security, HTTPException
from fastapi.security import APIKeyHeader

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def verify_api_key(api_key: str = Security(API_KEY_HEADER)):
    valid_keys = os.getenv("API_KEYS", "").split(",")
    if api_key not in valid_keys:
        raise HTTPException(status_code=403, detail="Invalid API key")
    return api_key

@app.get("/api/v1/bars", dependencies=[Depends(verify_api_key)])
async def get_bars(...):
    pass
```

**Pros:** Simple, stateless, easy to implement
**Cons:** Key rotation manual, no revocation without restart

---

### JWT Authentication (Alternative)

**Implementation:**
```python
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

security = HTTPBearer()

async def verify_token(credentials: HTTPAuthorizationCredentials = Security(security)):
    token = credentials.credentials
    # Verify JWT signature
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    return payload

@app.get("/api/v1/bars", dependencies=[Depends(verify_token)])
async def get_bars(...):
    pass
```

**Pros:** Standard, supports expiration, refresh tokens
**Cons:** More complex, requires token management

---

## Authorization (RBAC)

### Role Definitions

| Role | Permissions | Use Case |
|------|-------------|----------|
| `admin` | Full access | System administration |
| `operator` | Read/write signals | Operations team |
| `analyst` | Read-only | Data analysis |
| `api` | API-only access | Automated systems |

### Implementation

```python
from enum import Enum

class Role(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"
    ANALYST = "analyst"
    API = "api"

class User:
    def __init__(self, username: str, role: Role):
        self.username = username
        self.role = role

async def get_current_user(api_key: str = Security(API_KEY_HEADER)) -> User:
    # Look up user and role from API key
    user = lookup_user_by_key(api_key)
    return user

async def require_role(required_role: Role):
    def role_checker(user: User = Depends(get_current_user)):
        if user.role != required_role and user.role != Role.ADMIN:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user
    return role_checker

@app.delete("/api/v1/signals/{id}", dependencies=[Depends(require_role(Role.OPERATOR))])
async def delete_signal(signal_id: str):
    pass
```

---

## Credential Management

### Current State

```bash
# .env file (plaintext)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/indicagent
KAFKA_BOOTSTRAP_SERVERS=localhost:19092
```

### Recommended: Secrets Management

**Option 1: Environment variables from secrets file**
```bash
# /etc/indicagent/secrets (root-only, 0600)
DATABASE_PASSWORD=secure_password
API_KEYS=key1,key2,key3
```

**Option 2: HashiCorp Vault (for production)**
```python
import hvac

client = hvac.Client(url='http://vault:8200')
client.auth.approle.login(role_id='indicagent', secret_id='...')

DB_PASSWORD = client.read('secret/indicagent/database')['data']['password']
```

**Option 3: Docker secrets**
```yaml
# docker-compose.yml
services:
  timescaledb:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

---

## Database Security

### Current Configuration

```sql
-- Default user (postgres) with all privileges
CREATE USER postgres WITH PASSWORD 'postgres';
GRANT ALL PRIVILEGES ON DATABASE indicagent TO postgres;
```

### Recommended Configuration

```sql
-- Application user with limited privileges
CREATE USER indicagent_app WITH PASSWORD 'secure_password';
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO indicagent_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO indicagent_app;

-- Read-only user for analytics
CREATE USER indicagent_readonly WITH PASSWORD 'secure_password';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO indicagent_readonly;

-- Admin user (rarely used)
CREATE USER indicagent_admin WITH PASSWORD 'very_secure_password';
GRANT ALL PRIVILEGES ON DATABASE indicagent TO indicagent_admin;
```

### Row-Level Security (RLS)

For multi-tenant scenarios:

```sql
ALTER TABLE signal_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_signals ON signal_ledger
  FOR SELECT
  USING (created_by = current_user);

CREATE POLICY user_signals_insert ON signal_ledger
  FOR INSERT
  WITH CHECK (created_by = current_user);
```

---

## Network Security

### Current State

- All services on localhost (127.0.0.1)
- No TLS encryption
- No firewall rules

### Recommendations

**TLS for API:**
```python
# uvicorn with TLS
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 \
  --ssl-keyfile /etc/ssl/private/indicagent.key \
  --ssl-certfile /etc/ssl/certs/indicagent.crt
```

**Firewall rules:**
```bash
# Allow only necessary ports
ufw allow 22/tcp    # SSH
ufw allow 8000/tcp  # API (if exposed)
ufw allow 3001/tcp  # Grafana (if exposed)
ufw default deny incoming
ufw enable
```

**Internal network isolation:**
- Database on private network
- Kafka on private network
- Only API and Grafana exposed

---

## Audit Logging

### Sensitive Operations to Log

- User authentication
- Signal deletion/modification
- Configuration changes
- Database schema changes

### Implementation

```python
import structlog

audit = structlog.get_logger("audit")

async def delete_signal(signal_id: str, user: User = Depends(get_current_user)):
    await db.execute("DELETE FROM signal_ledger WHERE id = $1", signal_id)
    
    audit.info("signal_deleted",
        signal_id=signal_id,
        user=user.username,
        role=user.role,
        timestamp=datetime.now(UTC).isoformat()
    )
```

---

## Security Checklist

When deploying to untrusted environment:

- [ ] Change all default passwords
- [ ] Implement API authentication
- [ ] Enable TLS for all exposed services
- [ ] Configure firewall rules
- [ ] Set up secrets management
- [ ] Create least-privilege DB users
- [ ] Enable audit logging
- [ ] Set up Grafana authentication
- [ ] Review and restrict systemd unit file permissions
- [ ] Enable file system encryption (LUKS)

---

## See Also

- **API design:** `docs/platform/platform-api.md`
- **Infrastructure reference:** `docs/operations/operations-infrastructure.md`
- **Deployment:** `docs/operations/operations-infrastructure.md`
