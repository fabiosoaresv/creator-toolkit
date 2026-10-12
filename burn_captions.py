#!/usr/bin/env python3
r"""
Legendar vídeo - padrão TikTok / Reels
======================================
- Transcreve com faster-whisper (word timestamps)
- Limpa pontuação bizarra (vírgula/ponto/dois-pontos aleatórios)
- Normaliza números: 0-9 por extenso, >=10 em dígito, % como 1%, 5%...
- Caixa alta/baixa configurável
- Queima legenda embaixo, mas NÃO colada no rodapé (não cobre perfil+descrição)
- Estilo TikTok: 2-3 palavras por vez, centralizado, com destaque da palavra falada
- Animação LIFE IN MOTION: cor varrendo a palavra (karaoke kf), cor em COR_ANIMACAO

Uso (2 etapas: transcrever -> revisar o .srt -> queimar):
  pip install faster-whisper
  sudo apt install ffmpeg

  # Gerar SRT
  # . ~/.venv/bin/activate && python burn_captions.py /home/fabio.venturelli/consultoria/ep7/ep7.mov --somente-transcrever --srt -o ep7_legendado.mp4 --roteiro /home/fabio.venturelli/consultoria/ep7/roteiro_ep7.txt --modo-texto baixa

  # Queimar legenda no video
  . ~/.venv/bin/activate && python burn_captions.py /home/fabio.venturelli/consultoria/ep7/ep7.mov -o ep7_legendado.mp4 --de-srt /home/fabio.venturelli/consultoria/ep7/ep7_revisao.srt --cor "#f1f509" 
  
  # 1. só transcreve e gera .srt de revisão (não queima o vídeo).
  #    --roteiro guia nomes, aparelhos e números (mesmo com improviso).
  #    Sem --modelo usa large-v3-turbo (o melhor: menos erro, menos revisão).
  #    Modelos: tiny < base < small < medium < large-v3-turbo ≈ large-v3.
  #    --base-dir diz onde está o EP: revisão (.srt/.json) e legendado caem lá.
  python burn_captions.py ep8.mov --somente-transcrever --srt \
    --base-dir ~/consultoria/ep8 --roteiro roteiro_ep8.txt \
    --palavras auto --modo-texto baixa

  # revise o ep8_revisao.srt (texto, cortes, tempos) e depois:

  # 2. queima o .srt revisado no vídeo (animação LIFE IN MOTION):
  python burn_captions.py ep8.mov --base-dir ~/consultoria/ep8 \
    --de-srt ep8_revisao.srt --cor "#25F4EE"

  # Nunca deixe um .srt com o MESMO nome do .mp4 final na mesma pasta:
  # o player carrega sozinho e mostra legenda dupla.
"""

from __future__ import annotations
import argparse
import os
import re
import subprocess
import sys
import tempfile

# ============================================================
# CONFIGURÁVEIS - edite aqui o padrão
# ============================================================

MODELO_WHISPER = "large-v3-turbo"  # DEFAULT = melhor (precisão de large, ~3x mais rápido).
# Escada tiny < base < small < medium < large-v3-turbo ≈ large-v3 (topo).
# Maior = menos erro (poupa revisão do srt), porém mais lento + baixa ~800MB na 1ª vez.
# Passe --modelo p/ trocar (ex: --modelo small p/ rascunho rápido).
IDIOMA = "pt"                     # "pt" trava em português, None = auto

MODO_TEXTO = "baixa"              # "baixa" = tudo minúsculo | "alta" = tudo MAIÚSCULO | "original" = mantém
PALAVRAS_POR_LEGENDA = "auto"    # "auto" = corta pela fala (pausas/duração/tamanho). Ou N fixo: 2, 3, 4.
AUTO_MAX_CHARS = 30               # cartela corta aqui (evita parede de texto)
AUTO_MIN_CHARS = 10               # abaixo disso não corta por tamanho (não isola "de", "que")
AUTO_MIN_DUR = 0.7                # com essa duração já pode cortar se houver respiro
AUTO_PAUSA_CORTE = 0.18           # pausa que já rende corte quando a cartela tem corpo
AUTO_MAX_PALAVRAS = 4             # teto de segurança no modo auto
MAX_GAP = 0.35                    # se pausa maior que isso, quebra a legenda (era 0.45)
MAX_DURACAO = 2.8                 # segundos máximos por cartela (era 2.2: segura mais tempo na tela)
MIN_DURACAO_CARTELA = 1.1         # cartela nunca pisca mais rápido que isso (segura o fim)
MIN_DURACAO_SOLO = 1.6            # palavra solo (ênfase) segura ainda mais (era ela que "passava voando")
ESTENDER_ATE_PROXIMA = True       # segura cartela até a próxima começar (menos piscada). Máx extra abaixo.
HOLDE_MAX_EXTRA = 0.6             # quanto pode estender no máx (s)

# Cola: palavras que se conectam nunca partem ("são paulo", "estado de | são").
# 1. LIGANTES: cartela nunca TERMINA com essas (preposição/artigo/conjunção).
# 2. COLA_FRASES: expressões que andam grudadas (lugar, termo técnico, marca).
LIGANTES = {
    "de", "do", "da", "dos", "das", "dum", "duma", "em", "no", "na", "nos",
    "nas", "num", "numa", "para", "pra", "pro", "pras", "pros", "por",
    "pelo", "pela", "pelos", "pelas", "com", "sem", "sob", "sobre", "entre",
    "ate", "até", "que", "e", "ou", "mas", "porem", "porém", "se", "como",
    "o", "a", "os", "as", "uns", "umas", "meu", "minha", "teu", "tua",
    "seu", "sua", "esse", "essa", "este", "esta", "isso", "isto", "aquele",
    "aquela", "ao", "à", "aos", "às", "desse", "dessa", "deste", "desta",
    "nesse", "nessa", "neste", "nesta", "naquele", "naquela", "disso", "nisso",
}
COLA_FRASES = [
    "são paulo", "rio de janeiro", "belo horizonte", "minas gerais",
    "mato grosso", "mato grosso do sul", "espírito santo", "santa catarina",
    "rio grande do sul", "rio grande do norte", "distrito federal",
    "estado de são paulo", "educação física", "massa magra",
    "academia em casa", "barra olímpica", "mono cross", "leg press",
    "hack squat", "puxada alta", "remada baixa", "cadeira extensora",
    "mesa flexora", "elevação lateral", "levantamento terra", "supino reto",
    "supino inclinado", "supino declinado", "rosca direta", "crescer seco",
]

# Palavras de ênfase ficam SOLO na cartela. Ex: "software" | "cansado" (nunca "software cansado").
# Detecção automática: palavra GRITADA no áudio (whisper vem em CAPS ou com !),
# palavra longa (ênfase na fala) ou pausa forte antes dela.
# Complete com as suas (minúsculo, sem acento extra importa — compara normalizado):
ISOLAR_PALAVRAS = {"cansado", "cansada", "cansados", "cansadas"}
ISOLAR_ENFASE_AUTO = True         # True = detecta CAPS/!/duração longa sozinho
DURACAO_ENFASE = 0.5              # palavra mais longa que isso vira candidata a solo (s)
PAUSA_ENFASE = 0.30               # pausa antes da palavra já força quebra (s)

# Posição: TikTok tem descrição + barra embaixo, perfil do lado.
# Por isso NÃO usar MarginV baixo (ex: 60 cobre a descrição).
# 1080x1920 -> 340~420 fica no "meio-baixo" ideal. 720x1280 -> 230~280.
ALTURA_LEGENDA = 380              # MarginV quando Alignment=2 (bottom-center). Aumente p/ subir, diminua p/ descer.
ALINHAMENTO = 2                   # 2 = embaixo-centralizado (com MarginV alto). 5 = meio exato.

FONTE = "Montserrat ExtraBold"    # caia para "Arial" se não tiver Montserrat instalada
TAMANHO_FONTE = 84                # para 1080x1920. Se vídeo 720p, o script reduz sozinho.

