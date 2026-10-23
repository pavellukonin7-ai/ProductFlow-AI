#!/usr/bin/env bash
set -euo pipefail

cd /opt/productflow-ai
install -m 0644 deploy/systemd/productflow-ai.service /etc/systemd/system/productflow-ai.service
install -m 0644 deploy/systemd/productflow-web.service /etc/systemd/system/productflow-web.service
install -m 0644 deploy/systemd/productflow-backup.service /etc/systemd/system/productflow-backup.service
install -m 0644 deploy/systemd/productflow-backup.timer /etc/systemd/system/productflow-backup.timer
systemctl daemon-reload
systemctl enable --now productflow-ai.service
systemctl enable --now productflow-web.service
systemctl enable --now productflow-backup.timer
systemctl status productflow-ai.service --no-pager -l
systemctl status productflow-web.service --no-pager -l
systemctl list-timers productflow-backup.timer --no-pager
