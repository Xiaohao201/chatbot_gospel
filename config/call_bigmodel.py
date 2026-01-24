from zhipuai import ZhipuAI
from typing import List, Dict

def call_bigmodel(messages: List[Dict], model_name: str = "glm-4", temperature: float = 0.7, top_p: float = 0.9):
    client = ZhipuAI(api_key="78dca153d76749fe8cfcfe1461e31323.sIzuBt2atrC16tqX")
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            temperature=temperature,
            top_p=top_p
        )
        return response
    except Exception as e:
        print(f"API调用失败: {str(e)}")
        return None

if __name__ == "__main__":
    messages = [
        {"role": "user", "content": "你好，请介绍一下你自己。"}
    ]
    response = call_bigmodel(messages)
    if response:
        print(response.choices[0].message.content.strip())
    else:
        print("API调用失败")
