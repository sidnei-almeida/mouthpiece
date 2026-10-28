---
name: narration
description: >
  Write and generate voice-over in the owner's own cloned voice with the local `mouthpiece` CLI
  (Qwen3-TTS on the Intel Arc), and place it in a Remotion timeline. Use when the user asks for
  narration, voice-over, a voice line, "narrar", "narração", "locução", "gera o áudio dessa cena",
  or when editing a video (Remotion or otherwise) where a scene needs spoken audio. Also for
  hooks, outros and subscribe lines for the Dude, We Late channel.
---

# Narration in the owner's voice

`mouthpiece` turns text into speech in the owner's cloned voice. It runs locally: a server keeps the
model on the GPU and the CLI starts it on demand (first call ~10-70 s to load, then ~3 s of
generation per second of speech). Source: `~/ai/mouthpiece` (README, `server.py`, `cli.py`).

## 1. Write the line

- Channel: **Dude, We Late**, gaming video essays and blind playthroughs, narrated in **English**
  unless the user says otherwise (`--lang pt` for Portuguese).
- Tone: conversational, dry humor, understated. The running joke is being late (games played long
  after the hype). No announcer voice, no hype words, no "smash that like button".
- Short sentences; one idea each. Write numbers and years as words ("twenty fourteen") and spell
  tricky names the way they are said; the model reads text literally.
- Match the scene: say what the picture needs, don't describe what is plainly on screen.
- Show the user the text before generating anything long, and keep their wording when they give it.

## 2. Generate

```bash
mouthpiece say "Line to speak." -o public/narration/<scene>.wav --json      # English
mouthpiece say -f script.txt -o public/narration/<scene>.wav --json         # from a file
mouthpiece say "Fala aqui." -o public/narration/<scene>.wav --lang pt --json
```

`--json` prints `{"path", "duration", "frames_30", "frames_60", "generated_in"}`. Output is a
48 kHz 24-bit mono WAV at -16 LUFS, peaks under -1.5 dBFS: ready to mix, no further processing.

- Blank lines in the text become longer pauses; long text is split into sentences automatically.
- Mispronounced name? Add a rule once and regenerate:
  `mouthpiece pronuncia add "Alien: Isolation" "Alien Isolation"` (`mouthpiece pronuncia` lists them).
- Never overwrite a narration file the user already approved; write a new name (`scene1-v2.wav`).
- Generation hangs or is very slow: a game is probably using the GPU. Say so; don't loop retries.
  `mouthpiece status` / `mouthpiece stop` manage the server.

## 3. Put it in Remotion

Files go in the project's `public/narration/`. Size the scene from the JSON, not by guessing:

```tsx
import { Audio, Sequence, staticFile } from 'remotion';

// duration 4.0 s -> frames_30 = 120
<Sequence from={sceneStart} durationInFrames={120 + 15 /* breathing room */}>
  <Audio src={staticFile('narration/scene1.wav')} />
</Sequence>
```

- Game audio under narration sits about 10-12 dB lower (narration is -16 LUFS; game around -26 to
  -28 LUFS). Duck it with an `Audio` volume callback over the narration's frames.
- Narration should start a few frames after a cut, not on it.

## 4. Hand it back

I can't listen to audio. After generating, give the user the file path (and copy it to
`~/Downloads/` if they review there) and ask them to listen for pronunciation and pacing before
building the scene around it. Fix by rewording the text or adding a pronunciation rule.
