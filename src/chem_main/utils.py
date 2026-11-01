from pathlib import Path
import os
import copy
import json
from datetime import datetime
import base64
from PIL import Image
from io import BytesIO
from langchain_openai import ChatOpenAI
from typing import Any, Optional
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
import re

def get_latest_task_json():
    task_dirs = sorted(Path("history_files/tasks").iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)
    
    task_dirs = [d for d in task_dirs if d.is_dir()]
    
    if task_dirs:
        latest_dir = task_dirs[0]
        
        task_json_path = latest_dir / "task.json"
        
        if task_json_path.exists():
            with open(task_json_path, 'r', encoding='utf-8') as f:
                task_data = json.load(f)
        else:
            task_data = {}
    else:
        task_data = {}
    
    return task_data, task_json_path

def transform2dict(sth):
    return json.loads(sth) if isinstance(sth, str) else sth


def transform2dict_recursive(sth):
    """Recursively transform strings to dicts and handle nested structures"""
    try:
        # If it's a string, try to parse it as JSON
        if isinstance(sth, str):
            parsed = json.loads(sth)
            return transform2dict(parsed)  # Recursively process the parsed result
        
        # If it's a dict, recursively process all values
        elif isinstance(sth, dict):
            return {key: transform2dict(value) for key, value in sth.items()}
        
        # If it's a list, recursively process all items
        elif isinstance(sth, list):
            return [transform2dict(item) for item in sth]
        
        # For other types, return as-is
        else:
            return sth
            
    except (json.JSONDecodeError, TypeError):
        return sth


def handle_response(task_name: str, device_name: str, response_data: dict) -> str:
    def _get_next_execution_number(base_path: str) -> int:
        if not os.path.isdir(base_path):
            return 1
        execution_pattern = re.compile(r'Execution_(\d+)')
        
        max_num = 0
        try:
            for item in os.listdir(base_path):
                if os.path.isdir(os.path.join(base_path, item)):
                    match = execution_pattern.match(item)
                    if match:
                        num = int(match.group(1))
                        if num > max_num:
                            max_num = num
        except OSError:
            return 1

        return max_num + 1

    res_messages, resource_paths = [], []
    if "images" in response_data and isinstance(response_data["images"], list) and response_data["images"]:
        base_image_dir = f"history_files/tasks/{task_name}/resources/{device_name}"
        
        try:
            next_exec_num = _get_next_execution_number(base_image_dir)
            execution_dir_name = f"Execution_{next_exec_num:02d}"
            execution_path = os.path.join(base_image_dir, execution_dir_name)
            os.makedirs(execution_path, exist_ok=True)
            
            num_images_saved = 0
            for idx, image_item in enumerate(response_data["images"]):
                if isinstance(image_item, dict) and "image_data" in image_item:
                    image_data = image_item["image_data"]
                    if isinstance(image_data, str) and image_data:
                        try:
                            img_bytes = base64.b64decode(image_data)
                            img = Image.open(BytesIO(img_bytes))
                            img_filename = f"image_{idx + 1:02d}.png"
                            img.save(os.path.join(execution_path, img_filename))
                            resource_paths.append(os.path.join(execution_path, img_filename))
                            num_images_saved += 1
                        except base64.binascii.Error:
                            res_messages.append(f"Warning: Image {idx+1} has invalid base64 data.")
                        except Exception as e:
                            res_messages.append(f"Warning: Could not save image {idx+1}. Error: {e}")
                    elif isinstance(image_data, str) and not image_data:
                        res_messages.append(f"Warning: Image {idx+1} data is empty, skipped.")
                    else:
                        res_messages.append(f"Warning: Image {idx+1} 'image_data' is not a string or is missing, skipped.")
                else:
                    res_messages.append(f"Warning: Image item at index {idx+1} is not a valid dictionary or 'image_data' is missing, skipped.")

            if num_images_saved > 0:
                res_messages.append(f"{num_images_saved} image(s) saved in folder \"resources/{device_name}/{execution_dir_name}\".")
            elif not any("Warning:" in msg for msg in res_messages):
                res_messages.append("No valid images found to save.")

        except OSError as e:
            res_messages.append(f"Error creating directory for images: {e}")
        except Exception as e:
            res_messages.append(f"An unexpected error occurred during image processing: {e}")

    if "yield" in response_data:
        res_messages.append(f"Yield: {response_data['yield']}.")

    if "Peptide result" in response_data:
        res_messages.append(f"Peptide result: {response_data['Peptide result']}.")

    if "NMR result" in response_data:
        res_messages.append(f"{response_data['NMR result']}.")

    if "path1_info" in response_data:
        base_dir = f"history_files/tasks/{task_name}/resources/{device_name}"
        next_exec_num = _get_next_execution_number(base_dir)
        execution_dir_name = f"Execution_{next_exec_num:02d}"
        execution_path = os.path.join(base_dir, execution_dir_name)
        os.makedirs(execution_path, exist_ok=True)

        all_paths = {}
        NUM_PATHS = 10
        for i in range(NUM_PATHS):
            path_info_key = "path" + str(i+1) + "_info"
            path_key = "path" + str(i+1)
            path_info_data = response_data.get(path_info_key)
            path_data = response_data.get(path_key)
            if path_info_data:
                with open(os.path.join(execution_path, f'{path_info_key}.json'), 'w') as json_file:
                    json.dump(path_info_data, json_file, indent=4)
                resource_paths.append(os.path.join(execution_path, f'{path_info_key}.json'))
                
            if path_data:
                with open(os.path.join(execution_path, f'{path_key}.json'), 'w') as json_file:
                    json.dump(path_data, json_file, indent=4)
                resource_paths.append(os.path.join(execution_path, f'{path_key}.json'))

        res_messages.append(f"{NUM_PATHS} path(s) saved in folder \"resources/{device_name}/{execution_dir_name}\".")
    
    if not res_messages:
        return "Task completed successfully.", resource_paths
    else:
        return "Task completed. " + " ".join(res_messages), resource_paths


