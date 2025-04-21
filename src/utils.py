import random
import hmac
import hashlib
from flask import current_app


def generate_token():
    """Generates a non-guessable OAuth token"""
    chars = ('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    rand = random.SystemRandom()
    random_string = ''.join(rand.choice(chars) for _ in range(40))
    return hmac.new(
        current_app.config['SECRET_KEY'].encode('utf-8'),
        random_string.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()