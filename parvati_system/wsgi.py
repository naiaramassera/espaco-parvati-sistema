"""Entry point para Gunicorn / produção."""
import threading
import os

from dotenv import load_dotenv
load_dotenv()

from parvati_system.app import app
from parvati_system.models import db, User
from werkzeug.security import generate_password_hash


def _inicializar():
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(email="naiara@espacoparvati.com").first():
            admin = User(
                nome="Naiara",
                email="naiara@espacoparvati.com",
                senha=generate_password_hash(
                    os.environ.get("PARVATI_ADMIN_SENHA", "Parvati@2026")
                ),
                perfil="admin",
                profissional="Naiara",
                ativo=True,
            )
            db.session.add(admin)
            db.session.commit()


def _iniciar_automacoes():
    from parvati_system.automacoes import iniciar_automacoes
    iniciar_automacoes()


_inicializar()

# Roda automações apenas no processo principal (não em workers do gunicorn)
if os.environ.get("AUTOMACOES_ATIVAS", "1") == "1":
    _t = threading.Thread(target=_iniciar_automacoes, daemon=True)
    _t.start()

# importa rotas
from parvati_system import routes  # noqa: F401, E402