# --- Animação estilo TikTok Studio "LIFE IN MOTION" ---
# A cor varre a palavra da esquerda para a direita acompanhando a fala
# (efeito karaoke \kf). Troque aqui para a cor que quiser.
COR_TEXTO = "#FFFFFF"             # cor base (palavra ainda não falada)
COR_ANIMACAO = "#FFD900"          # cor da animação que passa pela palavra (amarelo TikTok). Ex: "#00E5FF", "#7CFC00", "#FF2E93"
COR_CONTORNO = "#000000"          # contorno preto
ESPESSURA_CONTORNO = 3.2
SOMBRA = 0
FADE_IN_MS = 120                  # suaviza entrada da cartela (ms)
FADE_OUT_MS = 120                 # suaviza saída da cartela (ms)
SWEEP_FATOR = 1.3                 # varredura 30% mais lenta: cada palavra ganha tempo
                                  # roubado da pausa seguinte (sincronismo mantido)

# Pontuação: tudo que causa "vírgula nada a ver, ponto final aleatório, dois pontos do nada"
# é removido. Mantemos só o essencial.
MANTER_PONTUACAO = {"!", "?", "%"}  # ex: {"!", "?", "%"} | set() = remove tudo
REMOVER_Sempre = {",", ".", ":", ";", "…", "...", '"', "'", "“", "”", "«", "»", "(", ")", "[", "]", "*", "#", "-", "–", "—"}

# Correções fixas (whisper erra nome/termo): chave minúscula sem caixa, valor já final.
# Ex: nome sem acento.
CORRECOES = {
    "fábio": "fabio",
    "fabio venturelli": "fabio venturelli",
}

# Palavrões: mascara última letra com * (merda -> merd*). Adicione os seus aqui.
MASCARAR_PALAVRAO = True
PALAVROES = {
    "merda", "merdas", "bosta", "bostas", "porra", "porras",
    "caralho", "caralhos", "cacete", "cacetes", "puta", "putas",
    "puto", "putos", "putaria", "foda", "fodas", "fode", "foder",
    "fodendo", "fodido", "fodida", "pica", "pinto", "cuzao", "cuzão",
    "cuzoes", "arrombado", "arrombada", "krl", "carai", "caralho",
    "vsf", "pqp", "tnc",
}

# ============================================================
# Revisão verbal: vocabulário de musculação/wellness.
# O whisper erra termo técnico ("hac"->rack, "supindo"->supino).
# Essa passada corrige ANTES de gerar o srt final.
# ============================================================
REVISAO_VERBAL = True
LIMIAR_FUZZY = 0.84  # 0-1: maior = mais conservador. 0.84 pega supindo->supino sem trocar palavra comum.

# Termos canônicos (minúsculo). Frases com espaço também valem.
VOCAB_ACADEMIA = [
    "supino", "supino reto", "supino inclinado", "supino declinado",
    "rack", "rack de agachamento", "agachamento", "agachamento livre",
    "agachamento búlgaro", "hack", "hack squat", "leg press",
    "smith", "pulley", "crossover", "cross over", "peck deck", "voador",
    "remada", "remada baixa", "remada alta", "remada curvada",
    "puxada", "puxada alta", "puxada frente", "barra fixa",
    "halter", "halteres", "kettlebell", "anilha", "anilhas", "barra",
    "rosca direta", "rosca alternada", "rosca martelo", "tríceps", "triceps testa",
    "cadeira extensora", "extensora", "mesa flexora", "flexora", "cadeira flexora",
    "adutora", "abdutora", "panturrilha", "panturrilheira",
    "desenvolvimento", "elevação lateral", "crucifixo", "stiff",
    "levantamento terra", "deadlift", "squat", "bench press",
    "esteira", "bike", "bicicleta ergométrica", "elíptico", "escada", "remador",
    "mobilidade", "alongamento", "cardio", "hipertrofia", "treino", "série", "repetição",
    "carga", "amplitude", "falha", "deltoide", "peitoral", "dorsal", "quadríceps",
    "posterior", "glúteo", "panturrilha", "core", "lombar", "wellness", "musculação",
    "mono cross", "microanilha", "microanilhas", "microprogressão", "progressão",
    "caneleira", "caneleiras",
    "adipômetro", "oxímetro", "mini bike", "tatame", "anilha", "anilhas",
]

# Erros já observados: correção exata (mais forte que o fuzzy).
ERROS_COMUNS = {
    "hac": "hack",
    "hacki": "hack",
    "haque": "hack",
    "supindo": "supino",
    "supinda": "supino",
    "supina": "supino",
    "legpresso": "leg press",
    "legpress": "leg press",
    "micropressao": "microprogressão",
    "micropressão": "microprogressão",
    "micropreção": "microprogressão",
    "pulley": "pulley",
    "puli": "pulley",
    "rosca": "rosca",
    "revisamento": "revezamento",
}

# Coloquial blindado: nunca troca pra/para, tá/está etc. (seu jeito de falar
# vale mais que o roteiro nesses).
COLOQUIAL = {
    "pra", "pro", "pras", "pros", "ta", "to", "tava", "tavam", "ne",
    "bora", "pera", "perai", "ce", "cê",
}

# ============================================================
# Números por extenso <-> dígito (pt-BR)
# Regra pedida:
#  0..9   -> sempre extenso: zero, um, dois ... nove
#  >=10   -> sempre dígito: 10, 11, 100, 200, 1000, 1 milhão etc.
#  %      -> sempre dígito + %: 1%, 5%, 100%
# ============================================================

DIGITO_PARA_EXTENSO = {
    "0": "zero", "1": "um", "2": "dois", "3": "três", "4": "quatro",
    "5": "cinco", "6": "seis", "7": "sete", "8": "oito", "9": "nove",
}

EXTENSO_BASE = {
    "zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "sete": 7, "oito": 8, "nove": 9,
    "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
    "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19,
    "vinte": 20, "trinta": 30, "quarenta": 40, "cinquenta": 50,
    "sessenta": 60, "setenta": 70, "oitenta": 80, "noventa": 90,
    "cem": 100, "cento": 100, "duzentos": 200, "duzentas": 200,
    "trezentos": 300, "trezentas": 300, "quatrocentos": 400, "quatrocentas": 400,
    "quinhentos": 500, "quinhentas": 500, "seiscentos": 600, "seiscentas": 600,
    "setecentos": 700, "setecentas": 700, "oitocentos": 800, "oitocentas": 800,
    "novecentos": 900, "novecentas": 900, "mil": 1000,
    "milhão": 1_000_000, "milhao": 1_000_000, "milhões": 1_000_000, "milhoes": 1_000_000,
    "bilhão": 1_000_000_000, "bilhao": 1_000_000_000, "bilhões": 1_000_000_000, "bilhoes": 1_000_000_000,
}
IGNORAR_NUMERO = {"e", "de", "em"}


def formatar_numero_br(n: int) -> str:
    """1000 -> 1.000 | 1000000 -> 1.000.000 (padrão BR, sem casa decimal)."""
    return f"{n:,}".replace(",", ".")


def tentar_converter_sequencia_extenso(tokens: list[str]) -> tuple[int | None, int]:
    """
    Tenta ler tokens[0:n] como um número por extenso >= 10.
    Retorna (valor, qtd_tokens_consumidos) ou (None, 0).
    Ex: ["cento", "e", "vinte"] -> (120, 3)
    """
    vals: list[int] = []
    i = 0
    while i < len(tokens):
        t = tokens[i].lower().strip(",.:;!?%")
        if t in IGNORAR_NUMERO:
            i += 1
            continue
        if t in EXTENSO_BASE:
            v = EXTENSO_BASE[t]
            # mil / milhão multiplicam o acumulado
            if v == 1000 or v >= 1_000_000:
                acc = sum(vals) if vals else 1
                vals = [acc * v]
            else:
                vals.append(v)
            i += 1
        else:
            break
    if not vals:
        return None, 0
    # soma simples resolve 0..999 + compostos com "e" (cento e vinte = 100+20)
    total = sum(vals)
    # só converte se >= 10 (0..9 ficam por extenso pela regra)
    if total < 10:
        return None, 0
    return total, i


def limpar_palavra(w: str) -> str:
    """Remove pontuação bizarra, mantém só o configurado."""
    out = []
    for ch in w:
        if ch in REMOVER_Sempre:
            continue
        if ch.isalnum() or ch in ("%",):
            out.append(ch)
        elif ch in MANTER_PONTUACAO:
            out.append(ch)
        # resto (símbolos estranhos) descarta
    # remove . , : ; grudados no fim por segurança (whisper adora inventar)
    palavra = "".join(out).strip()
    palavra = re.sub(r"[,.:;]+$", "", palavra)
    palavra = re.sub(r"^[,.:;]+", "", palavra)
    return palavra


