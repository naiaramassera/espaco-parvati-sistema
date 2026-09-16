"""
Testes ponta-a-ponta do chatbot da Mari.

Simula requisições reais do webhook do WhatsApp (Evolution API) contra um
banco temporário, cobrindo os bugs já corrigidos para que não voltem.

Como rodar:
    pip install -r requirements.txt
    python tests/test_chatbot.py
"""
import os
import sys
import time
import tempfile
from datetime import date, datetime, timedelta

_DB = os.path.join(tempfile.mkdtemp(), "teste_chatbot.db")
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["BOT_ATIVO"] = "1"          # webhook ativo durante os testes
os.environ.pop("ANTHROPIC_API_KEY", None)  # sem IA: usa a resposta de fallback
os.environ.pop("PROXIMO_DAY", None)
os.environ.pop("EVOLUTION_INSTANCE", None)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parvati_system.app import app  # noqa: E402
from parvati_system import routes  # noqa: E402,F401  (registra as rotas)
from parvati_system.models import db, Cliente, ConversaBot  # noqa: E402
import parvati_system.chatbot_agenda as cb  # noqa: E402

_falhas = []


def check(condicao, descricao):
    print(("PASS" if condicao else "FALHOU"), "-", descricao)
    if not condicao:
        _falhas.append(descricao)


def _payload(numero, texto, msg_id, ts=None, from_me=False, event="messages.upsert"):
    return {
        "event": event,
        "data": {
            "key": {"remoteJid": numero, "fromMe": from_me, "id": msg_id},
            "pushName": "",
            "message": {"conversation": texto},
            "messageTimestamp": ts or int(time.time()),
        },
    }


def enviar(cliente, numero, texto, msg_id, **kw):
    return cliente.post(
        "/webhook/whatsapp/agenda", json=_payload(numero, texto, msg_id, **kw)
    ).get_json()


