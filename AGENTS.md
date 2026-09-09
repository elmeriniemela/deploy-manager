# Repository guidelines

- Minimize maintained code and configuration; remove redundancy before adding tooling.
- Keep `ubuntu-install.sh` rerunnable, simple and easy to review.
- Setup scripts must not clean up or migrate files from older repository versions.
- Keep the custom Odoo image and `rclone-mount.service` backup design.
- Monitoring is mandatory: keep Loki, Promtail, and node exporter. Alloy migration is future work.
- Keep destructive LUKS preparation manual; automate safe setup steps.
- Never overwrite existing secrets under `/srv/secure`.

## Validation

```bash
mkdir -p build
awk '/```mermaid/{flag=1;next}/```/{flag=0}flag' README.md > build/diagram.mmd
mmdc -i build/diagram.mmd -o build/diagram.png
```
