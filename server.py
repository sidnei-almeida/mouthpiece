"""Voice studio: type text, hear it in your cloned voice, export a WAV.

Qwen3-TTS (Base model, voice clone) stays loaded on the Intel Arc GPU through PyTorch XPU. Each
request is a job: the text gets the pronunciation fixes, is split into sentences, generated one
chunk at a time on the GPU (one job at a time), joined with short pauses and normalized to
-16 LUFS / 48 kHz / 24-bit, ready to drop into an edit.

    ./start.sh          (or: .venv/bin/uvicorn server:app --port 7860)
"""
import json
import re
import subprocess
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
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from qwen_tts import Qwen3TTSModel

ROOT = Path(__file__).parent
VOICES = ROOT / 'voices'
OUTPUT = ROOT / 'output'
PRONUNCIATION = ROOT / 'pronuncia.json'
MODEL_ID = 'Qwen/Qwen3-TTS-12Hz-1.7B-Base'
DEVICE = 'xpu' if torch.xpu.is_available() else 'cpu'
LANGUAGES = {'en': 'English', 'pt': 'Portuguese'}
# Longer chunks drift; the model is steadiest a sentence or two at a time.
MAX_CHUNK = 260
PAUSE_SENTENCE, PAUSE_PARAGRAPH = 0.25, 0.6

OUTPUT.mkdir(exist_ok=True)
state = {'status': 'loading', 'error': None, 'model': None}
prompts: dict[str, object] = {}
jobs: dict[str, dict] = {}
gpu = threading.Lock()


def load_model():
    try:
        state['model'] = Qwen3TTSModel.from_pretrained(
            MODEL_ID, device_map=DEVICE, dtype=torch.bfloat16, attn_implementation='sdpa'
        )
        state['status'] = 'ready'
    except Exception as e:  # shown in the UI
        state['status'], state['error'] = 'error', str(e)


threading.Thread(target=load_model, daemon=True).start()


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
    if PRONUNCIATION.exists():
        return json.loads(PRONUNCIATION.read_text())
    return []


def apply_pronunciation(text: str) -> str:
    for rule in load_pronunciation():
        if rule.get('de'):
            text = text.replace(rule['de'], rule.get('para', ''))
    return text


def chunks(text: str) -> list[tuple[str, float]]:
    """(chunk, pause after it) pairs: paragraphs, split into sentences when long."""
    out = []
    for para in [p.strip() for p in re.split(r'\n\s*\n', text) if p.strip()]:
        sentences = re.split(r'(?<=[.!?…])\s+', para.replace('\n', ' '))
        current = ''
        for s in sentences:
            if current and len(current) + len(s) > MAX_CHUNK:
                out.append((current, PAUSE_SENTENCE))
                current = s
            else:
                current = f'{current} {s}'.strip()
        if current:
            out.append((current, PAUSE_PARAGRAPH))
    return out


def slug(text: str, words: int = 6) -> str:
    t = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return '-'.join(re.findall(r'[a-z0-9]+', t)[:words]) or 'fala'


def loudness(path: Path) -> float:
    log = subprocess.run(
        ['ffmpeg', '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128', '-f', 'null', '-'],
        capture_output=True, text=True,
    ).stderr
    summary = log[log.rfind('Integrated loudness'):]
    return float(re.search(r'I:\s+(-?[\d.]+)', summary).group(1))