def main():
    cliente_http = app.test_client()
    TEL = "5531988887777@s.whatsapp.net"

    # ── Fluxo da conversa e memória ──────────────────────────────────────────
    r1 = enviar(cliente_http, TEL, "oi", "MSG1")
    check("Qual é o seu nome" in r1.get("resposta", ""), "primeira mensagem pergunta o nome")

    r2 = enviar(cliente_http, TEL, "Ana Paula", "MSG2")
    check("Ana Paula" in r2.get("resposta", ""), "nome registrado corretamente")

    enviar(cliente_http, TEL, "quanto custa o botox?", "MSG3")
    enviar(cliente_http, TEL, "e a drenagem?", "MSG4")

    with app.app_context():
        conversa = ConversaBot.query.filter_by(telefone="5531988887777").first()
        historico = (conversa.dados or {}).get("historico", [])
        check(conversa.estado == "ia", "conversa fica no estado de IA")
        check(len(historico) >= 4, f"histórico PERSISTE no banco ({len(historico)} mensagens)")
        check((conversa.dados or {}).get("nome_cliente") == "Ana Paula", "nome persiste em dados")

    # ── Webhook: duplicadas, replay e mensagens antigas ──────────────────────
    repetida = enviar(cliente_http, TEL, "e a drenagem?", "MSG4")
    check("resposta" not in repetida, "mensagem duplicada é ignorada (dedup via banco)")

    historico_sync = enviar(cliente_http, TEL, "msg antiga", "OLD1", event="MESSAGES_SET")
    check("resposta" not in historico_sync, "evento MESSAGES_SET (replay) é ignorado")

    antiga = enviar(cliente_http, TEL, "msg de ontem", "OLD2", ts=int(time.time()) - 7200)
    check("resposta" not in antiga, "mensagem com 2h de idade é ignorada")

    propria = enviar(cliente_http, TEL, "eco do bot", "ME1", from_me=True)
    check("resposta" not in propria, "mensagem enviada pelo próprio bot é ignorada")

    # ── @lid não pode virar outra cliente ────────────────────────────────────
    with app.app_context():
        db.session.add(Cliente(nome="Fernanda Silva", telefone="31 99123-4567"))
        db.session.commit()

    LID = "88123991234567@lid"  # últimos 8 dígitos coincidem com o tel da Fernanda
    resposta_lid = enviar(cliente_http, LID, "oi", "LID1").get("resposta", "")
    check("Fernanda" not in resposta_lid, "@lid NÃO é saudado com nome de outra cliente")
    check("Qual é o seu nome" in resposta_lid, "@lid é tratado como contato novo")

    # ── Pergunta no lugar do nome ────────────────────────────────────────────
    TEL2 = "5531977776666@s.whatsapp.net"
    enviar(cliente_http, TEL2, "oi", "T2A")
    pergunta = enviar(cliente_http, TEL2, "quero saber o valor do botox?", "T2B")
    check("Quero Saber" not in pergunta.get("resposta", ""), "pergunta não vira nome da cliente")
    with app.app_context():
        c2 = ConversaBot.query.filter_by(telefone="5531977776666").first()
        check(c2.estado == "ia" and not c2.nome_remetente, "segue para IA sem registrar nome")

    # ── Prefixos no nome ─────────────────────────────────────────────────────
    TEL3 = "5531966665555@s.whatsapp.net"
    enviar(cliente_http, TEL3, "oi", "T3A")
    nome = enviar(cliente_http, TEL3, "me chamo Beatriz", "T3B").get("resposta", "")
    check("Beatriz" in nome and "Me Chamo" not in nome, "prefixo 'me chamo' é removido do nome")

    # ── Retomada após inatividade ────────────────────────────────────────────
    with app.app_context():
        parada = ConversaBot(
            telefone="5531900001111", canal="agenda", estado="horario",
            nome_remetente="Carla",
            dados={"nome_cliente": "Carla", "historico": [{"role": "user", "content": "oi"}],
                   "procedimento_nome": "Limpeza Facial"},
            atualizado_em=datetime.utcnow() - timedelta(hours=2),
        )
        db.session.add(parada)
        db.session.commit()

    with app.app_context():
        retomada = cb.processar_mensagem("5531900001111@s.whatsapp.net", "...", "")
        check("Ainda tem interesse" in retomada, "retoma agendamento após inatividade")
        conversa = ConversaBot.query.filter_by(telefone="5531900001111").first()
        check(len((conversa.dados or {}).get("historico", [])) == 2, "retomada PERSISTE no histórico")

    # ── Data do Day: nunca anunciar data vencida ─────────────────────────────
    hoje = date.today()
    os.environ["PROXIMO_DAY"] = (hoje - timedelta(days=30)).strftime("%d/%m")
    check("confirmada pela equipe" in cb._system_prompt(), "data vencida do Day NÃO é anunciada")

    futuro = (hoje + timedelta(days=20)).strftime("%d/%m")
    os.environ["PROXIMO_DAY"] = futuro
    check(futuro in cb._system_prompt(), "data futura do Day é anunciada")

    os.environ["PROXIMO_DAY"] = "sem data"
    cb._system_prompt()  # não pode levantar exceção
    check(True, "valor inválido em PROXIMO_DAY não quebra o bot")
    os.environ.pop("PROXIMO_DAY")

    # ── Botão de pausa ───────────────────────────────────────────────────────
    os.environ.pop("BOT_ATIVO")
    pausado = enviar(cliente_http, "5531911112222@s.whatsapp.net", "oi", "PAUSA1")
    check(pausado.get("pausado") is True and "resposta" not in pausado,
          "sem BOT_ATIVO a Mari fica em silêncio")
    os.environ["BOT_ATIVO"] = "1"

    print()
    if _falhas:
        print(f"{len(_falhas)} FALHA(S):")
        for f in _falhas:
            print("  -", f)
        return 1
    print("Todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
