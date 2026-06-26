import json
import os
from urllib import error, request


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


def _money(value):
    return f"R$ {float(value or 0):.2f}"


def montar_contexto_marketing(metricas, procedimentos, retornos, inativos):
    procedimentos_texto = ", ".join(
        f"{item.nome} ({item.categoria or 'geral'}, valor {_money(item.valor_padrao)})"
        for item in procedimentos[:8]
    ) or "procedimentos esteticos faciais e corporais"

    retornos_texto = ", ".join(
        f"{item['agendamento'].procedimento} em {item['data_retorno'].strftime('%d/%m')}"
        for item in retornos[:5]
    ) or "sem retornos urgentes"

    inativos_texto = ", ".join(
        f"{item['cliente'].nome} ({item['dias']} dias)"
        for item in inativos[:5]
    ) or "sem lista relevante"

    return {
        "metricas": metricas,
        "procedimentos": procedimentos_texto,
        "retornos": retornos_texto,
        "inativos": inativos_texto,
    }


def gerar_campanha_fallback(objetivo, publico, contexto, orcamento_centavos):
    foco = objetivo or "reativar clientes e preencher a agenda da semana"
    publico_texto = publico or "mulheres que ja conhecem a clinica e clientes com interesse em estetica"
    procedimentos = contexto.get("procedimentos") or "procedimentos esteticos"

    return {
        "pesquisa": (
            "Sugestao local baseada nos dados internos da agenda, retornos, clientes inativos "
            "e catalogo de procedimentos. Configure OPENAI_API_KEY para pesquisa assistida por IA."
        ),
        "estrategia": (
            f"Priorizar {publico_texto}. Comecar com post organico e impulsionar somente "
            "se a agenda da semana ainda tiver horarios livres."
        ),
        "legenda": (
            f"{foco.capitalize()} na Parvati Estetica.\n\n"
            f"Temos opcoes como {procedimentos}. Cada atendimento e avaliado com cuidado para "
            "indicar o melhor plano para sua pele, rotina e objetivo.\n\n"
            "Envie uma mensagem e veja os horarios disponiveis."
        ),
        "chamada": "Quero avaliar meus horarios",
        "hashtags": "#ParvatiEstetica #EsteticaAvancada #CuidadosComAPele #BelezaComCuidado",
        "orcamento_centavos": max(0, int(orcamento_centavos or 0)),
    }


def _extract_text(data):
    if data.get("output_text"):
        return data["output_text"]

    chunks = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in ("output_text", "text"):
                chunks.append(content.get("text", ""))
    return "\n".join(chunks).strip()


def _parse_json_object(text):
    text = (text or "").strip()
    if not text:
        raise ValueError("Resposta vazia da IA.")
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("A IA nao retornou JSON.")
    return json.loads(text[start:end + 1])


def gerar_campanha_ia(objetivo, publico, contexto, orcamento_centavos):
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return gerar_campanha_fallback(objetivo, publico, contexto, orcamento_centavos)

    model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
    system = (
        "Voce e uma estrategista de marketing para uma clinica de estetica premium no Brasil. "
        "Crie campanhas responsaveis, sem prometer resultados medicos, sem antes/depois enganoso "
        "e sem linguagem sensacionalista. Responda somente JSON valido."
    )
    user = {
        "objetivo": objetivo,
        "publico": publico,
        "orcamento_centavos": int(orcamento_centavos or 0),
        "contexto": contexto,
        "formato": {
            "pesquisa": "resumo de oportunidades, tendencias e angulos de conteudo",
            "estrategia": "plano pratico de postagem e impulsionamento",
            "legenda": "texto pronto para Facebook/Instagram",
            "chamada": "CTA curto",
            "hashtags": "hashtags em uma string",
            "orcamento_centavos": "valor recomendado, nunca acima do informado",
        },
    }

    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "temperature": 0.4,
    }
    if os.environ.get("PARVATI_OPENAI_WEB_SEARCH") == "1":
        payload["tools"] = [{"type": "web_search_preview"}]

    req = request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Erro OpenAI HTTP {exc.code}: {detail[:500]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Erro de conexao com OpenAI: {exc}") from exc

    result = _parse_json_object(_extract_text(data))
    result["orcamento_centavos"] = min(
        max(0, int(result.get("orcamento_centavos") or 0)),
        max(0, int(orcamento_centavos or 0)),
    )
    return result
