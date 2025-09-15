import json
import time
import hashlib
import hmac
import base64
import uuid
import requests
import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()
mcp = FastMCP("switchbot")
token = os.getenv("SWITCHBOT_TOKEN")
secret = os.getenv("SWITCHBOT_SECRET")
light_on_id = os.getenv("SWITCHBOT_LIGHT_ON")
light_off_id = os.getenv("SWITCHBOT_LIGHT_OFF")

@mcp.tool()
def light_on():
    exec_scene(light_on_id)
    return "ハロ、電気オンした"

@mcp.tool()
def light_off():
    exec_scene(light_off_id)
    return "ハロ、電気オフした"

@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    return f"Hello, {name}!"

def make_header():
    # 必須環境変数の検証
    if not token or not secret:
        raise RuntimeError("SWITCHBOT_TOKEN / SWITCHBOT_SECRET が設定されていません。")

    # Declare empty header dictionary
    apiHeader = {}
    nonce = uuid.uuid4()
    t = int(round(time.time() * 1000))
    string_to_sign = f"{token}{t}{nonce}"

    string_to_sign_bytes = string_to_sign.encode('utf-8')
    secret_bytes = secret.encode('utf-8')

    sign = base64.b64encode(hmac.new(secret_bytes, msg=string_to_sign_bytes, digestmod=hashlib.sha256).digest())
    '''
    print('Authorization: {}'.format(token))
    print('t: {}'.format(t))
    print('sign: {}'.format(str(sign, 'utf-8')))
    print('nonce: {}'.format(nonce))'
    '''

    # Build api header JSON
    apiHeader['Authorization'] = token
    apiHeader['Content-Type'] = 'application/json'
    apiHeader['charset'] = 'utf8'
    apiHeader['t'] = str(t)
    apiHeader['sign'] = str(sign, 'utf-8')
    apiHeader['nonce'] = str(nonce)
    return apiHeader

def exec_scene(scene_id):
    url = "https://api.switch-bot.com/v1.1/scenes/" + scene_id + "/execute"
    apiHeader = make_header()
    response = requests.post(url, headers=apiHeader)

    # レスポンスの確認
    if response.ok:
        print("Response:")
        print(json.dumps(response.json(), indent=4, ensure_ascii=False))
    else:
        print("Error:", response.status_code)
        print(response.text)

def get_device_list():
    url = "https://api.switch-bot.com/v1.1/devices"
    apiHeader = make_header()
    response = requests.get(url, headers=apiHeader)
    if response.ok:
        print("Response:")
        print(json.dumps(response.json(), indent=4, ensure_ascii=False))
    else:
        print("Error:", response.status_code)
        print(response.text)
    return response.json()

def get_scene_list():
    url = "https://api.switch-bot.com/v1.1/scenes"
    apiHeader = make_header()
    response = requests.get(url, headers=apiHeader)
    if response.ok:
        print("Response:")
        print(json.dumps(response.json(), indent=4, ensure_ascii=False))
    else:
        print("Error:", response.status_code)
        print(response.text)
    return response.json()

if __name__ == "__main__":
    mcp.run(transport="stdio")
    '''
    print(get_device_list())
    print(get_scene_list())
    res = light_on()
    print(res)
    '''
