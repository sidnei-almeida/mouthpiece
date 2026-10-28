#!/usr/bin/env python3
"""mouthpiece: speech in your own cloned voice, from the terminal (or from Claude Code).

Talks to the Mouthpiece server (server.py) and starts it in the background if it isn't running, so
the model loads once and stays on the GPU between calls. Standard library only; Windows and Linux.

    mouthpiece say "Text to speak." -o narration.wav [--lang en|pt] [--voice name-en.wav] [--json]
    mouthpiece say -f script.txt -o narration.wav        (or text on stdin: echo "..." | mouthpiece say -)
    mouthpiece open | status | stop
    mouthpiece voices
    mouthpiece pronuncia                                  (list rules)
    mouthpiece pronuncia add "Alien: Isolation" "Alien Isolation"

--json prints {"path", "duration", "frames_30", "frames_60", "generated_in"} for scripts and agents.
Progress goes to stderr, results to stdout.
"""
import argparse
import json
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(os.path.realpath(__file__)).parent
URL = os.environ.get('MOUTHPIECE_URL', 'http://127.0.0.1:7860')
WINDOWS = os.name == 'nt'
STATE = (Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Mouthpiece' if WINDOWS
         else Path.home() / '.cache' / 'mouthpiece')
PIDFILE, LOG = STATE / 'server.pid', STATE / 'server.log'
VENV_PY = ROOT / '.venv' / ('Scripts/pythonw.exe' if WINDOWS else 'bin/python')


def err(msg: str):
    print(msg, file=sys.stderr, flush=True)


def api(method: str, path: str, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method,
                                 headers={'Content-Type': 'application/json', 'X-Mouthpiece': '1'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:  # the server's own message, not a traceback
        try:
            detail = json.loads(e.read()).get('detail')
        except ValueError:
            detail = None
        if isinstance(detail, list):  # validation errors
            detail = '; '.join(d.get('msg', str(d)) for d in detail)
        sys.exit(f'error: {detail or e}')


def server_status():
    """The server's status, None if nothing listens, or {'status': 'foreign'} if something else does."""
    try:
        with urllib.request.urlopen(URL + '/api/status', timeout=3) as r:
            s = json.loads(r.read())
        return s if isinstance(s, dict) and 'status' in s else {'status': 'foreign'}
    except (urllib.error.HTTPError, ValueError):
        return {'status': 'foreign'}
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def log_tail(n: int = 15) -> str:
    try:
        return '\n'.join(LOG.read_text(errors='replace').splitlines()[-n:])
    except FileNotFoundError:
        return ''


def start_server():
    STATE.mkdir(parents=True, exist_ok=True)
    port = str(urllib.parse.urlsplit(URL).port or 7860)
    cmd = [str(VENV_PY), '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', port]
    kwargs = {'cwd': ROOT, 'stdout': open(LOG, 'a'), 'stderr': subprocess.STDOUT}
    if WINDOWS:  # its own process group, no console window, survives this command exiting
        kwargs['creationflags'] = (subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                                   | subprocess.CREATE_NO_WINDOW)
    else:
        kwargs['start_new_session'] = True
    proc = subprocess.Popen(cmd, **kwargs)
    PIDFILE.write_text(str(proc.pid))
    return proc


def ensure_server(wait: bool = True) -> dict:
    s, proc = server_status(), None
    if s and s['status'] == 'foreign':
        sys.exit(f'something else is using {URL}; free the port or set MOUTHPIECE_URL')
    if s is None:
        err('Mouthpiece is not running; starting it (the model takes ~10-70 s to load)')
        proc = start_server()
    t0 = time.time()
    while True:
        s = server_status()
        if proc and proc.poll() is not None:
            sys.exit(f'Mouthpiece exited during startup:\n{log_tail()}')
        if s and s['status'] in ('error', 'stuck'):
            sys.exit(f'Mouthpiece: {s["error"]}')
        if s and (s['status'] == 'ready' or (not wait and s['status'] == 'loading')):
            return s
        if time.time() - t0 > 600:
            sys.exit(f'Mouthpiece not ready after 10 min; see {LOG}')
        time.sleep(1.5)


def cmd_say(a):
    if a.file:
        text = Path(a.file).read_text(encoding='utf-8')
    elif a.text == '-' or a.text is None:
        text = sys.stdin.read()
    else:
        text = a.text
    if not text.strip():
        sys.exit('no text')
    ensure_server()
    job = api('POST', '/api/generate', {'text': text, 'lang': a.lang, 'voice': a.voice})
    jid, t0, last = job['id'], time.time(), None
    while True:
        if server_status() is None:
            sys.exit('Mouthpiece stopped while generating')
        job = api('GET', f'/api/jobs/{jid}')
        if job['state'] in ('done', 'error'):
            break
        if not a.json:
            line = f'generating {job["done"]}/{job["total"]} ({time.time() - t0:.0f} s)'
            if sys.stderr.isatty():  # one line, rewritten in place
                print(f'\r{line}', end='', file=sys.stderr, flush=True)
            elif job['done'] != last:  # logs: only when a chunk finishes
                err(line)
                last = job['done']
        time.sleep(1)
    if not a.json and sys.stderr.isatty():
        print(file=sys.stderr)
    if job['state'] == 'error':
        sys.exit(f'generation failed: {job.get("error")}')
    out = Path(a.output or job['filename'])
    out.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f'{URL}/api/download/{jid}') as r, open(out, 'wb') as f:
        shutil.copyfileobj(r, f)
    d = job['duration']
    if a.json:
        print(json.dumps({'path': str(out.resolve()), 'duration': d, 'frames_30': math.ceil(d * 30),
                          'frames_60': math.ceil(d * 60), 'generated_in': job['seconds']}))
    else:
        print(out)
        err(f'{d} s of audio, generated in {job["seconds"]} s')


def cmd_open(_):
    ensure_server(wait=False)
    webbrowser.open(URL)


def cmd_status(_):
    s = server_status()
    print(json.dumps(s, ensure_ascii=False) if s else 'not running')


def ours(pid: int) -> bool:
    """Whether pid is still our server: after a crash the number can be reused by another program."""
    if WINDOWS:
        out = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'],
            capture_output=True, text=True, creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout
        return 'uvicorn' in out and 'server:app' in out
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except FileNotFoundError:
        return False
    return any(b'uvicorn' in c for c in cmd) and b'server:app' in cmd


def cmd_stop(_):
    s = server_status()
    if s and s['status'] != 'foreign':
        try:  # the clean way: works whoever started it (launcher, start.sh or this CLI)
            req = urllib.request.Request(URL + '/api/shutdown', data=b'', method='POST', headers={'X-Mouthpiece': '1'})
            urllib.request.urlopen(req, timeout=5).read()
            print('stopped')
            PIDFILE.unlink(missing_ok=True)
            return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass  # stuck hard: fall back to killing the process
    if not PIDFILE.exists():
        print('not running')
        return
    pid = int(PIDFILE.read_text())
    if ours(pid):
        if WINDOWS:
            subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True)
        else:
            os.killpg(pid, signal.SIGTERM)
        print('stopped')
    else:
        print('not running')
    PIDFILE.unlink()


