"""
Agente de IA para Oráculos de Lemúria e ebooks.

Responde perguntas sobre tarot, radiestesia e ebooks via WhatsApp.
Usa Claude (Anthropic) se ANTHROPIC_API_KEY estiver configurada,
ou OpenAI se OPENAI_API_KEY, ou fallback local se nenhuma das duas.

Variáveis de ambiente:
  ANTHROPIC_API_KEY=<chave>          → usa Claude (recomendado)
  OPENAI_API_KEY=<chave>             → usa OpenAI como fallback
  ORACULOS_LINK_SESSAO=<url>         → link de pagamento para sessões
  ORACULOS_LINK_EBOOK=<url>          → link de pagamento para ebooks
  ORACULOS_PRECO_SESSAO=<valor>      → ex: "220"
  ORACULOS_PRECO_EBOOK=<valor>       → ex: "47"
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime

from parvati_system.models import ConversaBot, db

SYSTEM_PROMPT = """Você é a assistente espiritual do projeto *Oráculos de Lemúria*, criado por Naiara Massera.

O projeto oferece:
- Sessões de Tarot Terapêutico (individuais, online ou presencial)
- Radiestesia com pêndulo (leitura energética, limpeza, alinhamento)
- Ebooks sobre autoconhecimento, espiritualidade e práticas Lemurianas

Seu papel:
- Acolher a pessoa com empatia e presença
- Explicar como funciona cada modalidade com clareza
- Tirar dúvidas sobre tarot, radiestesia e temas espirituais
- Convidar a pessoa a agendar uma sessão ou adquirir um ebook quando perceber abertura
- NUNCA fazer previsões definitivas sobre saúde, dinheiro ou relacionamentos como se fossem certezas
- NUNCA prometer resultados garantidos
- Responder sempre em português do Brasil, de forma calorosa e acolhedora

Quando a pessoa demonstrar interesse em sessão ou ebook, informe o valor e envie o link de agendamento/compra.
Mantenha as respostas curtas (máximo 4 parágrafos) para o formato WhatsApp."""


def _precos_e_links() -> dict:
    return {
        "preco_sessao": os.environ.get("ORACULOS_PRECO_SESSAO", "220"),
        "preco_ebook": os.environ.get("ORACULOS_PRECO_EBOOK", "47"),
        "link_sessao": os.environ.get("ORACULOS_LINK_SESSAO", ""),
        "link_ebook": os.environ.get("ORACULOS_LINK_EBOOK", ""),
    }


def _montar_historico(conversa: ConversaBot) -> list[dict]:
    dados = conversa.dados or {}
    return dados.get("historico", [])


def _salvar_historico(conversa: ConversaBot, role: str, content: str) -> None:
    dados = conversa.dados or {}
    historico = dados.get("historico", [])
    historico.append({"role": role, "content": content})
    if len(historico) > 20:
        historico = historico[-20:]
    dados["historico"] = historico
    conversa.dados = dados


def _chamar_anthropic(historico: list[dict]) -> str:
    api_key = os.environ["ANTHROPIC_API_KEY"]
    payload = {
        "model": os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        "max_tokens": 400,
        "system": SYSTEM_PROMPT,
        "messages": historico,
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["content"][0]["text"].strip()


def _chamar_openai(historico: list[dict]) -> str:
    api_key = os.environ["OPENAI_API_KEY"]
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}] + historico,
        "max_tokens": 400,
        "temperature": 0.7,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _fallback(texto: str) -> str:
    t = texto.lower()
    info = _precos_e_Links()
    if any(p in t for p in ("tarot", "carta", "tiragem")):
        return (
            "O Tarot Terapêutico é uma ferramenta de autoconhecimento que nos ajuda a olhar para "
            "questões da vida com mais clareza e consciência. 🌙\n\n"
            "Cada sessão é um espaço acolhedor de reflexão — não de adivinhação.\n\n"
            f"Sessões a partir de R$ {info['preco_sessao']}. "
            + (f"Para agendar: {info['link_sessao']}" if info['link_sessao'] else "Me chame para verificar disponibilidade!")
        )
    if any(p in t for p in ("radiestesia", "pendulo", "pêndulo", "energia")):
        return (
            "A Radiestesia trabalha com a percepção energética através do pêndulo. "
            "É uma prática ancestral usada para leitura de campos energéticos, "
            "limpeza e alinhamento. ✨\n\n"
            f"Sessões a partir de R$ {info['preco_sessao']}. "
            + (f"Para agendar: {info['link_sessao']}" if info['link_sessao'] else "Me chame para verificar disponibilidade!")
        )
    if any(p in t for p in ("ebook", "livro", "material", "comprar")):
        return (
            "Temos ebooks sobre autoconhecimento, espiritualidade e práticas Lemurianas "
            "para você aprofundar sua jornada no seu próprio ritmo. 📖\n\n"
            f"Valor: R$ {info['preco_ebook']}. "
            + (f"Acesse: {info['link_ebook']}" if info['link_ebook'] else "Me chame para mais informações!")
        )
    return (
        "Olá! Sou a assistente dos *Oráculos de Lemúria* 🌸\n\n"
        "Trabalhamos com Tarot Terapêutico, Radiestesia e Ebooks espirituais.\n\n"
        "Posso te contar mais sobre alguma dessas modalidades?"
    )


def _precos_e_Links() -> dict:
    return _precos_e_links()


def processar_mensagem(telefone: str, texto: str, nome: str = "") -> str:
    """
    Processa mensagem recebida no canal dos Oráculos de Lemúria.
    Deve ser chamado dentro do app context do Flask.
    """
    import re
    tel = re.sub(r"\D", "", str(telefone or ""))

    conversa = ConversaBot.query.filter_by(telefone=tel, canal="oraculos").first()
    if not conversa:
        conversa = ConversaBot(
            telefone=tel,
            canal="oraculos",
            estado="ativo",
            nome_remetente=nome or "",
            dados={"historico": []},
        )
        db.session.add(conversa)

    if nome and not conversa.nome_remetente:
        conversa.nome_remetente = nome

    conversa.atualizado_em = datetime.utcnow()
    _salvar_historico(conversa, "user", texto)

    historico = _montar_historico(conversa)

    try:
        if os.environ.get("ANTHROPIC_API_KEY"):
            resposta = _chamar_anthropic(historico)
        elif os.environ.get("OPENAI_API_KEY"):
            resposta = _chamar_openai(historico)
        else:
            resposta = _fallback(texto)
    except Exception as exc:
        resposta = _fallback(texto)
        import logging
        logging.getLogger(__name__).error("Erro IA Oráculos: %s", exc)

    _salvar_historico(conversa, "assistant", resposta)
    db.session.commit()
    return resposta
