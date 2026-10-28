# Dude, We Late — Voice Studio

Texto para fala com **a sua voz clonada**, rodando local na placa de vídeo (Intel Arc B580). Você digita,
ouve uma prévia e baixa o WAV pronto para a edição. Também tem um **CLI**, para que o Claude Code gere
narração sozinho enquanto edita vídeos.

Por baixo: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (modelo 1.7B Base, clonagem de voz) via
PyTorch XPU.

## Instalar

```bash
./setup.sh                                       # uma vez: ambiente Python (~alguns GB)
cp /caminho/sua-voz-en.wav voices/minha-voz-en.wav   # referência: 10-15 s de fala limpa
cp /caminho/sua-voz-pt.wav voices/minha-voz-pt.wav
ln -sf "$PWD/cli.py" ~/.local/bin/dwl-voice      # o comando dwl-voice
ln -sfn "$PWD/claude-skill/narration" ~/.claude/skills/narration   # a skill do Claude Code
```

O modelo (~4 GB) baixa sozinho no primeiro uso, para `~/.cache/huggingface`.

## Usar pela página

```bash
./start.sh        # abre http://127.0.0.1:7860
```

- Escolha **EN** ou **PT**, digite e clique **GERAR** (ou `Ctrl+Enter`).
- A prévia toca sozinha. **BAIXAR WAV** salva o arquivo com nome tirado do texto.
- **Histórico:** ouvir, baixar, reaproveitar o texto ou apagar.
- **Pronúncia:** regras "escrito → falado" para nomes que o modelo erra (ex.: `Alien: Isolation` →
  `Alien Isolation`). Valem para a página e para o CLI.

## Usar pelo terminal

```bash
dwl-voice say "Twelve years late." -o narracao.wav
dwl-voice say -f roteiro.txt -o narracao.wav --lang pt
echo "texto" | dwl-voice say - -o narracao.wav
dwl-voice say "..." -o cena1.wav --json    # {"path", "duration", "frames_30", "frames_60", ...}
dwl-voice pronuncia add "Alien: Isolation" "Alien Isolation"
dwl-voice status | dwl-voice stop
```

Se o servidor não estiver rodando, o CLI liga ele sozinho e espera o modelo carregar.

## Com o Claude Code

A skill `narration` (`claude-skill/narration/SKILL.md`) ensina o Claude a escrever a fala no tom do
canal, gerar com `dwl-voice` e encaixar no Remotion usando a duração em frames. É só pedir, por
exemplo: *"gera uma narração para essa cena explicando o motion tracker"*.

## Saída

WAV mono, 48 kHz, 24 bits, **-16 LUFS** e picos abaixo de -1,5 dBFS: pronto para mixar com o jogo
(10–12 dB abaixo da voz).

## Cuidados

- **Não gere com um jogo aberto.** O jogo ocupa a placa, e o driver da Arc pode travar o trabalho.
- Velocidade na Arc: ~3 s de geração por segundo de fala, mais ~10 s para carregar o modelo.
- O clone copia o timbre **e o jeito** da gravação de referência (veja `voices/README.md`).
- As gravações da sua voz (`voices/*.wav`) e os áudios gerados (`output/`) ficam fora do git.
