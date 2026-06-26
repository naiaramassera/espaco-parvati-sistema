import os
from dotenv import load_dotenv
load_dotenv()

from parvati_system.app import app
from parvati_system.models import db, User
from werkzeug.security import generate_password_hash

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

from parvati_system import routes  # noqa: F401, E402
