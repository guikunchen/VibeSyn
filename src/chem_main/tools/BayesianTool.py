from typing import Dict
from pathlib import Path
import requests
import json

from chem_main.template import ToolTemplate
from chem_main.utils import str2dict_llm, handle_response, transform2dict_recursive


class BayesianTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        # self.json_chain = get_json_parser(create_model(
        #     "NMRToolJSON",
        #     mode=(str, Field(description="mode"))
        # ))
        
        # Define config file path
        self.config_dir = Path("src/chem_main/tools/config")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / f"{self.__class__.__name__}.json"
        self.default_config = {
            'connection_settings': {
                'http_url': 'http://10.97.50.51:8001',
                'http_status': None,
            },
        }

    def send_task2tool(self, tool_input_json) -> str:
        """Send tool input string to tool via HTTP without querying results"""
        # Get connection settings from file
        tool_config = self._load_tool_config()
        connection_settings = tool_config['connection_settings']
        
        url = connection_settings['http_url'] + "/receive_data"
        
        try:
            response = requests.post(url, json=tool_input_json)
            response_data = response.json()
            status = response_data.get("status")
            
            if response.status_code == 200:
                return f"Task sent successfully, status: {status}"
            else:
                return f"Failed to send task, HTTP status: {response.status_code}"
                
        except Exception as e:
            print(f"Error occurred while sending task: {e}")
            return f"Error sending task: {str(e)}"


    def query_task_result(self, task_file_path) -> str:
        """Query tool for results through HTTP"""
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        # Get connection settings from file
        tool_config = self._load_tool_config()
        connection_settings = tool_config['connection_settings']
        
        url = connection_settings['http_url'] + "/receive_data"
        data = {"data": "query"}  # Send query command
        
        # print(task_data)
        try:
            response = requests.post(url, json=data)
            response_data = response.json()
            status = response_data.get("status")
            
            if status == "running":
                return "waiting"
            elif status == "success":  # NOTE: Personalized
                res_str, resource_paths = handle_response(task_data['task_name'], self.__class__.__name__, response_data)
                task_data["waiting_info"][self.__class__.__name__]['resource_paths'] = resource_paths
                with open(task_file_path, 'w', encoding='utf-8') as f:
                    json.dump(task_data, f, indent=2)
                return res_str
            else:
                return "waiting"
                
        except Exception as e:
            print(f"Error occurred while querying results: {e}")
            return f"Error querying results: {str(e)}"

    def msg2json(self, msg: str) -> Dict:
        """Convert message to JSON format using the JSON chain, and then do postprocessing"""
        json_data = str2dict_llm(msg)
        json_data = transform2dict_recursive(json_data)
        return json_data
    
    def process_locally(self, task_file_path) -> str:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_send_flag = task_data["waiting_info"][self.__class__.__name__].get("task_send_flag", False)
        if task_send_flag:
            res = self.query_task_result(task_file_path)
        else:
            if isinstance(task_data["waiting_info"][self.__class__.__name__]['task'], dict):
                tool_input_task = json.dumps(task_data["waiting_info"][self.__class__.__name__]['task'], ensure_ascii=False)
            else:
                tool_input_task = task_data["waiting_info"][self.__class__.__name__]['task']
            tool_input_json = {'data': tool_input_task, 'TaskId': task_data['task_name'], 'ConversationId': task_data['messages'][-1]['time'] }
            print(self.send_task2tool(tool_input_json))
            res = "waiting"
            task_data["waiting_info"][self.__class__.__name__]['task_send_flag'] = True
            with open(task_file_path, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2)

        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_data["waiting_info"][self.__class__.__name__]['results'] = res
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)


if __name__ == "__main__":
    tool = BayesianTool()
