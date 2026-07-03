"""
Gateway de envio de mensagens WhatsApp.

Configure uma das opções via variáveis de ambiente:

Z-API (recomendado para começar, ~R$97/mês):
  WHATSAPP_PROVIDER=zapi
  ZAPI_INSTANCE=<id-da-instancia>
  ZAPI_TOKEN=<token>
  ZAPI_CLIENT_TOKEN=<client-token>

Evolution API (grátis, self-hosted):
  WHATSAPP_PROVIDER=evolution
  EVOLUTION_URL=http://localhost:8080
  EVOLUTION_API_KEY=<chave>
  EVOLUTION_INSTANCE=parvati

Sem provider configurado: modo simulação (loga no console, não envia).
"""
import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


def _limpar_telefone(telefone: str) -> str:
    digitos = "".join(ch for ch in str(telefone or "") if ch.isdigit())
    if digitos.startswith("0"):
        digitos = digitos[1:]
    if not digitos.startswith("55"):
        digitos = "55" + digitos
    return digitos


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc


def _enviar_zapi(telefone: str, texto: str) -> bool:
    instance = os.environ["ZAPI_INSTANCE"]
    token = os.environ["ZAPI_TOKEN"]
    client_token = os.environ.get("ZAPI_CLIENT_TOKEN", "")
    numero = _limpar_telefone(telefone)
    url = f"https://api.z-api.io/instances/{instance}/token/{token}/send-text"
    headers = {
        "Content-Type": "application/json",
        "Client-Token": client_token,
    }
    payload = {"phone": numero, "message": texto}
    result = _post_json(url, payload, headers)
    return bool(result.get("zaapId") or result.get("messageId"))


def _enviar_evolution(telefone: str, texto: str) -> bool:
    base_url = os.environ.get("EVOLUTION_URL", "http://localhost:8080")
    api_key = os.environ["EVOLUTION_API_KEY"]
    instance = os.environ.get("EVOLUTION_INSTANCE", "parvati")
    if "@lid" in telefone or "@s.whatsapp.net" in telefone:
        numero = telefone
    else:
        numero = _limpar_telefone(telefone) + "@s.whatsapp.net"
    url = f"{base_url}/message/sendText/{instance}"
    headers = {
        "Content-Type": "application/json",
        "apikey": api_key,
    }
    payload = {"number": numero, "text": texto}
    result = _post_json(url, payload, headers)
    return bool(result.get("key") or result.get("status") == "PENDING")


def enviar_mensagem(telefone: str, texto: str) -> bool:
    """Envia mensagem WhatsApp. Retorna True se enviado, False se simulado."""
    provider = os.environ.get("WHATSAPP_PROVIDER", "").lower()

    if provider == "zapi":
        try:
            ok = _enviar_zapi(telefone, texto)
            logger.info("Z-API enviado para %s: %s", telefone, ok)
            return ok
        except Exception as exc:
            logger.error("Erro Z-API: %s", exc)
            raise

    if provider == "evolution":
        try:
            ok = _enviar_evolution(telefone, texto)
            logger.info("Evolution API enviado para %s: %s", telefone, ok)
            return ok
        except Exception as exc:
            logger.error("Erro Evolution API: %s", exc)
            raise

    # Modo simulação
    logger.warning(
        "[WHATSAPP SIMULADO] Para %s:\n%s", telefone, texto
    )
    print(f"\n[WHATSAPP SIMULADO] ▶ {telefone}\n{texto}\n")
    return False
