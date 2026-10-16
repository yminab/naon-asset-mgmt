#!/usr/bin/env bash
set -u
echo "===== APP DIAGNOSTIC SCRIPT ====="
echo "Timestamp: $(date -u +"%Y-%m-%d %H:%M:%SZ")"
echo

# 0) require bash
if [ -z "$BASH_VERSION" ]; then
  echo "This script requires bash. Run with: bash check_app.sh" >&2
fi

# 1) environment / path
echo "== 1) 현재 작업 디렉터리 (pwd) =="
pwd
echo

echo "== 2) 주요 파일 존재 확인 =="
ls -la app.py requirements.txt migrations || true
echo

# 2) Git 정보
echo "== 3) Git 상태 =="
if [ -d .git ]; then
  echo "--- branch ---"
  git rev-parse --abbrev-ref HEAD || true
  echo "--- last commit ---"
  git log -1 --oneline || true
  echo "--- status (short) ---"
  git status --porcelain || true
  echo "--- branch list (remote) ---"
  git branch -av --no-color | sed -n '1,100p' || true
else
  echo "Not a git repo here."
fi
echo

# 3) venv / python
echo "== 4) 가상환경(venv) 탐색 및 python 경로 =="
PYTHON=python3
if [ -x ".venv/bin/python" ]; then
  PYTHON=.venv/bin/python
elif [ -x "venv/bin/python" ]; then
  PYTHON=venv/bin/python
elif [ -x "env/bin/python" ]; then
  PYTHON=env/bin/python
fi
echo "Using python: $(command -v $PYTHON || echo 'not found')"
$PYTHON --version 2>&1 || true
echo

# 4) python syntax check
echo "== 5) Python 문법 검사 (app.py) =="
if [ -f app.py ]; then
  $PYTHON -m py_compile app.py 2>&1 || echo "py_compile reported errors above"
else
  echo "app.py not found in current dir"
fi
echo

# 5) import app and list routes
echo "== 6) Import app and list routes =="
$PYTHON - <<'PY'
import traceback, sys, os
try:
    sys.path.insert(0, os.getcwd())
    import app
    print('IMPORT_OK')
    try:
        from app import app as flask_app
        rules = sorted(flask_app.url_map.iter_rules(), key=lambda r: r.rule)
        print('--- flask url_map rules ---')
        for r in rules:
            methods = ",".join(sorted(r.methods))
            print(f"{r.rule}    [{methods}]")
    except Exception:
        print('Error while accessing app.url_map:')
        traceback.print_exc()
except Exception:
    traceback.print_exc()
PY
echo

# 6) systemd/service checks
echo "== 7) systemd service check (search likely unit names) =="
echo "--- units mentioning asset / security / gunicorn ---"
systemctl list-units --type=service --all | egrep -i 'asset|security|gunicorn|naon' || true
echo
if systemctl list-unit-files | egrep -i 'security-assets|naon|gunicorn' >/dev/null 2>&1; then
  echo "--- status security-assets (if exists) ---"
  systemctl status security-assets --no-pager || true
fi
echo

echo "--- unit files that mention 'gunicorn' or 'app:app' ---"
grep -R --line-number -E 'gunicorn|app:app' /etc/systemd/system /lib/systemd/system 2>/dev/null || true
echo

# 7) gunicorn / python processes
echo "== 8) gunicorn / python processes =="
ps aux | egrep 'gunicorn|python' | egrep -v 'egrep|grep' | sed -n '1,200p' || true
echo

# 8) process cwd for first gunicorn pid
echo "== 9) process cwd for first gunicorn pid (if any) =="
GPID=$(ps aux | egrep 'gunicorn' | egrep -v 'egrep|grep' | awk '{print $2}' | head -n1 || true)
if [ -n "$GPID" ]; then
  echo "gunicorn pid: $GPID"
  echo "cwd ->"
  ls -la /proc/$GPID/cwd 2>/dev/null || true
  echo "exe ->"
  readlink -f /proc/$GPID/exe 2>/dev/null || true
else
  echo "no gunicorn process found"
fi
echo

# 9) port listening
echo "== 10) port 5000 listener =="
ss -ltnp | egrep ':5000\b|:80\b|:8000\b' || true
echo

# 10) curl checks
echo "== 11) curl checks =="
HOST_IP=127.0.0.1
if hostname -I 2>/dev/null | grep -q '192.168'; then
  HOST_IP=$(hostname -I | awk '{print $1}')
fi
for ip in 127.0.0.1 $HOST_IP; do
  echo "-- testing host: $ip --"
  for p in "/" "/assets" "/servers" "/assets/export" "/io"; do
    echo -n "$p  -> "
    curl -s -S -o /dev/null -w "%{http_code} %{url_effective}\n" "http://$ip:5000$p" || echo "curl error"
  done
done
echo

# 11) migrations listing
echo "== 12) migration files and schema.sql =="
ls -la migrations 2>/dev/null || true
ls -la schema.sql 2>/dev/null || true
echo

# 12) quick grep for suspicious truncation in app.py
echo "== 13) quick greps for common mistakes in app.py =="
if [ -f app.py ]; then
  echo "lines with '...' or truncated strings:"
  nl -ba app.py | egrep "\.\.\.|\[\.\.\." | sed -n '1,200p' || true
  echo "lines with f-strings:"
  nl -ba app.py | egrep "f\"|f'" | sed -n '1,200p' || true
fi

echo
# 14) hints
echo "== 14) HINTS =="
echo " - If IMPORT fails: paste the Python traceback above (section 6)."
echo " - If IMPORT_OK but routes missing: verify gunicorn is running the same codebase (see process cwd and ExecStart in systemd unit)."
echo " - If gunicorn not running: check systemd unit or process supervisor."
echo " - If curl returns 404 but import shows routes: likely a different process/working directory or URL prefix mismatch."

echo "===== End of diagnostic ====="
