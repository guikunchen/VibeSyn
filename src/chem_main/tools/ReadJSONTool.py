from typing import Dict
from pydantic import Field, create_model
import os
import json
from langchain_openai import ChatOpenAI

from chem_main.template import ToolTemplate
from chem_main.utils import get_json_parser


class ReadJSONTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "ReadJSONToolJSON",
            filename=(str, Field(..., description="The name of the JSON file to read, e.g., 'data.json'")),
        ))
        self.llm = ChatOpenAI(model='gpt-5', base_url=os.environ.get("OPENAI_API_BASE"))

    def msg2json(self, msg: str) -> Dict:
        json_data = self.json_chain.invoke({"query": msg})

        #  NOTE: postprocessing

        return json_data
    
    def process_locally(self, task_file_path) -> str:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_send_flag = task_data["waiting_info"][self.__class__.__name__].get("task_send_flag", False)
        tool_input_task = task_data["waiting_info"][self.__class__.__name__]['task']
        tool_input_task = json.loads(tool_input_task) if isinstance(tool_input_task, str) else tool_input_task
        
        if task_send_flag:        
            file_path = os.path.join('history_files', 'tasks', task_data['task_name'], tool_input_task['filename'])
            with open(file_path, 'r', encoding='utf-8') as f:
                res = json.load(f)
        else:
            res = "waiting"
            task_data["waiting_info"][self.__class__.__name__]['task_send_flag'] = True

        task_data["waiting_info"][self.__class__.__name__]['results'] = res
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)

if __name__ == "__main__":
    tool = ReadJSONTool()
    tool.unit_test()
