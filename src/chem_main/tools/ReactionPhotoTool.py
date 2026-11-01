from pydantic import Field, create_model
import os
import base64
import json

from chem_main.template import ToolTemplate
from chem_main.utils import transform2dict, get_json_parser, get_latest_task_json


class ReactionPhotoTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "ReactionPhotoToolJSON",
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
Analyze the provided image, which is a reaction vessel; the lower half of the vessel contains a solution and a magnetic stirrer, and the upper half is air.
The reaction was considered to have reached the visual endpoint only when the solution became yellowish-white and shows milky white precipitate/turbidity. 
Any remaining amber, or brownish color indicated that Fe(III) species were still present and that the reaction had not yet reached the endpoint.
Return whether the reaction has reached the defined visual endpoint yet and the reason.""",
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
    tool = ReactionPhotoTool()
    tool.img_reasoning("resources/ReacExecDevice/Execution_01")


# Return the solution state, including color, transparency, whether it contains milky white turbidity, whether there is obvious solid precipitate, etc.
# Note: Only when the solution is completely clear and transparent OR the white elliposid is clear should the white ellipsoid at the bottom of the solution be regarded as a magnetic stirrer; 
# if the solution is not fully clear and transparent, any white solid present in the solution should be regarded as an insoluble white substance rather than identified as the magnetic stirrer.
