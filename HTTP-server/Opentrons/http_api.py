import time
import requests
import json
import os


def get_id(mac):
    robot_id = None
    info = os.popen('arp -a').read()
    info_str = info.split(' ')
    info_index = info_str.index(mac)
    for i in range(info_index - 1, 0, -1):
        if info_str[i] != '':
            robot_id = info_str[i]
            break
    return robot_id


def opentrons_control(file="D:\\Opentrons\\test.py"):
    mac = 'b8-27-eb-9e-0e-77'
    ip = get_id(mac)

    rack_2_4 = 'D:\\Auto_Opentrons\\unchained_8_tuberack_20000ul.json'
    rack_6_8 = 'D:\\Auto_Opentrons\\unchained_48_tuberack_2000ul.json'
    rack_2_5 = 'D:\\Auto_Opentrons\\autoopt_10_wellplate_10000ul.json'
    tiprack_8_12 = 'D:\\Auto_Opentrons\\autoopt_96_tiprack_1000ul.json'

    url = f"http://{ip}:31950/"
    headers = {
        "opentrons-version": "3"
    }

    files = [
        ("files", open(file, "rb")),
        ("files", open(rack_2_4, "rb")),
        ("files", open(rack_6_8, "rb")),
        ("files", open(rack_2_5, "rb")),
        ("files", open(tiprack_8_12, "rb")),
    ]

    protocol_data = requests.post(url + 'protocols', headers=headers, files=files)
    protocol_id = json.loads(protocol_data.text)["data"]["id"]
    # print(protocol_id)

    run_data = requests.post(url + 'runs', headers=headers, json={"data": {"protocolId": protocol_id}})
    run_id = json.loads(run_data.text)["data"]["id"]
    # print(run_id)

    response = requests.post(url + 'runs/' + run_id + '/actions', headers=headers, json={"data": {"actionType": "play"}})
    # print(response)

    while 1:
        time.sleep(10)
        r = requests.get(url + 'runs/' + run_id, headers=headers)
        run_status = json.loads(r.text)["data"]["status"]
        print(run_status)
        if run_status == 'succeeded':
            break
        elif run_status == 'failed':
            break

    return run_status


if __name__ == "__main__":
    opentrons_control(file="D:\\Opentrons\\LiquidAdd.py")

