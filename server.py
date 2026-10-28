"""Mouthpiece: type text, hear it in your own cloned voice, export a WAV.

Qwen3-TTS (Base model, voice clone) stays loaded on the GPU: Intel Arc (XPU), NVIDIA (CUDA) or, as a
slow fallback, the CPU. Each request is a job: the text gets the pronunciation fixes, is split into
short chunks, generated one chunk at a time (one job at a time), joined with short pauses and
finished to -16 LUFS / 48 kHz / 24-bit, ready to drop into an edit.

    python launcher.py   (or: uvicorn server:app --port 7860)
"""
import io
import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

import audio
from server_model import MODEL_ID, MODEL_REVISION

ROOT = Path(__file__).parent


def data_dir() -> Path:
    """Where the user's voices, generations and rules live. Outside the install folder, so updating
    or uninstalling the app never deletes them. MOUTHPIECE_DATA overrides."""
    if os.environ.get('MOUTHPIECE_DATA'):
        return Path(os.environ['MOUTHPIECE_DATA'])
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA', Path.home())) / 'Mouthpiece'
    if (ROOT / '.git').exists():  # a development checkout keeps its data next to the code
        return ROOT
    return Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'mouthpiece'


DATA = data_dir()
VOICES, OUTPUT, PRONUNCIATION = DATA / 'voices', DATA / 'output', DATA / 'pronuncia.json'
for d in (VOICES, OUTPUT):
    d.mkdir(parents=True, exist_ok=True)
if not PRONUNCIATION.exists() and (ROOT / 'pronuncia.json').exists():
    PRONUNCIATION.write_text((ROOT / 'pronuncia.json').read_text())

if torch.xpu.is_available():
    DEVICE, DEVICE_NAME = 'xpu', torch.xpu.get_device_name(0)
elif torch.cuda.is_available():
    DEVICE, DEVICE_NAME = 'cuda', torch.cuda.get_device_name(0)
else:
    DEVICE, DEVICE_NAME = 'cpu', 'CPU'
DTYPE = torch.float32 if DEVICE == 'cpu' else torch.bfloat16
LANGUAGES = {'en': 'English', 'pt': 'Portuguese'}
MAX_TEXT = 6000  # characters per request: about 15 minutes of speech
# Longer chunks drift (repeats, invented words); the model is steadiest a sentence or two at a time.
MAX_CHUNK = 260
PAUSE_CHUNK, PAUSE_PARAGRAPH = 0.25, 0.6
MAX_UPLOAD = 60 * 1024 * 1024
# Shut down after this long with no page open and nothing to do, to give the GPU memory back.
IDLE_MINUTES = float(os.environ.get('MOUTHPIECE_IDLE_MIN', '20'))


def chunk_deadline(chunk: str) -> float:
    """A healthy chunk takes ~3 s per second of speech on a GPU (far more on the CPU). Far past that,
    the GPU is stuck: a game holding it can make the driver time the job out, and the call never
    returns."""
    return (90 + 0.6 * len(chunk)) * (10 if DEVICE == 'cpu' else 1)


state = {'status': 'loading', 'error': None, 'model': None, 'activity': time.time()}
prompts: dict[str, object] = {}
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
gpu = threading.Lock()
STUCK = 'A placa de vídeo travou (um jogo aberto costuma causar isso). Feche o jogo e reinicie o Mouthpiece.'


def load_model():
    try:
        path = snapshot_download(MODEL_ID, revision=MODEL_REVISION)
        state['model'] = Qwen3TTSModel.from_pretrained(
            path, device_map=DEVICE, dtype=DTYPE, attn_implementation='sdpa'
        )
        state['status'] = 'ready'
    except Exception as e:  # shown in the UI
        state['status'], state['error'] = 'error', str(e)


threading.Thread(target=load_model, daemon=True).start()


def check_jobs(now: float):
    """Fails a job whose chunk runs far past its deadline and marks the GPU stuck. The stuck call
    can't be interrupted and keeps the GPU lock, so everything queued behind it fails too, instead of
    waiting forever. Also forgets finished jobs after an hour (their files and history stay on disk)."""
    with jobs_lock:
        running = [j for j in jobs.values() if j['state'] == 'running' and j.get('chunk_deadline')]
        if any(now > j['chunk_deadline'] for j in running):
            state['status'], state['error'] = 'stuck', STUCK
            for j in jobs.values():
                if j['state'] in ('queued', 'running'):
                    j.update(state='error', error=STUCK, t=now)
        for jid in [k for k, j in jobs.items() if j['state'] in ('done', 'error') and now - j['t'] > 3600]:
            del jobs[jid]