def cmd_voices(_):
    s = ensure_server(wait=False)
    for v in s['voices']:
        print(v)
    if not s['voices']:
        print('no voices yet: create one in the app (mouthpiece open, then "Vozes")')


def cmd_pronuncia(a):
    if a.action in ('add', 'rm') and not a.de:
        sys.exit(f'usage: mouthpiece pronuncia {a.action} "written"' + (' "spoken"' if a.action == 'add' else ''))
    ensure_server(wait=False)  # the rules API answers before the model is ready
    rules = api('GET', '/api/pronuncia')
    if a.action == 'add':
        rules = [r for r in rules if r['de'] != a.de] + [{'de': a.de, 'para': a.para}]
        rules = api('PUT', '/api/pronuncia', rules)
    elif a.action == 'rm':
        rules = api('PUT', '/api/pronuncia', [r for r in rules if r['de'] != a.de])
    for r in rules:
        print(f'{r["de"]}  ->  {r["para"]}')


def main():
    if hasattr(sys.stdout, 'reconfigure'):  # accents on Windows consoles
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    p = argparse.ArgumentParser(prog='mouthpiece', description='Speech in your own cloned voice.')
    sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('say', help='generate speech')
    s.add_argument('text', nargs='?', help='text, or - for stdin')
    s.add_argument('-f', '--file', help='read the text from a file')
    s.add_argument('-o', '--output', help='output WAV (default: named after the text, in the current folder)')
    s.add_argument('--lang', choices=['en', 'pt'], default='en')
    s.add_argument('--voice', help='voice to use (see: mouthpiece voices; default: one ending in -<lang>.wav)')
    s.add_argument('--json', action='store_true', help='machine-readable result')
    s.set_defaults(fn=cmd_say)
    sub.add_parser('open', help='open the app in the browser').set_defaults(fn=cmd_open)
    sub.add_parser('status').set_defaults(fn=cmd_status)
    sub.add_parser('stop', help='shut the server down and free the GPU').set_defaults(fn=cmd_stop)
    sub.add_parser('voices', help='list the voices').set_defaults(fn=cmd_voices)
    pr = sub.add_parser('pronuncia', help='pronunciation rules')
    pr.add_argument('action', nargs='?', choices=['list', 'add', 'rm'], default='list')
    pr.add_argument('de', nargs='?')
    pr.add_argument('para', nargs='?', default='')
    pr.set_defaults(fn=cmd_pronuncia)
    a = p.parse_args()
    a.fn(a)


if __name__ == '__main__':
    main()
