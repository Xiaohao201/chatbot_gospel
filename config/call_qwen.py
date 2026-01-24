import requests
from typing import List, Dict
import dashscope
import json

with open("config/qwen.json", "r", encoding="utf-8") as f:
    qwen_config = json.load(f)

dashscope.api_key = qwen_config["apiKey"]

def call_qwen(messages: List[Dict], model_name: str = "qwen-turbo", temperature: float = 0.7, top_p: float = 0.9):
    headers = {
        "Authorization": f"Bearer {dashscope.api_key}",
        "Content-Type": "application/json"
    }
    data = {
        "model": model_name,
        "messages": messages,
        "headers": {'X-DashScope-DataInspection':{"input":"disable","output":"disable"}},
        "temperature": temperature,
        "top_p": top_p
    }
    response = requests.post(
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        headers=headers,
        json=data
    )
    if response.status_code == 200:
        return response.json()
    else:
        print(f"API调用失败: {response.status_code}, {response.text}")
        return None