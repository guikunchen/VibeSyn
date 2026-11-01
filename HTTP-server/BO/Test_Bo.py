import requests
import json

# 目标服务器 URL
url = '' + "/receive_data"

device_data = {
    "condition": [[11, 6, 'Pd(PPh3)4', 'Na2CO3'], [4.00, 5.72, 'SPhos Pd G3', 'K3PO4'], [7.48, 2.13, 'PdCl2(dppf)', 'K2CO3'], [6.21, 5.21, 'PdCl2(dppf)', 'Na2CO3'], [2.60, 4.08, 'XPhos Pd G3', 'K2CO3']],
    "outcomes": [0.164, 0.127, 0.538, 0.541, 0.101],
    "design_space": [{"name": "Catalyst loading (mol %)", "type": "continuous", "range": [ 2, 12 ] }, { "name": "Reaction time (hr)", "type": "continuous", "range": [ 2, 6 ] }, { "name": "Catalyst system", "type": "categorical", "range": [ 'Pd(PPh3)4', 'PdCl2(dppf)', 'XPhos Pd G3', 'SPhos Pd G3' ] }, { "name": "Base", "type": "categorical", "range": ['Na2CO3', 'K2CO3', 'K3PO4']}
                     ]
}

device_input_str = json.dumps(device_data)

data = {
    "TaskId": "T-20250725-193401-task4",
    "ConversationId": "C-20250327-013028",
    "data": "query"
}

# 发送 POST 请求
response = requests.post(url, json=data)

# 输出响应内容
if response.status_code == 200:
    print("Response from server:", response.json())
    response_data = response.json()
