from pydantic import Field, create_model
import os
import base64
import json

from chem_main.template import ToolTemplate
from chem_main.utils import transform2dict, get_json_parser, get_latest_task_json


class SepOptPhotoTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "SepOptPhotoToolJSON",
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
Analyze the provided image. This is a thin-layer chromatography (TLC) image. The horizontal black line located ~1/4 of the distance from the top edge of the fluorescent silica gel plate is the solvent front, and ~1/5 of the distance from the bottom edge of the fluorescent plate are the starting line. There are three sets of samples on the fluorescent silica gel plate: the leftmost set is the reaction substrate (one spot), the rightmost set is a mixture after reaction, and the middle set is a mixture after the reaction with added reaction substrate. 

Please analyze the TLC characteristics of the three sets of samples, including the number of spots, the shape characteristics of the spots, the Rf values corresponding to the spots and possible tailing Rf range.

When estimating the Rf value, the estimate should not be too high (Since the image estimate tends to be high, please subtract 0.05-0.1 overall). The Rf value of the circular spot at ~1/5 of the distance from the bottom edge of the fluorescence silical gel plate is 0-0.02. The Rf value of the spot near the solvent front is 0.95-1.0.

The shape characteristics of spots:

1. Normal: The spot has a relatively round shape, with no noticeable tailing or a weak tailing, and it is not close to the solvent front.
2. Crescent-shaped: A crescent-shaped TLC spot appears as a curved, arc-like band rather than a compact round spot. It usually shows uneven migration, with one side darker or thicker and the spot spreading in a half-moon shape.
3. Tailing: The spot displays tailing, meaning the spot is elongated. It is important to distinguish the tail from the overlap of other spots.
4. Multiple spots that are difficult to separate: several spots almost overlap or are very close to each other; pay attention to distinguishing the trailing phenomenon.
5. Near the solvent front(no visible spot): no visible spot at main plate, a spot near the horizontal black line located ~1/4 of the distance from the top edge of the fluorescent silica gel plate (solvent front).
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
    tool = SepOptPhotoTool()
    tool.img_reasoning("resources/SepOptcDevice/Execution_01")


# • Image displays **complete separation into two distinct phases** (e.g., clear upper and lower layers).
# • A **sharp, well-defined dividing line** is visible between the two phases.
