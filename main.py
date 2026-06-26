import threading
import os

from dotenv import load_dotenv
load_dotenv()

from parvati_system.app import app
from parvati_system.automacoes import iniciar_automacoes
from parvati_system.models import User, db
from werkzeug.security import generate_password_hash


def criar_admin_padrao():
    with app.app_context():
        db.create_all()

        user = User.query.filter_by(email="naiara@espacoparvati.com").first()
        if user:
            return

        user = User(
            nome="Naiara",
            email="naiara@espacoparvati.com",
            senha=generate_password_hash("Parvati@2026"),
            perfil="admin",
            profissional="Naiara",
            ativo=True
        )
        db.session.add(user)
        db.session.commit()


if __name__ == "__main__":
    criar_admin_padrao()

    automacoes = threading.Thread(target=iniciar_automacoes, daemon=True)
    automacoes.start()

    host = os.environ.get("PARVATI_HOST", "127.0.0.1")
    port = int(os.environ.get("PARVATI_PORT", "5000"))
    debug = os.environ.get("PARVATI_DEBUG", "0") == "1"

    app.run(host=host, port=port, debug=debug, use_reloader=False)
