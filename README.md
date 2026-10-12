# Consultoria — Thumbs + Legendas (Crescer Seco)

Scripts do fluxo de produção dos vídeos da série **Crescer Seco**
(musculação / wellness, formato vertical TikTok / Reels / Shorts):

1. **`thumb_generator.py`** — gera as thumbnails/capas de cada episódio
   (TikTok 1080x1350 e Reels 1080x1920, padrão EP + título + tagline).
2. **`legendar_video.py`** — legenda os vídeos no padrão TikTok
   (karaoke estilo LIFE IN MOTION, embaixo sem cobrir perfil/descrição,
   números 0–9 por extenso e em dígito acima disso, palavrão com `*`,
   vocabulário de academia + DE/PARA com o roteiro).

## Estrutura

```text
consultoria/
├── thumb_generator.py   # gerador de thumbs
├── legendar_video.py    # transcrição + legenda queimada no vídeo
├── fonts/               # Anton, JetBrains Mono, Space Mono (usadas nas thumbs)
├── README.md
└── epN/                 # por episódio: ep8.mov + roteiro_ep8.txt (+ revisões geradas)
```

## Requisitos

- Python 3 + `ffmpeg`/`ffprobe` no PATH (`sudo apt install ffmpeg`)
- Thumb: Pillow (o script cria `.venv` local e instala sozinho se faltar)
- Legenda: `pip install faster-whisper` (rode dentro de uma venv);
  na 1ª vez baixa ~800MB do modelo (depois fica em cache)

## Thumbs

```bash
# interativo (pergunta episódio, título, subtítulo e foto-base)
python3 thumb_generator.py

# linha de comando, sem subtítulo (usa "natural · sem pressa")
python3 thumb_generator.py --episode-number 8 --title "QUANTO CUSTA MONTAR | UMA ACADEMIA EM CASA?"

# linha de comando, com subtítulo
python3 thumb_generator.py --episode-number 8 --title "TITULO LINHA 1 | LINHA 2" --subtitle "treino · sem pressa"

# foto em qualquer lugar (output cai ao lado dela, sem copiar)
python3 thumb_generator.py --base-dir ~/Videos/projeto --episode-number 8 \
  --title "TITULO LINHA 1 | LINHA 2" --base-image ~/consultoria/ep8/base.jpeg
```

- `--base-dir`: pasta do projeto (acha foto de `thumbs/epN/` e as fontes; padrão: pasta do script).
- `--base-image`: a foto manda no output — os PNGs caem na mesma pasta dela.
- Saídas: `<pasta-da-foto>/epN-tiktok-1080x1350.png` e `<pasta-da-foto>/epN-reels-1080x1920.png`.

## Legendas (2 etapas: transcrever → revisar → queimar)

```bash
# 1. só transcreve e gera .srt/.json de revisão (não queima o vídeo)
python3 legendar_video.py ep8.mov --somente-transcrever --srt \
  --base-dir ~/consultoria/ep8 --roteiro roteiro_ep8.txt \
  --modo-texto baixa

# revise o ep8_revisao.srt (texto, cortes, tempos) no editor de texto

# 2. queima o .srt revisado no vídeo
python3 legendar_video.py ep8.mov --base-dir ~/consultoria/ep8 \
  --de-srt ep8_revisao.srt --cor "#25F4EE"
```

O que acontece na etapa 1, em ordem:

1. **Transcreve** com Whisper `large-v3-turbo` (o melhor; `--modelo small` = rascunho rápido),
   usando `--roteiro` como guia de nomes, aparelhos e números. Barra de progresso no terminal.
2. **Limpa e normaliza**: sem vírgula/ponto/dois-pontos aleatórios; 0–9 por extenso
   (`1 coisa` → `uma coisa`), ≥10 em dígito (`6 mil` → `6.000`, `15`+`534` → `15.534`);
   `%` sempre dígito (`5%`); `MERD*` mascarado; `Fábio` → `fabio`.
3. **Revisão de academia**: corrige aparelho (`hac`→`hack`, `supindo`→`supino`,
   `revisamento`→`revezamento`, `trem`→`treino` salvo em contexto de viagem).
4. **DE/PARA com o roteiro** (mostra no terminal o que trocou): conserta truncamento
   (`gol`→`golpe`), 1 letra trocada (`coisa`→`coisas`) e insere palavra comida
   (`250 em 250 [+gramas]`). Improviso grande, número e seu coloquial (`pra`, `tá`) intactos.
5. **Corta em cartelas** (`--palavras auto`: 1 no grito/pausa, 3–4 na fala corrida;
   `são paulo` e `de`+próxima nunca partem; ênfase como `CANSADO` fica solo segurando 1.6s).

A etapa 2 queima com animação LIFE IN MOTION (varredura `--cor`, 30% mais lenta via
`SWEEP_FATOR`, texto `--cor-texto`, borda preta), com barra de progresso.
O legendado cai na **mesma pasta do vídeo original** (`-o` relativo resolve lá também).

- `--palavras auto|2|3|4`, `--margem-v` (altura: maior = mais alta, longe da descrição),
  `--cor` / `--cor-texto`, `--modo-texto baixa|alta|original`.
- Nunca deixe um `.srt` com o **mesmo nome** do `.mp4` final na mesma pasta:
  o player carrega sozinho e mostra legenda dupla.

## Ajustes frequentes (constantes no topo de cada script)

- `legendar_video.py`: `COR_ANIMACAO`, `MODO_TEXTO`, `PALAVRAS_POR_LEGENDA`,
  `ALTURA_LEGENDA`, `SWEEP_FATOR`, `VOCAB_ACADEMIA`, `ERROS_COMUNS`, `PALAVROES`,
  `CORRECOES`, `LIGANTES`, `COLA_FRASES`, `COLOQUIAL`.
- `thumb_generator.py`: tudo via CLI (`--episode-number`, `--title`, `--subtitle`,
  `--base-dir`, `--base-image`).