def gen_new_message(task_data):
    return {"role": "assistant", "content": f"C-{datetime.now().strftime('%Y%m%d-%H%M%S')} | {task_data['cur_task_type']} | {task_data['cur_task_content']}", "time": f"C-{datetime.now().strftime('%Y%m%d-%H%M%S')}", "task_type": task_data['cur_task_type'], "task_content": task_data['cur_task_content'], "waiting_info": copy.deepcopy(task_data.get("waiting_info", {}))}


def get_json_parser(
    pydantic_model: type[BaseModel],
    mode: str = "structured_output",
    *,
    system_prompt: Optional[str] = None,
    enable_direct_parse: bool = True,
    postprocess=None,
    llm: Optional[ChatOpenAI] = None,
):
    def _extract_query(inp: Any) -> Any:
        if isinstance(inp, dict) and "query" in inp:
            return inp["query"]
        return inp

    def _model_to_dict(result: Any) -> dict:
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        if isinstance(result, dict):
            return result
        raise TypeError(f"Unsupported result type: {type(result)}")

    def _direct_parse(raw_query: Any) -> Optional[dict]:
        try:
            if isinstance(raw_query, dict):
                return pydantic_model.model_validate(raw_query).model_dump()

            if isinstance(raw_query, str):
                s = raw_query.strip()
                if s.startswith("{") and s.endswith("}"):
                    return pydantic_model.model_validate_json(s).model_dump()
        except Exception:
            return None

        return None

    def _default_system_prompt() -> str:
        from pydantic_core import PydanticUndefined
        defaults = {
            name: field.default
            for name, field in pydantic_model.model_fields.items()
            if field.default is not PydanticUndefined
        }
        defaults_str = json.dumps(defaults, ensure_ascii=False) if defaults else "{}"
        defaults_str = defaults_str.replace("{", "{{").replace("}", "}}")
        allowed_keys = list(pydantic_model.model_fields.keys())

        return (
            "You are a JSON transcriber, not an editor.\n"
            "Return exactly one valid JSON object.\n"
            f"The only allowed keys are: {', '.join(allowed_keys)}.\n"
            f"If the input already contains any allowed key, copy its value verbatim.\n"
            f"If a key is missing, use its default value exactly as defined here: {defaults_str}.\n"
            "Do not paraphrase, summarize, infer, normalize, translate, repair, or rewrite any existing field value.\n"
            "Keep all original text content unchanged.\n"
            "Only escape characters when required for valid JSON syntax.\n"
            "Output raw JSON only. No markdown. No explanation."
        )

    if llm is None:
        llm = ChatOpenAI( model="gpt-4o-2024-11-20" )

    if system_prompt is None:
        system_prompt = _default_system_prompt()

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("human", "{query}"),
        ]
    )

    if mode == "structured_output":
        chain = prompt | llm.with_structured_output(
            pydantic_model,
            method="json_schema",
        )
    elif mode == "function_calling":
        chain = prompt | llm.with_structured_output(
            pydantic_model,
            method="function_calling",
        )
    elif mode == "json_mode":
        chain = prompt | llm.bind(response_format={"type": "json_object"})
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    class DictWrapper:
        def __init__(self, chain):
            self.chain = chain

        def invoke(self, inp: Any, *args, **kwargs) -> dict:
            raw_query = _extract_query(inp)

            if enable_direct_parse:
                direct = _direct_parse(raw_query)
                if direct is not None:
                    return postprocess(direct, raw_query) if postprocess else direct

            chain_input = inp if isinstance(inp, dict) and "query" in inp else {"query": raw_query}
            result = self.chain.invoke(chain_input, *args, **kwargs)

            if mode == "json_mode":
                if not hasattr(result, "content"):
                    raise TypeError(f"Unexpected result type in json_mode: {type(result)}")
                out = pydantic_model.model_validate_json(result.content).model_dump()
            else:
                out = _model_to_dict(result)

            return postprocess(out, raw_query) if postprocess else out

    return DictWrapper(chain)

def str2dict_llm(input_str: str) -> str:
    llm = ChatOpenAI( model="gpt-4o-2024-11-20", ).bind(response_format={"type": "json_object"})

    system_prompt = """You convert input text into exactly one JSON object.

Rules:
1. If the input already contains one complete valid JSON object, extract and return that object only.
2. Otherwise, generate one JSON object that best represents the content.
3. Output must be a single JSON object at the root.
4. Do not output markdown, explanations, or code fences.
5. Escape quotes and braces correctly inside string values.
6. If some content cannot be reliably structured, place it under a reasonable key instead of inventing facts.
"""

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{text}")
    ])

    response_str = (prompt | llm).invoke({"text": input_str}).content.strip()

    try:
        obj = json.loads(response_str)
    except json.JSONDecodeError as e:
        raise ValueError({
            "error": "LLM_RESPONSE_NOT_VALID_JSON",
            "reason": "Failed to parse the response as JSON.",
            "original_response": response_str,
            "parse_error": str(e),
        })

    if not isinstance(obj, dict):
        raise ValueError({
            "error": "LLM_RESPONSE_NOT_JSON_OBJECT",
            "reason": "The model returned valid JSON, but the root value is not an object/dict.",
            "original_response": response_str,
            "parsed_type": type(obj).__name__,
        })

    return response_str