def aplicar_caixa(texto: str, modo: str) -> str:
    if modo == "baixa":
        return texto.lower()
    if modo == "alta":
        return texto.upper()
    return texto


def mascarar_palavrao(palavra: str) -> str:
    """merda -> merd* | preserva sufixo !?% e caixa já aplicada."""
    if not MASCARAR_PALAVRAO:
        return palavra
    m = re.match(r"^(.+?)([!?%]+)?$", palavra)
    nucleo, suf = (m.group(1), m.group(2) or "") if m else (palavra, "")
    if nucleo.lower() in PALAVROES and len(nucleo) >= 2:
        return nucleo[:-1] + "*" + suf
    # plural/variação simples: termina com palavrão + s? ex: "merdas" já listado; resto ignora
    return palavra


def sem_acento(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def revisao_verbal(palavras: list[dict], vocab_extra: set[str] | None = None) -> list[dict]:
    """Passada de revisão antes do srt final: corrige termos de academia.

    1. ERROS_COMUNS (exato): 'hac'->'rack', 'supindo'->'supino'.
    2. Fuzzy 1 palavra: troca só se parecida (>=LIMIAR_FUZZY) e len>=4,
       sem mexer em número/% nem palavrão mascarado.
    3. Frases: 'rack agachamento' -> 'rack de agachamento' (distribui tempos).
    Roda ANTES da caixa: compara minúsculo, preserva tempos.
    """
    import difflib
    if not REVISAO_VERBAL or not palavras:
        return palavras

    vocab_1 = {}  # norm -> canônico (só 1 palavra)
    frases = []   # [(norm_joined, [canon_words])]
    for v in VOCAB_ACADEMIA:
        partes = v.lower().split()
        if len(partes) == 1:
            vocab_1.setdefault(sem_acento(partes[0]), partes[0])
        else:
            frases.append((" ".join(sem_acento(p) for p in partes), partes))
    frases.sort(key=lambda x: -len(x[1]))  # frases longas primeiro
    # roteiro entra como evidência forte: palavra do roteiro tem prioridade
    extra_norm = {}
    if vocab_extra:
        for w in vocab_extra:
            wl = w.lower()
            extra_norm.setdefault(sem_acento(wl), wl)
    # par confusível rack/hack: segue o roteiro (ex: seu caso é hack)
    tem_hack = extra_norm and ("hack" in extra_norm) and ("rack" not in extra_norm)
    tem_rack = extra_norm and ("rack" in extra_norm) and ("hack" not in extra_norm)

    # "micro pressão" (whisper separando) -> "microprogressão" (1 token, tempos unidos)
    i = 0
    while i < len(palavras) - 1:
        a = sem_acento(palavras[i]["word"].lower())
        b = sem_acento(palavras[i + 1]["word"].lower()).rstrip("!?%")
        if a == "micro" and b in ("pressao", "progressao", "precao", "pressa", "presa"):
            t0, t1 = palavras[i]["start"], palavras[i + 1]["end"]
            palavras[i:i + 2] = [{"word": "microprogressão", "start": t0, "end": t1, "enfase": False}]
        i += 1

    # passo 1+2: palavra a palavra
    for idx_p, p in enumerate(palavras):
        w = p["word"]
        if not w or w.endswith("%") or "*" in w:
            continue
        if re.fullmatch(r"[\d.]+", w):
            continue
        low = w.lower()
        if low in ("trem", "trens"):
            # contexto viagem (estação, trilho, vagão...)? mantém. Senão é "treino".
            ctx = {sem_acento(x["word"].lower()) for x in palavras[max(0, idx_p - 4):idx_p + 5]}
            viagem = {"estacao", "estacoes", "trilho", "trilhos", "vagao", "vagoes",
                      "viagem", "viajar", "ferrovia", "ferroviario", "metro",
                      "passagem", "embarque", "tunel", "locomotiva", "plataforma"}
            if not (ctx & viagem):
                p["word"] = "treinos" if low == "trens" else "treino"
                continue
        if tem_hack and low in ("rack", "raca", "rek", "hec"):
            p["word"] = "hack"
            continue
        if tem_rack and low in ("hack", "hac", "heque"):
            p["word"] = "rack"
            continue
        if low in ERROS_COMUNS:
            p["word"] = ERROS_COMUNS[low]
            continue
        nrm = sem_acento(low)
        if extra_norm and nrm in extra_norm:
            if low != extra_norm[nrm]:
                p["word"] = extra_norm[nrm]
            continue
        if nrm in vocab_1:
            if low != vocab_1[nrm]:
                p["word"] = vocab_1[nrm]
            continue
        if len(nrm) >= 4:
            if extra_norm:
                best_e = difflib.get_close_matches(nrm, list(extra_norm.keys()), n=1, cutoff=0.80)
                if best_e and best_e[0] != nrm:
                    p["word"] = extra_norm[best_e[0]]
                    continue
            best = difflib.get_close_matches(nrm, list(vocab_1.keys()), n=1, cutoff=LIMIAR_FUZZY)
            if best and best[0] != nrm:
                p["word"] = vocab_1[best[0]]

    # passo 3: frases (janela 2-4)
    i = 0
    while i < len(palavras):
        achou = False
        for norm_frase, canon in frases:
            n_f = len(canon)
            janela = palavras[i:i + n_f + 1]  # +1 p/ tolerar "de" faltando/sobrando
            if len(janela) < 2:
                continue
            for tam in (n_f + 1, n_f, max(2, n_f - 1)):
                if i + tam > len(palavras):
                    continue
                cand = " ".join(sem_acento(x["word"].lower()) for x in palavras[i:i + tam])
                r = difflib.SequenceMatcher(None, cand, norm_frase).ratio()
                if r >= 0.88 or cand == norm_frase:
                    span = palavras[i:i + tam]
                    t0, t1 = span[0]["start"], span[-1]["end"]
                    dur = max(0.2, t1 - t0)
                    pesos = [max(1, len(cw)) for cw in canon]
                    tot = sum(pesos)
                    t = t0
                    novas = []
                    for k, cw in enumerate(canon):
                        fim = t1 if k == len(canon) - 1 else t + dur * pesos[k] / tot
                        novas.append({"word": cw, "start": round(t, 3), "end": round(fim, 3),
                                      "enfase": False})
                        t = fim
                    palavras[i:i + tam] = novas
                    i += len(novas)
                    achou = True
                    break
            if achou:
                break
        if not achou:
            i += 1
    return palavras


def normalizar_tokens(palavras: list[dict]) -> list[dict]:
    """
    Entrada: [{"word": "...", "start": f, "end": f}, ...] do whisper.
    Saída: mesma estrutura com texto limpo + números normalizados.
    """
    # 1. limpa pontuação de cada token, preserva tempos
    toks: list[dict] = []
    for p in palavras:
        raw = str(p.get("word", "")).strip()
        if not raw:
            continue
        # trata "por cento" / "%" separado: marca flag
        low = raw.lower().strip(",.:;!?")
        nucleo = re.sub(r"[^\w%]", "", raw, flags=re.UNICODE)
        gritada = len(nucleo) >= 3 and nucleo.replace("%", "").isupper()
        excl = raw.strip().endswith(("!", "?"))
        toks.append({"raw": raw, "low": low, "start": p["start"], "end": p["end"],
                     "gritada": gritada, "excl": excl})

    out: list[dict] = []
    i = 0
    while i < len(toks):
        low = toks[i]["low"]

        # --- % grudado ou separado: "5 %" / "5%" / "cinco por cento" ---
        # caso: número + "por" + "cento"
        if low == "por" and i + 1 < len(toks) and toks[i + 1]["low"] in ("cento", "porcento"):
            # anexa % ao token anterior
            if out:
                if not out[-1]["word"].endswith("%"):
                    out[-1]["word"] += "%"
                    out[-1]["end"] = toks[i + 1]["end"]
            i += 2
            continue
        if low in ("porcento",) and out:
            if not out[-1]["word"].endswith("%"):
                out[-1]["word"] += "%"
                out[-1]["end"] = toks[i]["end"]
            i += 1
            continue

        # --- dígito puro: "1", "100", "1.000", "5%" ---
        m = re.fullmatch(r"(\d{1,3}(?:[.\s]\d{3})*|\d+)([%!?]?)", toks[i]["raw"].strip())
        if m:
            num_txt, suf = m.groups()
            n = int(re.sub(r"\D", "", num_txt))
            start = toks[i]["start"]
            if suf == "%" or (i + 1 < len(toks) and toks[i + 1]["low"] in ("porcento", "%", "por")):
                # porcentagem: sempre dígito + %
                word = f"{n}%"
                end = toks[i]["end"]
                # consome "por cento" seguinte se houver
                if i + 1 < len(toks) and toks[i + 1]["low"] == "por":
                    if i + 2 < len(toks) and toks[i + 2]["low"] in ("cento", "porcento"):
                        end = toks[i + 2]["end"]
                        i += 3
                    else:
                        end = toks[i + 1]["end"]
                        i += 2
                elif i + 1 < len(toks) and toks[i + 1]["low"] in ("porcento", "%"):
                    end = toks[i + 1]["end"]
                    i += 2
                else:
                    i += 1
                out.append({"word": word, "start": start, "end": end})
                continue
            # --- dígito + magnitude por extenso: "6 mil" -> "6.000" (não "seis 1.000") ---
            if suf == "" and i + 1 < len(toks):
                prox = toks[i + 1]["low"]
                if prox in EXTENSO_BASE and EXTENSO_BASE[prox] >= 100:
                    seq = [str(n)] + [t["low"] for t in toks[i + 1:i + 6]]
                    # avalia: dígito inicial multiplica/soma com magnitudes seguintes
                    total = 0
                    base_n = n
                    k = 1
                    mult = None
                    resto = []
                    # primeiro tenta padrão "<n> mil/milhão/bilhão [e ...]"
                    if EXTENSO_BASE.get(seq[1], 0) == 1000 or EXTENSO_BASE.get(seq[1], 0) >= 1_000_000:
                        mult = EXTENSO_BASE[seq[1]]
                        total = (base_n if base_n != 0 else 1) * mult
                        k = 2
                        # consome resto aditivo: "6 mil e quinhentos" -> +500
                        while k < len(seq):
                            t = seq[k].lower().strip(",.:;!?%")
                            if t in IGNORAR_NUMERO:
                                k += 1
                                continue
                            if t in EXTENSO_BASE and EXTENSO_BASE[t] < 1000:
                                total += EXTENSO_BASE[t]
                                k += 1
                            else:
                                break
                    elif EXTENSO_BASE.get(seq[1], 0) >= 100:
                        # "6 cento(s)/duzentos..." — soma simples
                        total = base_n * EXTENSO_BASE[seq[1]] if base_n <= 9 and EXTENSO_BASE[seq[1]] >= 100 else None
                        k = 2 if total is not None else 1
                    if total:
                        end = toks[i + k - 1]["end"]
                        # porcentagem logo depois? "6 mil por cento" (raro, mas trata)
                        if i + k < len(toks) and toks[i + k]["low"] in ("porcento", "%"):
                            out.append({"word": f"{formatar_numero_br(total)}%", "start": start, "end": toks[i + k]["end"]})
                            i += k + 1
                            continue
                        if (i + k + 1 < len(toks) and toks[i + k]["low"] == "por"
                                and toks[i + k + 1]["low"] in ("cento", "porcento")):
                            out.append({"word": f"{formatar_numero_br(total)}%", "start": start, "end": toks[i + k + 1]["end"]})
                            i += k + 2
                            continue
                        out.append({"word": formatar_numero_br(total), "start": start, "end": end})
                        i += k
                        continue
            if 0 <= n <= 9:
                word = DIGITO_PARA_EXTENSO[str(n)]
                if n == 1 and i + 1 < len(toks):
                    # artigo concorda com o substantivo: "1 coisa" -> "uma coisa"
                    prox = toks[i + 1]["low"].strip("!?%")
                    if re.fullmatch(r"[a-zà-ú]+s?", prox) and (
                            prox.endswith(("a", "as")) or prox in ("coisa", "carga", "série", "serie", "repetição", "repeticao")):
                        word = "uma"
                out.append({"word": limpar_palavra(word), "start": toks[i]["start"], "end": toks[i]["end"]})
            else:
                out.append({"word": formatar_numero_br(n), "start": toks[i]["start"], "end": toks[i]["end"]})
            i += 1
            continue

        # --- % grudado em extenso: "cinco%" -> "5%" (porcentagem sempre dígito) ---
        if re.fullmatch(r"[a-zà-ú]+%", low):
            base = low.replace("%", "")
            if base in EXTENSO_BASE:
                out.append({"word": f"{EXTENSO_BASE[base]}%", "start": toks[i]["start"], "end": toks[i]["end"]})
            else:
                out.append({"word": limpar_palavra(low), "start": toks[i]["start"], "end": toks[i]["end"]})
            i += 1
            continue

        # --- extenso 0-9 + "por cento": "cinco por cento" -> "5%" ---
        if low in EXTENSO_BASE and EXTENSO_BASE[low] <= 9:
            if i + 1 < len(toks) and toks[i + 1]["low"] in ("porcento", "%"):
                out.append({"word": f"{EXTENSO_BASE[low]}%", "start": toks[i]["start"], "end": toks[i + 1]["end"]})
                i += 2
                continue
            if (i + 2 < len(toks) and toks[i + 1]["low"] == "por"
                    and toks[i + 2]["low"] in ("cento", "porcento")):
                out.append({"word": f"{EXTENSO_BASE[low]}%", "start": toks[i]["start"], "end": toks[i + 2]["end"]})
                i += 3
                continue

        # --- sequência por extenso >= 10: "cento e vinte", "dois mil" ---
        # "e"/"de" sozinhos não iniciam número (evita comer conjunção)
        if low not in IGNORAR_NUMERO:
            seq_lows = [t["low"] for t in toks[i:i + 6]]
            valor, consumidos = tentar_converter_sequencia_extenso(seq_lows)
            if valor is not None:
                # verifica se é porcentagem ("... por cento" logo depois)
                j = i + consumidos
                eh_pct = j < len(toks) and toks[j]["low"] in ("porcento", "%")
                k = j
                if j < len(toks) and toks[j]["low"] == "por" and j + 1 < len(toks) and toks[j + 1]["low"] in ("cento", "porcento"):
                    eh_pct = True
                    k = j + 2
                word = f"{formatar_numero_br(valor)}%" if eh_pct else formatar_numero_br(valor)
                end = toks[k - 1]["end"] if eh_pct and k > j else toks[i + consumidos - 1]["end"]
                out.append({"word": word, "start": toks[i]["start"], "end": end})
                i = k if eh_pct and k > j else i + consumidos
                continue

        # --- palavra normal: só limpa ---
        limpa = limpar_palavra(toks[i]["raw"])
        if limpa:
            # dígito 0-9 que sobrou como extenso mantém; se for dígito solto converte
            if limpa in DIGITO_PARA_EXTENSO:
                limpa = DIGITO_PARA_EXTENSO[limpa]
            out.append({"word": limpa, "start": toks[i]["start"], "end": toks[i]["end"]})
        i += 1

    # remove vazios, aplica correções fixas e depois a caixa
    out = [p for p in out if p["word"]]
    # junta milhar que o whisper separou ("15" + "534" -> "15.534")
    i = 0
    while i < len(out) - 1:
        a, b = out[i]["word"], out[i + 1]["word"]
        if (re.fullmatch(r"\d{1,3}(?:\.\d{3})*", a) and re.fullmatch(r"\d{3}", b)
                and out[i + 1]["start"] - out[i]["end"] < 0.5):
            out[i] = {"word": f"{a}.{b}", "start": out[i]["start"], "end": out[i + 1]["end"]}
            del out[i + 1]
        else:
            i += 1
    # correções multi-palavra ("fabio venturelli"): varre a sequência
    frases = {k: v for k, v in CORRECOES.items() if " " in k}
    if frases:
        lows = [p["word"].lower() for p in out]
        for frase, repl in frases.items():
            partes_f = frase.lower().split()
            n_f = len(partes_f)
            n = 0
            while n <= len(lows) - n_f:
                if lows[n:n + n_f] == partes_f:
                    repl_partes = repl.split()
                    for m, rp in enumerate(repl_partes):
                        out[n + m]["word"] = rp
                        lows[n + m] = rp.lower()
                    n += n_f
                else:
                    n += 1
    for p in out:
        base_low = p["word"].lower()
        if base_low in CORRECOES:
            p["word"] = CORRECOES[base_low]
        p["word"] = aplicar_caixa(p["word"], MODO_TEXTO_GLOBAL)
        p["word"] = mascarar_palavrao(p["word"])
    # marca ênfase (p/ isolar solo): gritada/CAPS, !/?, duração longa ou lista ISOLAR_PALAVRAS
    for p in out:
        dur = p["end"] - p["start"]
        base = p["word"].lower().rstrip("%").strip("!?")
        flag = next((t for t in toks if abs(t["start"] - p["start"]) < 0.015), {})
        p["enfase"] = bool(
            (ISOLAR_ENFASE_AUTO and (flag.get("gritada") or flag.get("excl")))
            or dur >= DURACAO_ENFASE
            or base in ISOLAR_PALAVRAS
        )
    return out


# será sobrescrito pelo argumento --modo-texto
MODO_TEXTO_GLOBAL = MODO_TEXTO


def agrupar(palavras: list[dict], por_cartela="auto") -> list[dict]:
    """Agrupa em cartelas respeitando pausa, ênfase (solo) e duração máxima.
    Ênfase nunca gruda na anterior: 'software' | 'cansado'.
    por_cartela="auto": corta pela fala — 1 palavra no grito/pausa longa,
    3-4 na fala corrida, sem parede de texto (máx ~30 chars). N fixo: força N."""
    auto = str(por_cartela).lower() == "auto"
    if not auto:
        por_cartela = int(por_cartela)
    grupos: list[dict] = []
    cur: list[dict] = []

    def fecha():
        if cur:
            grupos.append({"words": cur.copy(), "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur.clear()

    def chars(lst) -> int:
        return sum(len(x["word"]) for x in lst) + max(0, len(lst) - 1)

    def base_norm(s: str) -> str:
        return sem_acento(s.lower().strip("!?%.,;:"))

    lig_n = {sem_acento(x) for x in LIGANTES}
    cola_pares = set()
    for fr in COLA_FRASES:
        ps = [sem_acento(p) for p in fr.lower().split()]
        for a, b in zip(ps, ps[1:]):
            cola_pares.add((a, b))
    adiar = False  # corte adiado p/ não partir cola ("...de são | paulo")

    def fecha():
        nonlocal adiar
        if cur:
            grupos.append({"words": cur.copy(), "start": cur[0]["start"], "end": cur[-1]["end"]})
            cur.clear()
        adiar = False

    for w in palavras:
        if cur:
            gap = w["start"] - cur[-1]["end"]
            dur = w["end"] - cur[0]["start"]
            ult = base_norm(cur[-1]["word"])
            colado = ult in lig_n or (ult, base_norm(w["word"])) in cola_pares
            # 1. pausa forte sempre quebra (inclui pausa de ênfase)
            if gap > MAX_GAP or gap > PAUSA_ENFASE and (w.get("enfase") or cur[-1].get("enfase")):
                fecha()
            # 2. palavra de ênfase nunca entra grudada: fecha a anterior primeiro
            elif w.get("enfase") and cur:
                fecha()
            # 3. anterior era ênfase solo: fecha antes de continuar
            elif cur and len(cur) == 1 and cur[0].get("enfase"):
                fecha()
            # 4. limites: N fixo ou, no auto, fala (tamanho/duração/respiro).
            #    Com cola, segue junto até desgrudar (teto duro estoura mesmo assim).
            elif auto:
                if dur > MAX_DURACAO * 1.25 or len(cur) >= AUTO_MAX_PALAVRAS + 2:
                    fecha()  # teto duro: nem cola segura
                elif (dur > MAX_DURACAO or len(cur) >= AUTO_MAX_PALAVRAS
                        or (chars(cur) >= AUTO_MIN_CHARS
                            and chars(cur) + 1 + len(w["word"]) > AUTO_MAX_CHARS)
                        or ((cur[-1]["end"] - cur[0]["start"]) >= AUTO_MIN_DUR
                            and gap > AUTO_PAUSA_CORTE)):
                    if colado:
                        adiar = True
                    else:
                        fecha()
            elif len(cur) >= por_cartela or dur > MAX_DURACAO:
                if colado and dur <= MAX_DURACAO * 1.25:
                    adiar = True
                else:
                    fecha()
        cur.append(w)
        # 5. ênfase fecha sozinha na hora
        if w.get("enfase"):
            fecha()
    fecha()

    # junta órfão: cartela de 1 palavra comum gruda na vizinha (atrás primeiro)
    # se couber em tamanho e duração ("moro no estado de são | paulo" não parte;
    # "paulo foi | caótico" vira "paulo foi caótico" se couber)
    def pode_juntar(a, b) -> bool:
        return (chars(a["words"]) + 1 + chars(b["words"]) <= max(AUTO_MAX_CHARS, 34)
                and b["end"] - a["start"] <= MAX_DURACAO)

    def eh_orfao(g) -> bool:
        return len(g["words"]) == 1 and not g["words"][0].get("enfase")

    def eh_solo(g) -> bool:
        return len(g["words"]) == 1 and bool(g["words"][0].get("enfase"))

    i = 0
    while i < len(grupos):
        g = grupos[i]
        if eh_orfao(g) and len(grupos) > 1:
            uniu = False
            if i > 0 and not eh_solo(grupos[i - 1]) and pode_juntar(grupos[i - 1], g):
                grupos[i - 1] = {"words": grupos[i - 1]["words"] + g["words"],
                                 "start": grupos[i - 1]["start"], "end": g["end"]}
                del grupos[i]
                uniu = True
                i = max(0, i - 1)
            elif i < len(grupos) - 1 and not eh_solo(grupos[i + 1]) and pode_juntar(g, grupos[i + 1]):
                grupos[i] = {"words": g["words"] + grupos[i + 1]["words"],
                             "start": g["start"], "end": grupos[i + 1]["end"]}
                del grupos[i + 1]
                uniu = True
            if uniu:
                continue
        i += 1

    # desacelera: garante duração mínima e segura até a próxima (sem piscada)
    for idx, g in enumerate(grupos):
        solo = len(g["words"]) == 1 and g["words"][0].get("enfase")
        minima = MIN_DURACAO_SOLO if solo else MIN_DURACAO_CARTELA
        dur = g["end"] - g["start"]
        if dur < minima:
            g["end"] = g["start"] + minima
        if ESTENDER_ATE_PROXIMA and idx + 1 < len(grupos):
            prox_start = grupos[idx + 1]["start"]
            g["end"] = min(prox_start, g["end"] + HOLDE_MAX_EXTRA)
            if g["end"] < grupos[idx + 1]["start"] - 0.05:
                pass  # mantém micro-respiro
            else:
                g["end"] = grupos[idx + 1]["start"]
    return grupos


def salvar_json(grupos: list[dict], path: str) -> None:
    import json
    data = {"grupos": [
        {"start": round(g["start"], 3), "end": round(g["end"], 3),
         "text": " ".join(x["word"] for x in g["words"]),
         "words": [{"word": x["word"], "start": round(x["start"], 3),
                     "end": round(x["end"], 3)} for x in g["words"]]}
        for g in grupos]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def carregar_json(path: str) -> list[dict]:
    import json
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    grupos = []
    for g in data.get("grupos", []):
        ws = [{"word": x["word"], "start": float(x["start"]), "end": float(x["end"])}
              for x in g["words"]]
        grupos.append({"words": ws, "start": float(g["start"]), "end": float(g["end"])})
    return grupos


def salvar_srt(grupos: list[dict], path: str) -> None:
    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    with open(path, "w", encoding="utf-8") as f:
        for n, g in enumerate(grupos, 1):
            txt = " ".join(x["word"] for x in g["words"])
            f.write(f"{n}\n{ts(g['start'])} --> {ts(g['end'])}\n{txt}\n\n")


def parse_srt(path: str) -> list[dict]:
    """Lê srt editado: retorna [{'start': s, 'end': s, 'text': '...'}]."""
    import re
    with open(path, encoding="utf-8") as f:
        conteudo = f.read().strip().replace("\r", "")
    blocos = re.split(r"\n\s*\n", conteudo)
    out = []
    for b in blocos:
        linhas = [l.strip() for l in b.strip().splitlines() if l.strip()]
        if not linhas:
            continue
        # pula número sequencial se houver
        if re.fullmatch(r"\d+", linhas[0]):
            linhas = linhas[1:]
        if len(linhas) < 2:
            continue
        m = re.match(r"(.+?)\s*-->\s*(.+)", linhas[0])
        if not m:
            continue
        def ps(t: str) -> float:
            t = t.strip().replace(",", ".")
            h, mi, resto = t.split(":")
            return int(h) * 3600 + int(mi) * 60 + float(resto)
        texto = " ".join(linhas[1:]).strip()
        if texto:
            out.append({"start": ps(m.group(1)), "end": ps(m.group(2)), "text": texto})
    return out


def carregar_roteiro(path: str) -> tuple[str, set[str], str]:
    """Lê roteiro txt: retorna (prompt p/ whisper, vocab_extra p/ revisão, texto limpo).

    Remove marcações [IMG1]/[VÍDEO...], corta LEGENDA/hashtags do fim
    (não são falados) e limita o prompt (~1200 chars, limite do whisper).
    Mesmo com improviso pontual, o prompt guia nomes, aparelhos e números.
    """
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    # corta bloco de legenda/descrição (não falado)
    txt = re.split(r"\n\s*LEGENDA\s*\n", txt, maxsplit=1, flags=re.IGNORECASE)[0]
    txt = re.sub(r"\[.*?\]", " ", txt)  # [IMG1 — ...], [VÍDEO ...]
    txt = re.sub(r"#\w+", " ", txt)     # hashtags
    txt = re.sub(r"\s+", " ", txt).strip()
    prompt = txt
    if len(prompt) > 1200:
        corte = prompt[:1200].rsplit(" ", 1)[0]
        prompt = corte
    vocab = {w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ%]+", txt) if len(w) >= 5}
    return prompt, vocab, txt


def checagem_roteiro(palavras: list[dict], roteiro_txt: str) -> list[dict]:
    """DE/PARA com o roteiro: corrige palavra que não faz sentido perto do roteiro.

    Ex: whisper entendeu "gol a empresa" e o roteiro diz "golpe a empresa".
    Alinha as duas sequências e, em trecho parecido: troca truncamento
    ("gol"->"golpe"), 1 letra trocada ("coisa"->"coisas",
    "revisamento"->"revezamento") e insere 1 palavra comida ("250 em 250
    [gramas]", marcada com (+)). Improviso grande é ignorado, número/%/
    palavrão intocados, e coloquial ("pra", "tá") nunca vira roteiro.
    Mostra o DE/PARA no terminal. Roda em minúsculo (a caixa vem depois).
    """
    import difflib
    rot = [w.lower() for w in re.findall(r"[A-Za-zÀ-ÿ0-9%]+", roteiro_txt)]
    if not rot or not palavras:
        return palavras
    rot_n = [sem_acento(w) for w in rot]
    tra_n = [sem_acento(str(p["word"]).lower().rstrip("!?%")) for p in palavras]
    rot_n = [sem_acento(w) for w in rot]
    tra_n = [sem_acento(str(p["word"]).lower().rstrip("!?%")) for p in palavras]

    def lev(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i] + [0] * len(b)
            for j, cb in enumerate(b, 1):
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            prev = cur
        return prev[-1]

    def casa(t: str, r: str):
        """Retorna ratio se o par vale troca, senão None. Genérico p/ qq palavra."""
        if not t or not r or t in COLOQUIAL or r in COLOQUIAL:
            return None
        comp = max(len(t), len(r))
        ratio = difflib.SequenceMatcher(None, t, r).ratio()
        if r.startswith(t) or t.startswith(r):
            # truncamento ("gol"->"golpe", "supi"->"supino", "desse"->"esse")
            if comp >= 4 and ratio >= 0.72:
                return ratio
        elif t in r or r in t:
            # substring no meio: só palavra longa, senão troca fala real à toa
            if comp >= 6 and ratio >= 0.85:
                return ratio
        # 1 letra trocada ("coisa"->"coisas", "revisamento"->"revezamento",
        # "anilias"->"anilhas"): erro clássico de ouvido do whisper
        if comp >= 5 and ratio >= 0.78 and lev(t, r) <= comp // 4:
            return ratio
        return None

    trocas: list[str] = []
    insercoes: list[tuple[int, dict]] = []
    sm = difflib.SequenceMatcher(None, tra_n, rot_n, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        # palavra comida pelo whisper ("250 em 250 [gramas]"): insere 1 palavra
        # do roteiro com tempo interpolado, marcada com (+) p/ conferir no srt
        if tag == "insert" and (j2 - j1) == 1 and (i2 - i1) == 0:
            w = rot[j1].lower()
            if len(w) >= 4 and not re.fullmatch(r"[\d.,]+", w):
                prev = palavras[i1 - 1] if i1 > 0 else None
                nxt = palavras[i1] if i1 < len(palavras) else None
                ini = prev["end"] if prev else (nxt["start"] - 0.3 if nxt else 0.0)
                fim = nxt["start"] if nxt else ini + 0.3
                if fim <= ini:
                    fim = ini + 0.25
                fim = min(fim, ini + 0.6)
                insercoes.append((i1, {"word": w, "start": round(ini, 3),
                                      "end": round(fim, 3), "enfase": False}))
                trocas.append(f"(+{w})")
            continue
        # improviso grande (bloco >6) = fala real diferente: ignora tudo
        if tag != "replace" or (i2 - i1) > 6 or (j2 - j1) > 6:
            continue
        usados = set()
        for k in range(i1, i2):
            t = tra_n[k]
            orig = str(palavras[k]["word"])
            if not t or "*" in orig or "%" in orig or re.fullmatch(r"[\d.]+", t):
                continue
            # melhor par dentro do bloco (cada palavra do roteiro usa 1x)
            melhor, melhor_r = -1.0, None
            for m in range(j1, j2):
                if m in usados:
                    continue
                r = rot_n[m]
                if not r:
                    continue
                ratio = casa(t, r)
                if ratio is not None and ratio > melhor:
                    melhor, melhor_r = ratio, m
            if melhor_r is not None:
                novo = rot[melhor_r].lower()
                if novo != orig.lower():
                    trocas.append(f"{orig.lower()} -> {novo}")
                    palavras[k]["word"] = novo
                usados.add(melhor_r)
    for pos, novo_w in sorted(insercoes, reverse=True):
        palavras.insert(pos, novo_w)
    if trocas:
        print(f"  DE/PARA roteiro ({len(trocas)}): " + " | ".join(trocas[:20]))
        if len(trocas) > 20:
            print(f"  ... +{len(trocas) - 20} (ver srt)")
    else:
        print("  DE/PARA roteiro: nada a corrigir")
    return palavras


def grupos_de_srt(cartelas: list[dict]) -> list[dict]:
    """Converte cartelas do srt revisado em grupos com tempos palavra-por-palavra.

    Distribui o tempo da cartela entre as palavras proporcional ao tamanho
    (cartela tem 1-3 palavras, então o erro é imperceptível e a varredura
    LIFE IN MOTION continua sincronizada no geral).
    O texto do srt é final: respeita o que você escreveu (só aplica caixa).
    """
    grupos = []
    for c in cartelas:
        palavras_txt = [p for p in c["text"].split() if p]
        if not palavras_txt:
            continue
        dur = max(0.3, c["end"] - c["start"])
        pesos = [max(1, len(p.strip("!?%.,;:"))) for p in palavras_txt]
        total = sum(pesos)
        t = c["start"]
        ws = []
        for k, ptxt in enumerate(palavras_txt):
            pdur = dur * pesos[k] / total
            # última palavra fecha exato no fim da cartela
            wend = c["end"] if k == len(palavras_txt) - 1 else t + pdur
            ws.append({"word": mascarar_palavrao(aplicar_caixa(ptxt, MODO_TEXTO_GLOBAL)),
                       "start": round(t, 3), "end": round(wend, 3)})
            t = wend
        grupos.append({"words": ws, "start": c["start"], "end": c["end"]})
    return grupos


def fmt_ass(t: float) -> str:
    t = max(0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    cs = int(round((t - int(t)) * 100))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def escapar_ass(s: str) -> str:
    return s.replace("{", "(").replace("}", ")")


def hex_para_ass(cor_hex: str, alpha: str = "00") -> str:
    """'#FFD900' -> '&H0000D9FF' (formato ASS: &HAABBGGRR)."""
    h = cor_hex.strip().lstrip("#")
    if len(h) == 3:  # ex: #FFF
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        raise ValueError(f"Cor inválida: {cor_hex}. Use formato #RRGGBB.")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha}{b}{g}{r}".upper()


def gerar_ass(grupos: list[dict], path: str, largura: int, altura: int,
              cor_texto: str = COR_TEXTO, cor_animacao: str = COR_ANIMACAO) -> None:
    # ajusta fonte e margem conforme resolução
    escala = min(largura / 1080, altura / 1920) if largura and altura else 1.0
    escala = max(0.6, min(escala, 1.2))
    fontsize = int(TAMANHO_FONTE * escala)
    margin_v = int(ALTURA_LEGENDA * escala)

    primary = hex_para_ass(cor_texto)
    secondary = hex_para_ass(cor_animacao)  # cor que varre a palavra (LIFE IN MOTION)
    outline = hex_para_ass(COR_CONTORNO)

    header = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {largura}
PlayResY: {altura}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTok,{FONTE},{fontsize},{primary},{secondary},{outline},&H80000000,-1,0,0,0,100,100,0.5,0,1,{ESPESSURA_CONTORNO},{SOMBRA},{ALINHAMENTO},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    linhas = [header]
    for g in grupos:
        # LIFE IN MOTION: varredura karaoke palavra por palavra, com pausa real entre elas.
        # O karaoke consome tempo de forma contínua desde o início do Dialogue,
        # por isso o silêncio entre palavras vira um kf sobre o espaço —
        # assim a cor só começa a varrer exatamente quando a palavra é falada.
        # SWEEP_FATOR: cada palavra varre mais devagar, roubando tempo da pausa
        # seguinte (o total da linha é preservado; última palavra usa o hold).
        partes = [f"{{\\fad({FADE_IN_MS},{FADE_OUT_MS})}}"]
        segs: list[tuple[str, int, str]] = []  # (tipo, kf, texto)
        prev_end = g["start"]
        pendente = 0.0
        for idx, w in enumerate(g["words"]):
            gap_ms = max(0, int(round((w["start"] - prev_end) * 1000 / 10)))
            dur_ms = max(80, int((w["end"] - w["start"]) * 1000))
            kf_w = dur_ms / 10 * SWEEP_FATOR
            extra = kf_w - dur_ms / 10
            if idx > 0:
                usa = min(gap_ms, int(round(pendente)))
                segs.append(("gap", gap_ms - usa, " "))
                pendente -= usa
            segs.append(("word", int(round(kf_w)), escapar_ass(w["word"])))
            pendente += extra
            prev_end = w["end"]
        dlg_ms = max(1, int(round((g["end"] - g["start"]) * 1000 / 10)))
        total = sum(k for _, k, _ in segs)
        if total > dlg_ms:  # cartela lotada: encolhe proporcional (nunca corta a cor)
            f = dlg_ms / total
            segs = [(t, max(1, int(round(k * f))), x) for t, k, x in segs]
        for tipo, kf, txt in segs:
            if tipo == "gap" and kf <= 0:
                partes.append(" ")
            else:
                partes.append(f"{{\\kf{kf}}}{txt}")
        texto = "".join(partes)
        # fim EXATO (sem +0.05): overlap faz o libass empilhar uma cartela acima e outra
        # abaixo, alternando. Com fim exato tudo fica na mesma linha.
        linhas.append(f"Dialogue: 0,{fmt_ass(g['start'])},{fmt_ass(g['end'])},TikTok,,0,0,0,,{texto}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas) + "\n")


def rodar(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("CMD falhou:", " ".join(cmd), file=sys.stderr)
        print(r.stderr[-3000:], file=sys.stderr)
        raise SystemExit(1)


def probe_resolucao(video: str) -> tuple[int, int]:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
            capture_output=True, text=True)
        w, h = r.stdout.strip().split(",")
        return int(w), int(h)
    except Exception:
        return 1080, 1920


def carregar_wav_mono16k(path: str):
    """Lê wav PCM 16-bit mono 16k (gerado pelo ffmpeg) p/ numpy float32. Evita bug do PyAV."""
    import wave
    import numpy as np
    with wave.open(path, "rb") as wf:
        n = wf.getnframes()
        raw = wf.readframes(n)
        sampwidth = wf.getsampwidth()
        nchan = wf.getnchannels()
        fr = wf.getframerate()
    if sampwidth == 2:
        audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        audio = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"sampwidth não suportado: {sampwidth}")
    if nchan > 1:
        audio = audio.reshape(-1, nchan).mean(axis=1)
    if fr != 16000:
        # reamostra simples por interpolação linear
        import math
        dur = len(audio) / fr
        novo_len = int(dur * 16000)
        xp = np.linspace(0, 1, len(audio))
        xnew = np.linspace(0, 1, novo_len)
        audio = np.interp(xnew, xp, audio).astype(np.float32)
    return audio


def transcrever(audio: str, modelo: str, idioma: str | None, prompt: str | None = None):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("Falta faster-whisper. Instale: pip install faster-whisper", file=sys.stderr)
        raise SystemExit(1)
    print(f"[1/4] transcrevendo com faster-whisper ({modelo})...")
    model = WhisperModel(modelo, device="cpu", compute_type="int8")
    # passa numpy em vez do caminho: contorna TypeError metadata_errors do av.open
    onda = carregar_wav_mono16k(audio)
    kwargs = dict(language=idioma, word_timestamps=True, vad_filter=True)
    if prompt:
        kwargs["initial_prompt"] = prompt
        print(f"  roteiro como guia ({len(prompt)} chars)")
    segments, info = model.transcribe(onda, **kwargs)
    try:
        from tqdm import tqdm
        barra = tqdm(total=round(float(info.duration or 0), 1), unit="s",
                     desc="transcrevendo", bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s")
    except ImportError:
        barra = None
    palavras = []
    for seg in segments:
        if barra is not None:
            barra.n = round(float(seg.end), 1)
            barra.refresh()
        if not seg.words:
            continue
        for w in seg.words:
            palavras.append({"word": w.word.strip(), "start": float(w.start), "end": float(w.end)})
    if barra is not None:
        barra.n = barra.total
        barra.close()
    return palavras


def duracao_video(path: str) -> float:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", path], capture_output=True, text=True)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def queimar_video(entrada: str, ass_path: str, saida: str) -> None:
    """Queima legenda com ffmpeg mostrando barra de progresso (lê -progress)."""
    try:
        from tqdm import tqdm
        tem_tqdm = True
    except ImportError:
        tem_tqdm = False
    total = duracao_video(entrada)
    ass_esc = ass_path.replace(":", "\\:").replace("'", "'\\''")
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", entrada,
           "-map", "0:v", "-map", "0:a?",
           "-sn",  # nunca embute legenda soft (evita legenda dupla no player)
           "-vf", f"ass='{ass_esc}'",
           "-c:a", "aac", "-b:a", "192k",
           "-c:v", "libx264", "-preset", "medium", "-crf", "18",
           "-movflags", "+faststart",
           "-shortest",
           "-progress", "pipe:1",
           saida]
    barra = tqdm(total=round(total, 1), unit="s", desc="queimando legenda",
                 bar_format="{desc}: {percentage:3.0f}%|{bar}| {n:.0f}/{total:.0f}s") if tem_tqdm and total > 0 else None
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        for linha in proc.stdout:
            if linha.startswith("out_time_ms="):
                try:
                    s = int(linha.split("=")[1].strip()) / 1_000_000
                except ValueError:
                    continue
                if barra is not None:
                    barra.n = min(round(s, 1), barra.total)
                    barra.refresh()
            elif linha.startswith("progress=end"):
                break
    finally:
        if barra is not None:
            barra.n = barra.total
            barra.close()
    _, err = proc.communicate()
    if proc.returncode != 0:
        print("CMD falhou:", " ".join(cmd), file=sys.stderr)
        print(err[-3000:], file=sys.stderr)
        raise SystemExit(1)


def main() -> None:
    global MODO_TEXTO_GLOBAL, ALTURA_LEGENDA
    ap = argparse.ArgumentParser(description="Legenda vídeo no padrão TikTok.")
    ap.add_argument("entrada", help="vídeo de entrada (mp4/mov/mkv...)")
    ap.add_argument("-o", "--saida", default=None, help="vídeo de saída (padrão: MESMA pasta do original, nome_legendado.mp4)")
    ap.add_argument("--modelo", default=MODELO_WHISPER, help="modelo whisper (padrão: large-v3-turbo, o melhor; use small p/ rascunho rápido)")
    ap.add_argument("--palavras", default=PALAVRAS_POR_LEGENDA, help="palavras por cartela: auto (pela fala, padrão), 2, 3 ou 4")
    ap.add_argument("--modo-texto", choices=["baixa", "alta", "original"], default=MODO_TEXTO,
                    help="100%% caixa baixa ou alta")
    ap.add_argument("--margem-v", type=int, default=ALTURA_LEGENDA,
                    help="altura da legenda a partir do rodapé (maior = mais alta, não cobre descrição)")
    ap.add_argument("--cor", default=COR_ANIMACAO,
                    help="cor da animação LIFE IN MOTION em hex, ex: '#FFD900' (padrão: %(default)s)")
    ap.add_argument("--cor-texto", default=COR_TEXTO,
                    help="cor base do texto em hex, ex: '#FFFFFF' (padrão: %(default)s)")
    ap.add_argument("--srt", action="store_true", help="também salva .srt ao lado da saída")
    ap.add_argument("--somente-transcrever", action="store_true",
                    help="etapa 1: só transcreve e salva .json + .srt p/ revisão, sem queimar vídeo")
    ap.add_argument("--json-out", default=None, help="caminho do .json de revisão (padrão: saida.json)")
    ap.add_argument("--de-json", default=None,
                    help="etapa 2 avançada: queima a partir do .json REVISADO (tempos exatos palavra-por-palavra)")
    ap.add_argument("--de-srt", default=None,
                    help="etapa 2 simples: queima a partir do .srt REVISADO (texto/tempos que você editou)")
    ap.add_argument("--roteiro", default=None,
                    help="txt do roteiro: guia a transcrição (nomes, aparelhos, números) mesmo com improviso pontual")
    ap.add_argument("--base-dir", default=None,
                    help="pasta base do EP (onde está o vídeo). Tudo que o script gera (srt/json de revisão, vídeo legendado) cai lá. Padrão: pasta do vídeo")
    args = ap.parse_args()

    MODO_TEXTO_GLOBAL = args.modo_texto
    ALTURA_LEGENDA = args.margem_v

    entrada = args.entrada
    if not os.path.isfile(entrada):
        print(f"Arquivo não encontrado: {entrada}", file=sys.stderr)
        raise SystemExit(1)
    base = os.path.abspath(os.path.expanduser(args.base_dir)) if args.base_dir else os.path.dirname(os.path.abspath(entrada))
    os.makedirs(base, exist_ok=True)
    nome = os.path.splitext(os.path.basename(entrada))[0]
    pasta_video = os.path.dirname(os.path.abspath(entrada))
    # legendado cai na MESMA pasta do vídeo original (sempre):
    # -o relativo resolve lá dentro; -o absoluto respeitado.
    if args.saida and os.path.isabs(args.saida):
        saida = args.saida
    elif args.saida:
        saida = os.path.join(pasta_video, args.saida)
    else:
        saida = os.path.join(pasta_video, nome + "_legendado.mp4")
    # revisão com sufixo próprio: nunca tem o mesmo nome do vídeo final,
    # então o player NÃO carrega junto (era isso que duplicava a legenda).
    json_path = args.json_out or os.path.join(base, nome + "_revisao.json")

    # ---------- ETAPA 2: queimar a partir do revisado (json ou srt) ----------
    if args.de_srt:
        print(f"[revisão] carregando srt revisado {args.de_srt}...")
        cartelas = parse_srt(args.de_srt)
        if not cartelas:
            print("SRT vazio ou inválido.", file=sys.stderr)
            raise SystemExit(1)
        grupos = grupos_de_srt(cartelas)
        print(f"  {len(grupos)} cartelas revisadas (texto do srt respeitado)")
    elif args.de_json:
        print(f"[revisão] carregando {args.de_json}...")
        grupos = carregar_json(args.de_json)
        # re-aplica caixa caso tenha trocado o modo
        for g in grupos:
            for x in g["words"]:
                x["word"] = aplicar_caixa(x["word"], MODO_TEXTO_GLOBAL)
        print(f"  {len(grupos)} cartelas revisadas")
    else:
        tmp = tempfile.mkdtemp(prefix="legenda_")
        audio = os.path.join(tmp, "audio.wav")
        ass_path = os.path.join(tmp, "legenda.ass")

        print("[0/4] extraindo áudio...")
        rodar(["ffmpeg", "-y", "-i", entrada, "-vn", "-ac", "1", "-ar", "16000", audio])

        prompt, vocab_extra, roteiro_txt = (carregar_roteiro(args.roteiro) if args.roteiro else (None, None, None))
        palavras_raw = transcrever(audio, args.modelo, IDIOMA if IDIOMA else None, prompt)
        if not palavras_raw:
            print("Nada transcrito.", file=sys.stderr)
            raise SystemExit(1)

        print("[2/4] limpando texto, normalizando números e revisando termos de academia...")
        palavras = normalizar_tokens(palavras_raw)
        palavras = revisao_verbal(palavras, vocab_extra)
        if roteiro_txt:
            print("[2b/4] DE/PARA com o roteiro...")
            palavras = checagem_roteiro(palavras, roteiro_txt)
        # re-aplica caixa (revisão trabalha em minúsculo) + máscara
        for p in palavras:
            p["word"] = mascarar_palavrao(aplicar_caixa(p["word"], MODO_TEXTO_GLOBAL))
        grupos = agrupar(palavras, args.palavras)
        print(f"  {len(palavras)} palavras -> {len(grupos)} cartelas | modo={args.modo_texto} | corte={args.palavras}")

        salvar_json(grupos, json_path)
        print(f"[revisão] json salvo em: {json_path} (edite os cortes aqui)")

        if args.somente_transcrever:
            srt_preview = os.path.splitext(json_path)[0] + ".srt"
            salvar_srt(grupos, srt_preview)
            print(f"[revisão] srt salvo em: {srt_preview}")
            print("Revise o .srt (texto, cortes e tempos) e rode:")
            print(f'  python {os.path.basename(__file__)} "{entrada}" -o "{saida}" --de-srt "{srt_preview}" --cor "{args.cor}"')
            print("O .srt de revisão tem nome diferente do vídeo final de propósito:")
            print("assim o player não exibe ele por cima da legenda queimada (legenda dupla).")
            return

    print("[3/4] gerando legenda estilo TikTok...")
    w, h = probe_resolucao(entrada)
    if args.de_json or args.de_srt:
        # gera ass num temp novo
        tmp = tempfile.mkdtemp(prefix="legenda_")
        ass_path = os.path.join(tmp, "legenda.ass")
    gerar_ass(grupos, ass_path, w, h, cor_texto=args.cor_texto, cor_animacao=args.cor)

    if args.srt:
        # sufixo .legenda. p/ não colidir com o nome do vídeo (player auto-carrega
        # .srt de mesmo nome e duplica a legenda na tela).
        srt_path = os.path.splitext(saida)[0] + ".legenda.srt"
        salvar_srt(grupos, srt_path)
        print("SRT salvo em:", srt_path)

    print("[4/4] queimando legenda no vídeo (ffmpeg + libass)...")
    queimar_video(entrada, ass_path, saida)
    print("OK ->", saida)
    # a legenda de baixo/grande que você viu era o .srt lado a lado com o .mp4:
    # o player carrega sozinho. Apague/mova ele p/ ver só a queimada (a de cima).
    lado = os.path.splitext(saida)[0] + ".srt"
    if os.path.isfile(lado):
        print(f"AVISO: existe {lado} com o mesmo nome do vídeo — o player mostra ele POR CIMA")
        print("da legenda queimada (duas legendas). Apague ou mova esse .srt p/ ver só a de cima.")
    print(f"Dica TikTok: se cobrir a descrição, aumente --margem-v (atual {ALTURA_LEGENDA}). Se ficar alta demais, diminua.")


if __name__ == "__main__":
    main()