def finish(raw: Path, out: Path):
    """-16 LUFS by one fixed gain, then a limiter under -1.5 dBFS; 48 kHz 24-bit mono."""
    gain = -16 - loudness(raw)
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
            job['state'] = 'running'
            t0 = time.time()
            prompt = clone_prompt(job['voice'])
            parts, sr = [], 24000
            for i, (text, pause) in enumerate(job['chunks']):
                wavs, sr = state['model'].generate_voice_clone(
                    text=text, language=LANGUAGES[job['lang']], voice_clone_prompt=prompt
                )
                parts += [wavs[0].astype(np.float32), np.zeros(int(sr * pause), np.float32)]
                job['done'] = i + 1
            audio = np.concatenate(parts[:-1])
        raw = OUTPUT / f'{job_id}-raw.wav'
        sf.write(raw, audio, sr)
        finish(raw, OUTPUT / f'{job_id}.wav')
        raw.unlink()
        job.update(state='done', seconds=round(time.time() - t0, 1), duration=round(len(audio) / sr, 1))
        meta = {k: job[k] for k in ('id', 'text', 'lang', 'voice', 'created', 'filename', 'duration', 'seconds')}
        (OUTPUT / f'{job_id}.json').write_text(json.dumps(meta, ensure_ascii=False))
    except Exception as e:
        job.update(state='error', error=str(e))


app = FastAPI()


class GenerateRequest(BaseModel):
    text: str
    lang: str = 'en'
    voice: str | None = None


@app.get('/api/status')
def status():
    return {'status': state['status'], 'error': state['error'], 'device': DEVICE,
            'gpu': torch.xpu.get_device_name(0) if DEVICE == 'xpu' else 'CPU', 'voices': voices()}


@app.post('/api/generate')
def generate(req: GenerateRequest):
    if state['status'] != 'ready':
        raise HTTPException(503, 'o modelo ainda está carregando')
    if req.lang not in LANGUAGES:
        raise HTTPException(400, 'idioma inválido')
    text = req.text.strip()
    if not text:
        raise HTTPException(400, 'texto vazio')
    voice = req.voice or next((v for v in voices() if v.endswith(f'-{req.lang}.wav')), None) or voices()[0]
    if voice not in voices():
        raise HTTPException(400, 'voz não encontrada')
    job_id = uuid.uuid4().hex[:10]
    created = datetime.now()
    jobs[job_id] = {
        'id': job_id, 'text': text, 'lang': req.lang, 'voice': voice, 'state': 'queued',
        'chunks': chunks(apply_pronunciation(text)), 'done': 0, 'created': created.isoformat(timespec='seconds'),
        'filename': f'{slug(text)}-{created:%Y%m%d-%H%M%S}.wav',
    }
    jobs[job_id]['total'] = len(jobs[job_id]['chunks'])
    threading.Thread(target=run, args=(job_id,), daemon=True).start()
    return {'id': job_id}


@app.get('/api/jobs/{job_id}')
def job(job_id: str):
    if job_id not in jobs:
        raise HTTPException(404)
    return {k: v for k, v in jobs[job_id].items() if k != 'chunks'}


def audio_path(job_id: str) -> Path:
    path = OUTPUT / f'{job_id}.wav'
    if not re.fullmatch(r'[0-9a-f]{10}', job_id) or not path.exists():
        raise HTTPException(404)
    return path


@app.get('/api/audio/{job_id}')
def audio(job_id: str):
    return FileResponse(audio_path(job_id), media_type='audio/wav')


@app.get('/api/download/{job_id}')
def download(job_id: str):
    meta = json.loads((OUTPUT / f'{job_id}.json').read_text())
    return FileResponse(audio_path(job_id), media_type='audio/wav', filename=meta['filename'])


@app.get('/api/history')
def history():
    items = [json.loads(p.read_text()) for p in OUTPUT.glob('*.json')]
    return sorted(items, key=lambda m: m['created'], reverse=True)[:50]


@app.delete('/api/history/{job_id}')
def forget(job_id: str):
    audio_path(job_id).unlink()
    (OUTPUT / f'{job_id}.json').unlink(missing_ok=True)
    return {'ok': True}


@app.get('/api/pronuncia')
def get_pronunciation():
    return load_pronunciation()


@app.put('/api/pronuncia')
def put_pronunciation(rules: list[dict]):
    clean = [{'de': r.get('de', ''), 'para': r.get('para', '')} for r in rules if r.get('de')]
    PRONUNCIATION.write_text(json.dumps(clean, ensure_ascii=False, indent=2))
    return clean


app.mount('/', StaticFiles(directory=ROOT / 'static', html=True), name='static')
