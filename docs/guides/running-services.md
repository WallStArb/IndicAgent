# Running Services

Service management guide.

---

## Production Services

See [STATUS.md](../STATUS.md) for current service list.

### systemd Management

```bash
sudo systemctl status indicagent-backend-api
sudo systemctl restart indicagent-hf-tws
journalctl -u indicagent-hf-tws -f
```

### Health Checks

```bash
curl http://localhost:9109/health  # Indicator Processor
curl http://localhost:9109/metrics # Prometheus metrics
```

---

## Development Mode

[TODO: Add development service startup]

---

**Reference:** [Service Reference](../reference/services/overview.md)
