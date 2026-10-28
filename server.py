"""Voice studio: type text, hear it in your cloned voice, export a WAV.

Qwen3-TTS (Base model, voice clone) stays loaded on the Intel Arc GPU through PyTorch XPU. Each
request is a job: the text gets the pronunciation fixes, is split into short chunks, generated one
chunk at a time on the GPU (one job at a time), joined with short pauses and normalized to
-16 LUFS / 48 kHz / 24-bit, ready to drop into an edit.

    ./start.sh          (or: .venv/bin/uvicorn server:app --port 7860)
"""
import json
import os
import re
import subprocess
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
from fastapi import FastAPI, HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel

ROOT = Path(__file__).parent
VOICES = ROOT / 'voices'
OUTPUT = ROOT / 'output'
PRONUNCIATION = ROOT / 'pronuncia.json'
# Pinned: a newer upload of the weights or processor can't change or break the voice unannounced.
MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
MODEL_REVISION = 'fd4b254389122332181a7c3db7f27e918eec64e3'
DEVICE = 'xpu' if torch.xpu.is_available() else 'cpu'
LANGUAGES = {'en': 'English', 'pt': 'Portuguese'}
MAX_TEXT = 6000  # characters per request: about 15 minutes of speech
# Longer chunks drift (repeats, invented words); the model is steadiest a sentence or two at a time.
MAX_CHUNK = 260
PAUSE_CHUNK, PAUSE_PARAGRAPH = 0.25, 0.6


def chunk_deadline(chunk: str) -> float:
    """A healthy chunk takes ~3 s per second of speech. Far past that, the GPU is stuck (a game holding
    the Arc makes the driver time the job out, and the call never returns)."""
    return 90 + 0.6 * len(chunk)


OUTPUT.mkdir(exist_ok=True)
state = {'status': 'loading', 'error': None, 'model': None}
prompts: dict[str, object] = {}
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
gpu = threading.Lock()
STUCK = 'A GPU travou (um jogo aberto costuma causar isso). Feche o jogo e reinicie o Voice Studio.'


def load_model():
    try:
        path = snapshot_download(MODEL_ID, revision=MODEL_REVISION)
        state['model'] = Qwen3TTSModel.from_pretrained(
            path, device_map=DEVICE, dtype=torch.bfloat16, attn_implementation='sdpa'
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


def watchdog():
    while True:
        time.sleep(5)
        check_jobs(time.time())


threading.Thread(target=watchdog, daemon=True).start()


def write_atomic(path: Path, text: str):
    """Write then rename, so a reader never sees a half-written file."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}.')
    with os.fdopen(fd, 'w') as f:
        f.write(text)
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


def loudness(path: Path) -> float:
    log = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128', '-f', 'null', '-'],
        capture_output=True, text=True,
    ).stderr
    m = re.search(r'I:\s+(-?[\d.]+)', log[log.rfind('Integrated loudness'):])
    if not m:
        raise RuntimeError('não consegui medir o volume do áudio gerado')
    return float(m.group(1))


def finish(raw: Path, out: Path):
    """-16 LUFS by one fixed gain, then a limiter under -1.5 dBFS; 48 kHz 24-bit mono."""
    level = loudness(raw)
    if level < -50:  # ebur128 reports -70 for silence; a gain to -16 would only amplify hiss
        raise RuntimeError('o modelo devolveu silêncio; tente reescrever o texto')
    gain = min(-16 - level, 30)
    subprocess.run(
        ['ffmpeg', '-v', 'error', '-y', '-i', str(raw), '-af',
         f'volume={gain:.2f}dB,aresample=48000,alimiter=limit=0.84:level=disabled:asc=1',
         '-ar', '48000', '-ac', '1', '-c:a', 'pcm_s24le', str(out)],
        check=True,
    )


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
            audio = np.concatenate(parts[:-1])
        raw = OUTPUT / f'{job_id}-raw.wav'
        sf.write(raw, audio, sr)
        try:
            finish(raw, OUTPUT / f'{job_id}.wav')
        finally:
            raw.unlink(missing_ok=True)
        job.update(seconds=round(time.time() - t0, 1), duration=round(len(audio) / sr, 1))
        meta = {k: job[k] for k in ('id', 'text', 'lang', 'voice', 'created', 'filename', 'duration', 'seconds')}
        write_atomic(OUTPUT / f'{job_id}.json', json.dumps(meta, ensure_ascii=False))
        job['state'] = 'done'
    except Exception as e:
        job.update(state='error', error=str(e))
    finally:
        job['t'] = time.time()


app = FastAPI()
# Only the names this machine uses for itself. Any other Host means a page reached the server
# through DNS rebinding (an attacker's domain pointed at 127.0.0.1) and could otherwise make it
# speak arbitrary text in the owner's voice and read the history.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])


class GenerateRequest(BaseModel):
    text: str = Field(max_length=MAX_TEXT)
    lang: str = 'en'
    voice: str | None = None


class Rule(BaseModel):
    de: str = Field(max_length=200)
    para: str = Field(default='', max_length=200)


@app.get('/api/status')
def status():
    return {'status': state['status'], 'error': state['error'], 'device': DEVICE,
            'gpu': torch.xpu.get_device_name(0) if DEVICE == 'xpu' else 'CPU', 'voices': voices(),
            'max_text': MAX_TEXT}


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
        raise HTTPException(400, 'nenhuma voz em voices/ (veja voices/README.md)')
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
def audio(job_id: str):
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


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
