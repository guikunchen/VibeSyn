from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Any, Dict
from bayesian_optimization import get_next_exps
import uvicorn
import traceback
import json
import threading

app = FastAPI()


@app.get('/ping')
def ping():
    """
    Health check endpoint.

    Returns:
        JSON response with server online status.
    """
    return {"status": "online"}


tool_data = {
    "q": 4,
    "goal": [
        {
            "name": "yield",
            "target": "max"
        }
    ],
    "num_of_init": 4,
    "reaction": "aa"
}


class ExpData(BaseModel):
    TaskId: str = ""
    ConversationId: str = ""
    data: str


# 存储优化结果，query 时返回
optimization_result = None
result_lock = threading.Lock()


def run_optimization(payload, dropped_keys):
    global optimization_result
    try:
        result = get_next_exps(payload)
        # 剔除由 tool_data 填充的默认字段，避免带入反馈结果
        result = {k: v for k, v in result.items() if k not in dropped_keys}
        with result_lock:
            optimization_result = result
    except Exception as e:
        with result_lock:
            optimization_result = {"error": str(e), "traceback": traceback.format_exc()}


@app.post("/receive_data")
async def next_exps(data: ExpData):
    try:
        if data.data == "query":
            with result_lock:
                if optimization_result is None:
                    return {"status": "running"}
                return optimization_result

        payload = json.loads(data.data)
        # 记录哪些字段来自 tool_data 默认值（客户端未显式提供）
        dropped_keys = [k for k in tool_data if k not in payload]
        payload = {**tool_data, **payload}
        threading.Thread(target=run_optimization, args=(payload, dropped_keys), daemon=True).start()
        return {"status": "running"}
    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


if __name__ == '__main__':
    uvicorn.run(app=app, host="", port=123)
