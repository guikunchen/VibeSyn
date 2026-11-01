from pydantic import Field, create_model
import os
import base64
import json

from chem_main.template import ToolTemplate
from chem_main.utils import transform2dict, get_json_parser, get_latest_task_json


class ExtracExecPhotoTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "ExtracExecPhotoToolJSON",
            img_path=(str, Field(description="path to the captured image"))
        ))

    def process_locally(self, task_file_path) -> str:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        given_task = transform2dict(task_data["waiting_info"][self.__class__.__name__]['task'])
        input_img_path = given_task['img_path']
        res = self.img_reasoning(input_img_path)
        
        task_data["waiting_info"][self.__class__.__name__]['results'] = res
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
        return res
    
    def _encode_image(self, image_path):
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode("utf-8")

    def img_reasoning(self, img_path):
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"],
            base_url=os.environ.get("OPENAI_API_BASE"),
        )
        task_data, task_json_path = get_latest_task_json()
        img_path = os.path.join("history_files/tasks", task_data['task_name'], img_path, 'image_01.png')
        base64_image = self._encode_image(img_path)
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """**Task:**  
Analyze the provided image, which is an image showing the extraction process in a separating funnel. The white cylinder in the middle of the separatory funnel is the stirring paddle.
Determine whether the image exhibits **Phase separation succeed** or **Phase separation unfinished**.  

**Criteria:**  

1. **Phase separation unfinished**: 
• Image shows **incomplete separation** (e.g., the overall liquid or the intermediate layer is milky or cloudy) **OR** 
• The liquid is divided into three or more layers.
2. **Phase separation succeed**: 
• Without **milky/cloudy layer** persisting between the two phases, and small bubbles in the solution can be ignored.

**Instructions:**  

1. Compare image against the criteria above.  
2. Return **only one** of the following labels along with a simple description of the image status.
• The extraction process in image shows: Phase separation succeed
• The extraction process in image shows: Phase separation unfinished""",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                        },
                    ],
                }
            ],
        )

        return response.choices[0].message.content


if __name__ == "__main__":
    tool = ExtracExecPhotoTool()
    tool.img_reasoning("resources/ExracExecDevice/Execution_01")


# • Image displays **complete separation into two distinct phases** (e.g., clear upper and lower layers).
# • A **sharp, well-defined dividing line** is visible between the two phases.
