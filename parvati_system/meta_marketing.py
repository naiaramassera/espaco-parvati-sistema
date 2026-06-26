import json
import os
from urllib import error, parse, request


GRAPH_VERSION = os.environ.get("META_GRAPH_VERSION", "v23.0")
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"


def meta_configurado():
    return bool(os.environ.get("META_ACCESS_TOKEN") and os.environ.get("META_PAGE_ID"))


def _post_form(path, fields):
    token = os.environ["META_ACCESS_TOKEN"]
    data = dict(fields)
    data["access_token"] = token
    req = request.Request(
        f"{GRAPH_BASE}/{path.lstrip('/')}",
        data=parse.urlencode(data).encode("utf-8"),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta HTTP {exc.code}: {body[:600]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Erro de conexao com Meta: {exc}") from exc


def publicar_campanha(campanha):
    mensagem = "\n\n".join(
        parte for parte in [campanha.legenda, campanha.chamada, campanha.hashtags] if parte
    )
    canais = {item.strip() for item in (campanha.canais or "").split(",") if item.strip()}

    if not meta_configurado():
        return {
            "modo": "simulado",
            "motivo": "Configure META_ACCESS_TOKEN e META_PAGE_ID para publicar.",
            "canais": sorted(canais),
            "mensagem": mensagem,
        }

    resultados = {}
    page_id = os.environ["META_PAGE_ID"]
    if "facebook" in canais:
        resultados["facebook"] = _post_form(f"{page_id}/feed", {"message": mensagem})

    instagram_id = os.environ.get("META_INSTAGRAM_BUSINESS_ID")
    if "instagram" in canais:
        if instagram_id:
            media = _post_form(f"{instagram_id}/media", {"caption": mensagem})
            creation_id = media.get("id")
            if creation_id:
                resultados["instagram"] = _post_form(
                    f"{instagram_id}/media_publish",
                    {"creation_id": creation_id},
                )
            else:
                resultados["instagram"] = media
        else:
            resultados["instagram"] = {
                "modo": "pendente",
                "motivo": "Configure META_INSTAGRAM_BUSINESS_ID para publicar no Instagram.",
            }

    return resultados
