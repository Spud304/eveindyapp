import os
import json
import logging

from flask_login import LoginManager
from dotenv import load_dotenv

from flask_migrate import Migrate

from src.models.models import db, User
from src.application import Application
from src.auth import AuthBlueprint
from src.user import UserBlueprint
from src.industry import IndustryBlueprint
from src.config import ConfigBlueprint

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
logger = logging.getLogger(__name__)

CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
CALLBACK_URL = os.environ.get('CALLBACK_URL')
DB_NAME = os.environ.get('DB_NAME')
STATIC_DB = os.environ.get('STATIC_DB')
SCOPES = os.environ.get('SCOPES', 'publicData')

# Ensure SCOPES is URL encoded and space delimited
scopes_list = SCOPES.split()
encoded_scopes = "%20".join(scopes_list)
SCOPES = json.loads(SCOPES) if isinstance(SCOPES, str) else SCOPES
SCOPES = "%20".join(SCOPES)

if CLIENT_ID is None or CLIENT_SECRET is None or CALLBACK_URL is None:
    raise ValueError("CLIENT_ID, CLIENT_SECRET, and CALLBACK_URL must be set in the environment variables.")

if DB_NAME is None:
    raise ValueError("DB_NAME must be set in the environment variables.")

instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
app = Application(__name__, instance_path=instance_path)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_NAME}.sqlite'
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY")
app.config['SQLALCHEMY_BINDS'] = {
    'static': f'sqlite:///{STATIC_DB}.sqlite',
    'base': f'sqlite:///{DB_NAME}.sqlite'
}

db.init_app(app)
migrate = Migrate(app, db)


login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'auth.login'

@login_manager.user_loader
def load_user(user_id):
    """ Load the user from the database """
    return db.session.get(User, int(user_id))

with app.app_context():
    db.create_all()

auth_blueprint = AuthBlueprint('auth', __name__, CLIENT_ID, CLIENT_SECRET, scopes=SCOPES)
app.register_blueprint(auth_blueprint)

user_blueprint = UserBlueprint('user', __name__)
app.register_blueprint(user_blueprint)

industry_blueprint = IndustryBlueprint('industry', __name__)
app.register_blueprint(industry_blueprint)

config_blueprint = ConfigBlueprint('config', __name__)
app.register_blueprint(config_blueprint)

if __name__ == '__main__':
    app.run(debug=False, host="localhost", port=5050)
