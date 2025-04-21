import requests
import os
import json
import base64

from flask import Flask
from flask import redirect
from flask import render_template
from flask import request
from flask import session
from flask import url_for
from flask import request
from flask import jsonify

from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ.get('CLIENT_ID')
CLIENT_SECRET = os.environ.get('CLIENT_SECRET')
CALLBACK_URL = os.environ.get('CALLBACK_URL')

print(f"CLIENT_ID: {CLIENT_ID}")
print(f"CLIENT_SECRET: {CLIENT_SECRET}")
print(f"CALLBACK_URL: {CALLBACK_URL}")

app= Flask(__name__)

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET'])
def login():
    request_url = f"https://login.eveonline.com/v2/oauth/authorize/?response_type=code&redirect_uri={CALLBACK_URL}&client_id={CLIENT_ID}&scope=publicData&state=spudtest"
    return redirect(request_url)


@app.route('/callback', methods=['GET'])
def callback():
    """ This is where the user comes after he logged in SSO """
    
    # get the code from the login process
    code = request.args.get('code')
    token = request.args.get('state')

    oauthurl = 'https://login.eveonline.com/v2/oauth/token'

    params = {
        'grant_type': 'authorization_code',
        'code': code
    }

    auth_header = f"{CLIENT_ID}:{CLIENT_SECRET}"
    encoded_auth = base64.b64encode(auth_header.encode('utf-8')).decode('utf-8')
    headers = {
        'Authorization': f'Basic {encoded_auth}'
    }

    request_params = {
        'headers': headers,
        'data': params,
        'url': oauthurl
    }

    response = requests.post(**request_params)

    print(response.status_code)
    # print(response.headers)
    print(response.text)
    print(response.content)

    if response.status_code == 200:
        data = response.json()
        access_token = data['access_token']
        refresh_token = data['refresh_token']
        expires_in = data['expires_in']

        print(data)
    
        character_id = '2116911745'
    
        request2 = f'https://esi.evetech.net/latest/characters/{character_id}/'

        headers2 = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        response2 = requests.get(request2, headers=headers2)
        print(response2.status_code)
        print(response2.text)

        return jsonify(response2.json())
    
    return ('shits fucked')


if __name__ == '__main__':
    app.run(debug=True)