def idle(now: float) -> bool:
    busy = any(j['state'] in ('queued', 'running') for j in jobs.values())
    return IDLE_MINUTES > 0 and not busy and now - state['activity'] > IDLE_MINUTES * 60


def watchdog():
    while True:
        time.sleep(5)
        now = time.time()
        check_jobs(now)
        if idle(now):
            os._exit(0)


threading.Thread(target=watchdog, daemon=True).start()


def write_atomic(path: Path, data: str | bytes):
    """Write then rename, so a reader never sees a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    with os.fdopen(fd, 'wb' if isinstance(data, bytes) else 'w') as f:
        f.write(data)
    os.replace(tmp, path)


def voices() -> list[str]:
    return sorted(p.name for p in VOICES.glob('*.wav'))


def clone_prompt(voice: str):
    # Built once per reference: the speaker embedding is the slow part of a clone.
    if voice not in prompts:
        prompts[voice] = state['model'].create_voice_clone_prompt(
            ref_audio=str(VOICES / voice), x_vector_only_mode=True
        )
    return prompts[voice]


def load_pronunciation() -> list[dict]:
    try:
        rules = json.loads(PRONUNCIATION.read_text())
        return [r for r in rules if isinstance(r, dict) and isinstance(r.get('de'), str) and r['de']]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def apply_pronunciation(text: str) -> str:
    for rule in load_pronunciation():
        text = text.replace(rule['de'], str(rule.get('para', '')))
    return text


def split_long(sentence: str) -> list[str]:
    """A sentence over MAX_CHUNK: split at commas/semicolons/dashes, then by words as a last resort."""
    if len(sentence) <= MAX_CHUNK:
        return [sentence]
    out, current = [], ''
    for piece in re.split(r'(?<=[,;:—–])\s+', sentence):
        words = piece.split()
        while words:
            # A piece too long on its own is cut by words.
            take, n = '', 0
            while n < len(words) and len(f'{take} {words[n]}'.strip()) <= MAX_CHUNK:
                take = f'{take} {words[n]}'.strip()
                n += 1
            take, words = (take, words[n:]) if n else (words[0], words[1:])
            if current and len(current) + 1 + len(take) > MAX_CHUNK:
                out.append(current)
                current = take
            else:
                current = f'{current} {take}'.strip()
    if current:
        out.append(current)
    return out


def chunks(text: str) -> list[tuple[str, float]]:
    """(chunk, pause after it) pairs: paragraphs, packed into sentences of at most MAX_CHUNK."""
    out = []
    for para in [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]:
        sentences = [s for raw in re.split(r'(?<=[.!?…])\s+', para.replace('\n', ' ')) for s in split_long(raw)]
        current = ''
        for s in sentences:
            if current and len(current) + 1 + len(s) > MAX_CHUNK:
                out.append((current, PAUSE_CHUNK))
                current = s
            else:
                current = f'{current} {s}'.strip()
        if current:
            out.append((current, PAUSE_PARAGRAPH))
    # Only punctuation left (e.g. "..."): nothing to say.
    return [(c, p) for c, p in out if re.search(r'\w', c)]


def slug(text: str, words: int = 6) -> str:
    t = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return '-'.join(re.findall(r'[a-z0-9]+', t)[:words]) or 'fala'


def run(job_id: str):
    job = jobs[job_id]
    try:
        with gpu:
            if job['state'] != 'queued':  # failed by the watchdog while waiting
                return
            job['state'] = 'running'
            t0 = time.time()
            prompt = clone_prompt(job['voice'])
            parts, sr = [], 24000
            for i, (text, pause) in enumerate(job['chunks']):
                job['chunk_deadline'] = time.time() + chunk_deadline(text)
                wavs, sr = state['model'].generate_voice_clone(
                    text=text, language=LANGUAGES[job['lang']], voice_clone_prompt=prompt
                )
                if job['state'] != 'running':  # the watchdog gave up on it meanwhile
                    return
                parts += [wavs[0].astype(np.float32), np.zeros(int(sr * pause), np.float32)]
                job['done'] = i + 1
            job['chunk_deadline'] = None
            speech = np.concatenate(parts[:-1])
        out = audio.finish(speech, sr)
        buf = io.BytesIO()
        sf.write(buf, out, audio.OUT_SR, subtype='PCM_24', format='WAV')
        write_atomic(OUTPUT / f'{job_id}.wav', buf.getvalue())
        job.update(seconds=round(time.time() - t0, 1), duration=round(len(out) / audio.OUT_SR, 1))
        meta = {k: job[k] for k in ('id', 'text', 'lang', 'voice', 'created', 'filename', 'duration', 'seconds')}
        write_atomic(OUTPUT / f'{job_id}.json', json.dumps(meta, ensure_ascii=False))
        job['state'] = 'done'
    except Exception as e:
        job.update(state='error', error=str(e))
    finally:
        job['t'] = time.time()


app = FastAPI(title='Mouthpiece')
# Only the names this machine uses for itself. Any other Host means a page reached the server
# through DNS rebinding (an attacker's domain pointed at 127.0.0.1) and could otherwise make it
# speak arbitrary text in the user's voice and read the history.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])


@app.middleware('http')
async def guard(request: Request, call_next):
    # Every change needs this header. A website can send a "simple" cross-origin POST (text/plain body,
    # no preflight) that would otherwise replace a voice or shut the app down; a custom header forces
    # the browser's preflight, which this server never approves (no CORS).
    if request.method not in ('GET', 'HEAD') and request.headers.get('x-mouthpiece') != '1':
        return JSONResponse({'detail': 'requisição recusada'}, status_code=403)
    state['activity'] = time.time()  # an open page polls every few seconds and keeps this fresh
    return await call_next(request)


class GenerateRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    lang: str = 'en'
    voice: str | None = None


class Rule(BaseModel):
    de: str = Field(max_length=200)
    para: str = Field(default='', max_length=200)


@app.get('/api/status')
def status():
    return {'status': state['status'], 'error': state['error'], 'device': DEVICE, 'gpu': DEVICE_NAME,
            'voices': voices(), 'max_text': MAX_TEXT, 'data': str(DATA)}


@app.post('/api/generate')
def generate(req: GenerateRequest):
    if state['status'] == 'stuck':
        raise HTTPException(503, STUCK)
    if state['status'] != 'ready':
        raise HTTPException(503, 'o modelo ainda está carregando' if state['status'] == 'loading' else state['error'])
    if req.lang not in LANGUAGES:
        raise HTTPException(400, 'idioma inválido')
    text = req.text.strip()
    if not text:
        raise HTTPException(400, 'texto vazio')
    available = voices()
    if not available:
        raise HTTPException(400, 'nenhuma voz ainda: crie a sua em "Vozes"')
    voice = req.voice or next((v for v in available if v.endswith(f'-{req.lang}.wav')), available[0])
    if voice not in available:
        raise HTTPException(400, 'voz não encontrada')
    parts = chunks(apply_pronunciation(text))
    if not parts:
        raise HTTPException(400, 'não sobrou nada para falar (confira as regras de pronúncia)')
    job_id = uuid.uuid4().hex[:10]
    created = datetime.now()
    with jobs_lock:
        jobs[job_id] = {
            'id': job_id, 'text': text, 'lang': req.lang, 'voice': voice, 'state': 'queued',
            'chunks': parts, 'done': 0, 'total': len(parts), 't': time.time(),
            'created': created.isoformat(timespec='seconds'),
            'filename': f'{slug(text)}-{created:%Y%m%d-%H%M%S}.wav',
        }
    threading.Thread(target=run, args=(job_id,), daemon=True).start()
    return {'id': job_id}


@app.get('/api/jobs/{job_id}')
def job(job_id: str):
    j = jobs.get(job_id)
    if not j:
        raise HTTPException(404)
    return {k: v for k, v in j.items() if k not in ('chunks', 'chunk_deadline', 't')}


def audio_path(job_id: str) -> Path:
    if not re.fullmatch(r'[0-9a-f]{10}', job_id):
        raise HTTPException(404)
    path = OUTPUT / f'{job_id}.wav'
    if not path.exists():
        raise HTTPException(404)
    return path


def read_meta(job_id: str) -> dict | None:
    try:
        return json.loads((OUTPUT / f'{job_id}.json').read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


@app.get('/api/audio/{job_id}')
def audio_file(job_id: str):
    return FileResponse(audio_path(job_id), media_type='audio/wav')


@app.get('/api/download/{job_id}')
def download(job_id: str):
    path = audio_path(job_id)
    meta = read_meta(job_id) or {}
    return FileResponse(path, media_type='audio/wav', filename=meta.get('filename', f'{job_id}.wav'))


@app.get('/api/history')
def history():
    items = [m for p in OUTPUT.glob('*.json') if (m := read_meta(p.stem))]
    return sorted(items, key=lambda m: m.get('created', ''), reverse=True)[:50]


@app.delete('/api/history/{job_id}')
def forget(job_id: str):
    audio_path(job_id).unlink()
    (OUTPUT / f'{job_id}.json').unlink(missing_ok=True)
    return {'ok': True}


def voice_path(name: str) -> Path:
    if not re.fullmatch(r'[a-z0-9-]{1,60}\.wav', name) or not (VOICES / name).exists():
        raise HTTPException(404, 'voz não encontrada')
    return VOICES / name


def reading_script(lang: str, script_id: str | None) -> str | None:
    """The text the recorder showed (static/scripts.json), if the recording was made reading it."""
    try:
        script = json.loads((ROOT / 'static' / 'scripts.json').read_text())[lang]
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return None
    return ' '.join(s['text'] for s in script['sections']) if script.get('id') == script_id else None


@app.post('/api/voices')
async def add_voice(request: Request, name: str, lang: str, script: str | None = None):
    """The body is the recording itself (WAV, FLAC, OGG or MP3). Its best 30 s of speech become the
    clone reference, voices/<name>-<lang>.wav. The whole recording is kept too, in voices/raw/ with
    the text that was read (when it came from the recorder): with an exact transcript, a future
    version can use the model's more faithful transcript-based cloning."""
    if lang not in LANGUAGES:
        raise HTTPException(400, 'idioma inválido')
    base = slug(name, words=5)
    body = await request.body()
    if not body:
        raise HTTPException(400, 'arquivo vazio')
    if len(body) > MAX_UPLOAD:
        raise HTTPException(413, 'arquivo grande demais (máximo 60 MB)')
    try:
        raw, sr = sf.read(io.BytesIO(body), dtype='float32', always_2d=True)
    except Exception:
        raise HTTPException(400, 'não consegui ler esse áudio (use WAV, FLAC, OGG ou MP3)')
    try:
        clip, speech_s = audio.prepare_reference(raw, sr, seconds=30)
    except ValueError as e:
        raise HTTPException(400, str(e))
    name = f'{base}-{lang}.wav'
    buf = io.BytesIO()
    sf.write(buf, clip, 24000, subtype='PCM_16', format='WAV')
    write_atomic(VOICES / name, buf.getvalue())
    prompts.pop(name, None)  # replaced: rebuild its speaker embedding on next use
    (VOICES / 'raw').mkdir(exist_ok=True)
    full = io.BytesIO()
    sf.write(full, audio.to_mono(raw), sr, subtype='PCM_16', format='FLAC')
    write_atomic(VOICES / 'raw' / f'{base}-{lang}.flac', full.getvalue())
    meta = {'lang': lang, 'sample_rate': sr, 'seconds': round(len(raw) / sr, 1), 'speech': speech_s,
            'script': script, 'transcript': reading_script(lang, script), 'created': datetime.now().isoformat(timespec='seconds')}
    write_atomic(VOICES / 'raw' / f'{base}-{lang}.json', json.dumps(meta, ensure_ascii=False, indent=2))
    return {'name': name, 'seconds': round(len(clip) / 24000, 1), 'speech': speech_s}


@app.get('/api/voices/{name}')
def voice_file(name: str):
    return FileResponse(voice_path(name), media_type='audio/wav')


@app.delete('/api/voices/{name}')
def delete_voice(name: str):
    voice_path(name).unlink()
    prompts.pop(name, None)
    for ext in ('.flac', '.json'):
        (VOICES / 'raw' / name.replace('.wav', ext)).unlink(missing_ok=True)
    return {'ok': True}


@app.get('/api/pronuncia')
def get_pronunciation():
    return load_pronunciation()


@app.put('/api/pronuncia')
def put_pronunciation(rules: list[Rule]):
    if len(rules) > 500:
        raise HTTPException(400, 'regras demais')
    clean = [{'de': r.de, 'para': r.para} for r in rules if r.de]
    write_atomic(PRONUNCIATION, json.dumps(clean, ensure_ascii=False, indent=2) + '\n')
    return clean


@app.post('/api/shutdown')
def shutdown():
    """The page's "quit" button: frees the GPU memory right away."""
    threading.Timer(0.5, lambda: os._exit(0)).start()
    return {'ok': True}


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
