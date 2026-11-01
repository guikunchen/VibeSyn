from pydantic import Field, create_model
import os
import base64
import json

from chem_main.template import ToolTemplate
from chem_main.utils import transform2dict, get_json_parser, get_latest_task_json


class SepExecPhotoTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "SepExecPhotoToolJSON",
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
Analyze the provided image, the image shows a flash chromatography curve. 
The green dashed line represents the ethyl acetate gradient OR MeOH gradient (0-100%), 
the blue line represents the absorption curve at 254 nm, and the orange line represents the absorption curve at 280 nm. 
The vertical axis on the right represents the gradient (in %). The horizontal axis represents the column volumes used for the chromatographic separation.
Please analyze the curve (indicate the possible substance corresponding to each peak).
""",
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
    tool = SepExecPhotoTool()
    tool.img_reasoning("resources/SepExecDevice/Execution_01")


# • Image displays **complete separation into two distinct phases** (e.g., clear upper and lower layers).
# • A **sharp, well-defined dividing line** is visible between the two phases.
