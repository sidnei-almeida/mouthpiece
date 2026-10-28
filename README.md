<p align="center"><img src="brand/logo/lockup.svg" alt="mouthpiece" width="420"></p>

<p align="center"><b>your voice, typed.</b><br>Digite um texto e ouça com a sua própria voz. Tudo roda no seu computador.</p>

---

O Mouthpiece clona a sua voz a partir de uns 15 segundos de gravação e fala qualquer texto com ela, em
**inglês ou português**. Você ouve a prévia e baixa um WAV pronto para a edição. Tem também um comando
de terminal, para scripts e para o Claude Code gerarem narração sozinhos.

Por baixo: [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) (1.7B, clonagem de voz) com PyTorch, na
placa de vídeo (**Intel Arc** ou **NVIDIA**) ou, mais devagar, na CPU. Nada sai do seu computador.

## Instalar

### Windows

Baixe e rode `Mouthpiece-Setup-1.0.0.exe`. O instalador:

1. copia o app (sem pedir administrador);
2. baixa o Python, o PyTorch certo para a sua placa e o modelo de voz, **alguns GB**, mostrando o
   progresso numa janela;
3. cria atalhos no Menu Iniciar (e na Área de Trabalho, se quiser) e o comando `mouthpiece`.

Requisitos: Windows 10/11 64 bits, ~10 GB livres. Recomendado: placa Intel Arc ou NVIDIA com 8 GB+.

### Linux

```bash
git clone https://github.com/sidnei-almeida/mouthpiece && cd mouthpiece
./setup.sh                                   # detecta a placa e baixa tudo (alguns GB)
ln -sf "$PWD/cli.py" ~/.local/bin/mouthpiece # o comando
./start.sh                                   # abre o app
```

Precisa do [uv](https://docs.astral.sh/uv/). Para Intel Arc, o runtime de computação da Intel
(`intel-compute-runtime` e `level-zero-loader`).

## Usar

1. **Vozes → Nova voz:** leia em voz alta o roteiro da tela (1 a 2 minutos), num lugar silencioso.
   Ele tem trechos com tons diferentes (normal, perguntas, empolgado, baixinho), números, nomes e
   todos os sons do idioma, para o clone ter o máximo de dados da sua voz. Também dá para enviar um
   arquivo. O clone usa os melhores 30 s; a gravação inteira fica guardada com o texto lido.
2. **Falar:** escolha EN ou PT, digite e clique **Gerar** (ou `Ctrl+Enter`). A prévia toca sozinha.
3. **Baixar WAV:** mono, 48 kHz, 24 bits, **-16 LUFS**, picos abaixo de -1,5 dBFS. Pronto para mixar.

Uma linha em branco no texto vira uma pausa maior. Textos longos são divididos em frases sozinhos
(até 6.000 caracteres por vez, uns 15 minutos de fala).

**Pronúncia:** regras "escrito → falado" para nomes que saem errados (ex.: `Alien: Isolation` →
`Alien Isolation`). Valem para o app e para o terminal.

**Sair:** o botão **Sair** fecha o Mouthpiece e libera a memória da placa. Sem uso, ele fecha sozinho
depois de 20 minutos.

## Terminal

```bash
mouthpiece say "Twelve years late." -o narracao.wav
mouthpiece say -f roteiro.txt -o narracao.wav --lang pt
echo "texto" | mouthpiece say - -o narracao.wav
mouthpiece say "..." -o cena1.wav --json    # {"path", "duration", "frames_30", "frames_60", ...}
mouthpiece voices | open | status | stop
mouthpiece pronuncia add "Alien: Isolation" "Alien Isolation"
```

Se o app não estiver aberto, o comando abre o servidor sozinho e espera o modelo carregar.

## Claude Code

A skill `claude-skill/narration` ensina o Claude a escrever a fala, gerar com `mouthpiece` e encaixar
no Remotion pela duração em frames. Instale com
`ln -sfn "$PWD/claude-skill/narration" ~/.claude/skills/narration` e peça, por exemplo: *"gera uma
narração para essa cena"*.

## Onde ficam os seus arquivos

| | Windows | Linux |
|---|---|---|
| Vozes, áudios gerados, regras | `%APPDATA%\Mouthpiece` | `~/.local/share/mouthpiece` (no clone do git: a própria pasta) |
| Modelo (~4 GB) | `%USERPROFILE%\.cache\huggingface` | `~/.cache/huggingface` |

Desinstalar remove o app, mas **mantém as suas vozes e o modelo**.

## Cuidados

- **Não gere com um jogo aberto.** O jogo disputa a placa e o driver pode travar a geração. O app
  mostra **"placa travada"**: feche o jogo e reabra o Mouthpiece.
- Use só a sua voz, ou a de quem autorizou. Clonar a voz de outra pessoa sem permissão é imitação.
- Segurança: o servidor só aceita conexões do próprio computador e recusa pedidos vindos de outros
  sites, para que nenhuma página consiga gerar áudio com a sua voz.

## Desenvolvimento

- `brand/` tem o kit de marca (`brand/BRAND.md`); `python3 brand/build.py` gera logos e ícones.
- `install/windows/` tem o instalador (Inno Setup); `install/build-windows.sh` gera o `.exe` no Linux
  via Wine.
- Versões dos pacotes em `requirements.txt` e `setup.*`; o modelo é fixado em `server_model.py`.
