#!/usr/bin/env python3
"""dwl-voice: generate speech in your cloned voice from the terminal (or from Claude Code).

Talks to the voice studio server (server.py) and starts it in the background if it isn't running,
so the model loads once and stays on the GPU between calls. Standard library only.

    dwl-voice say "Text to speak." -o narration.wav [--lang en|pt] [--voice minha-voz-en.wav] [--json]
    dwl-voice say -f script.txt -o narration.wav        (or text on stdin: echo "..." | dwl-voice say -)
    dwl-voice status | stop
    dwl-voice pronuncia                                  (list rules)
    dwl-voice pronuncia add "Alien: Isolation" "Alien Isolation"

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
from pathlib import Path

ROOT = Path(os.path.realpath(__file__)).parent
URL = os.environ.get('DWL_VOICE_URL', 'http://127.0.0.1:7860')
STATE = Path.home() / '.cache' / 'dwl-voice'
PIDFILE, LOG = STATE / 'server.pid', STATE / 'server.log'


def api(method: str, path: str, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers={'Content-Type': 'application/json'})
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


def err(msg: str):
    print(msg, file=sys.stderr, flush=True)


def server_status():
    """The server's status, None if nothing listens, or {'status': 'foreign'} if something else does."""
    try:
        with urllib.request.urlopen(URL + '/api/status', timeout=3) as r:
            s = json.loads(r.read())
        return s if isinstance(s, dict) and 'status' in s else {'status': 'foreign'}
    except urllib.error.HTTPError:
        return {'status': 'foreign'}
    except ValueError:
        return {'status': 'foreign'}
    except (urllib.error.URLError, ConnectionError, TimeoutError):
        return None


def log_tail(n: int = 15) -> str:
    try:
        return '\n'.join(LOG.read_text().splitlines()[-n:])
    except FileNotFoundError:
        return ''


def ensure_server(wait: bool = True) -> dict:
    s, proc = server_status(), None
    if s and s['status'] == 'foreign':
        sys.exit(f'something else is using {URL}; free the port or set DWL_VOICE_URL')
    if s is None:
        STATE.mkdir(parents=True, exist_ok=True)
        err('voice server not running; starting it (the model takes ~10-70 s to load)')
        port = str(urllib.parse.urlsplit(URL).port or 7860)
        proc = subprocess.Popen(
            [str(ROOT / '.venv' / 'bin' / 'uvicorn'), 'server:app', '--host', '127.0.0.1', '--port', port],
            cwd=ROOT, stdout=open(LOG, 'a'), stderr=subprocess.STDOUT, start_new_session=True,
        )
        PIDFILE.write_text(str(proc.pid))
    t0 = time.time()
    while True:
        s = server_status()
        if proc and proc.poll() is not None:
            sys.exit(f'the voice server exited during startup:\n{log_tail()}')
        if s and s['status'] in ('error', 'stuck'):
            sys.exit(f'voice server: {s["error"]}')
        if s and (s['status'] == 'ready' or (not wait and s['status'] == 'loading')):
            return s
        if time.time() - t0 > 300:
            sys.exit(f'server not ready after 5 min; see {LOG}')
        time.sleep(1.5)


def cmd_say(a):
    if a.file:
        text = Path(a.file).read_text()
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
            sys.exit('the voice server stopped while generating')
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


def cmd_status(_):
    s = server_status()
    print(json.dumps(s, ensure_ascii=False) if s else 'not running')


def ours(pid: int) -> bool:
    """Whether pid is still our uvicorn: after a crash the number can be reused by another program."""
    try:
        cmd = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except FileNotFoundError:
        return False
    return any(b'uvicorn' in c for c in cmd) and b'server:app' in cmd


def cmd_stop(_):
    if not PIDFILE.exists():
        print('no server started by dwl-voice (one opened with start.sh stops with Ctrl+C)')
        return
    pid = int(PIDFILE.read_text())
    if ours(pid):
        os.killpg(pid, signal.SIGTERM)
        print('stopped')
    else:
        print('not running')
    PIDFILE.unlink()


def cmd_pronuncia(a):
    if a.action in ('add', 'rm') and not a.de:
        sys.exit(f'usage: dwl-voice pronuncia {a.action} "written"' + (' "spoken"' if a.action == 'add' else ''))
    ensure_server(wait=False)  # the rules API answers before the model is ready
    rules = api('GET', '/api/pronuncia')
    if a.action == 'add':
        rules = [r for r in rules if r['de'] != a.de] + [{'de': a.de, 'para': a.para}]
        rules = api('PUT', '/api/pronuncia', rules)
    elif a.action == 'rm':
        rules = api('PUT', '/api/pronuncia', [r for r in rules if r['de'] != a.de])
    for r in rules:
        print(f'{r["de"]}  ->  {r["para"]}')


p = argparse.ArgumentParser(prog='dwl-voice', description='Speech in your cloned voice (Qwen3-TTS on the Arc).')
sub = p.add_subparsers(dest='cmd', required=True)
s = sub.add_parser('say', help='generate speech')
s.add_argument('text', nargs='?', help='text, or - for stdin')
s.add_argument('-f', '--file', help='read the text from a file')
s.add_argument('-o', '--output', help='output WAV (default: named after the text, in the current folder)')
s.add_argument('--lang', choices=['en', 'pt'], default='en')
s.add_argument('--voice', help='reference voice in voices/ (default: *-<lang>.wav)')
s.add_argument('--json', action='store_true', help='machine-readable result')
s.set_defaults(fn=cmd_say)
sub.add_parser('status').set_defaults(fn=cmd_status)
sub.add_parser('stop').set_defaults(fn=cmd_stop)
pr = sub.add_parser('pronuncia', help='pronunciation rules')
pr.add_argument('action', nargs='?', choices=['list', 'add', 'rm'], default='list')
pr.add_argument('de', nargs='?')
pr.add_argument('para', nargs='?', default='')
pr.set_defaults(fn=cmd_pronuncia)
a = p.parse_args()
a.fn(a)
