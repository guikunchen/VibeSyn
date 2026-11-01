import os
from typing import Any, Dict, List, Optional, Union, Annotated
import json
from abc import ABC, abstractmethod
# from langchain.memory import ConversationBufferMemory
from langchain_classic.memory import ConversationBufferMemory
from langchain_community.chat_models import ChatZhipuAI, ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
# from langchain.schema import HumanMessage, SystemMessage, AIMessage
from pydantic import Field, create_model
from datetime import datetime
from chem_main.agent_manager import AgentManager
from chem_main.utils import gen_new_message, get_json_parser

class BaseAgent(ABC):
    def __init__(self, name: str, system_prompt: str, model_name: str = "glm-4-plus", temperature: float = 0.5,
                 api_key: str = None, api_url: str = None):
        self.name = name
        self.memory = ConversationBufferMemory(return_messages=True)
        if model_name.startswith("glm"):
            self.llm = ChatZhipuAI(model=model_name)
        elif model_name.startswith("gpt"):
            model_name_map = {"gpt-o3-2025-04-16": "o3-2025-04-16"}
            if model_name in model_name_map:
                model_name = model_name_map[model_name]
            api_key = api_key if isinstance(api_key, str) and len(api_key) > 10 else os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("Missing OPENAI_API_KEY.")
            base_url = api_url if isinstance(api_url, str) and len(api_url) > 10 else os.environ.get("OPENAI_API_BASE")
            self.llm = ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url)
        elif model_name.startswith("llama"):
            self.llm = ChatOllama(model=model_name, base_url=os.environ["OLLAMA_BASE_URL"])
        elif model_name.startswith("deepseek"):
            model_name_map = {'deepseek-v3': 'deepseek-v3-250324', 'deepseek-r1': 'deepseek-r1-250120'}
            self.llm = ChatOpenAI(model=model_name_map[model_name],
                                  api_key=os.environ["ARK_API_KEY"],
                                  base_url=os.environ["ARK_API_BASE"])
        else:
            raise ValueError(f"Unsupported model: {model_name}")
        self.system_prompt = system_prompt

    def _get_chat_history(self) -> List[str]:
        return self.memory.chat_memory.messages

    def _format_message(self, input_data: Union[Dict, str]) -> str:
        return json.dumps(input_data, ensure_ascii=False, indent=2) if isinstance(input_data, dict) else input_data

    def _save_to_memory(self, input_data: Union[Dict, str], output_data: Union[Dict, str]):
        input_msg = self._format_message(input_data) if isinstance(input_data, dict) else input_data
        output_msg = json.dumps(output_data, ensure_ascii=False, indent=2) if isinstance(output_data, dict) else output_data
        self.memory.chat_memory.add_user_message(input_msg)
        self.memory.chat_memory.add_ai_message(output_msg)

    def export_memory(self) -> Dict:
        memory_dict = {"messages": []}
        for msg in self.memory.chat_memory.messages:
            if isinstance(msg, HumanMessage):
                memory_dict["messages"].append({ "type": "human", "content": msg.content })
            else:
                memory_dict["messages"].append({ "type": "ai", "content": msg.content })
        if hasattr(self, "last_sender"):
            memory_dict["last_sender"] = self.last_sender
        if hasattr(self, "previous_memory"):
            memory_dict["previous_memory"] = self.previous_memory
        return memory_dict
    
    def import_memory(self, memory_dict: Dict):
        self.memory.clear()
        for msg_data in memory_dict.get("messages", []):
            if msg_data["type"] == "human":
                self.memory.chat_memory.add_user_message(msg_data["content"])
            elif msg_data["type"] == "ai":
                self.memory.chat_memory.add_ai_message(msg_data["content"])
        if memory_dict.get("last_sender", ""):
            self.last_sender = memory_dict["last_sender"]
        if memory_dict.get("previous_memory", ""):
            self.previous_memory = memory_dict["previous_memory"]


class WorkerAgent(BaseAgent):
    def __init__(self, agent_name, system_prompt, background, output_format, workflow,
                 initial_assistant_message="I see! I've learned about the roles and workflows you've described.",
                 model_name: str = "glm-4-plus", temperature: float = 0.5, api_key: str = None, api_url: str = None):
        super().__init__(agent_name, system_prompt, model_name, temperature, api_key, api_url)
        self.executor_options = [item['to'][1] for item in output_format]
        self.task_transfer_parser = self.get_task_transfer_parser(
            self.executor_options,
            mode="structured_output",
        )
        self._save_to_memory(self._concat_initial_user_message(background, self._output_format_lst2str(output_format), workflow), initial_assistant_message)
        self.background_promt = background
        self.previous_memory = []
        self.use_llm = True
    
    def _task_transfer_postprocess(self, result: dict, raw_query: Any, executor_options: list[str]) -> dict:
        out = {
            "recipient": result.get("recipient", "NONE"),
            "task": result.get("task", "NONE"),
            "results": result.get("results", "NONE"),
        }

        if out["recipient"] is None:
            out["recipient"] = "NONE"
        if out["task"] is None:
            out["task"] = "NONE"
        if out["results"] is None:
            out["results"] = "NONE"

        if out["recipient"] != "NONE" and out["recipient"] not in executor_options:
            raise ValueError(
                f"Invalid recipient: {out['recipient']}. "
                f"Allowed values: {executor_options} or 'NONE'."
            )

        has_recipient = out["recipient"] != "NONE"
        has_task = out["task"] != "NONE"
        has_results = out["results"] != "NONE"

        if has_recipient and has_task and not has_results:
            return out

        if has_results and not has_recipient and not has_task:
            return out

        if not has_recipient and not has_task and not has_results:
            return out

        raise ValueError(
            "Invalid TaskTransferJSON state. "
            "Expected either (recipient + task, results=NONE) "
            "or (results, recipient=NONE, task=NONE). "
            f"Got: {out}"
        )

    def get_task_transfer_parser(self, executor_options: list[str], mode: str = "structured_output"):
        TaskTransferJSON = create_model(
            "TaskTransferJSON",
            recipient=Annotated[Optional[str], Field(
                default="NONE",
                description=(
                    f"Recipient field. Copy verbatim if present. "
                    f"Allowed values are exactly: {executor_options} or NONE."
                )
            )],
            task=Annotated[Optional[str], Field(
                default="NONE",
                description=(
                    "Task field. Copy verbatim if present. "
                    "Do not paraphrase, summarize, normalize, or rewrite it."
                )
            )],
            results=Annotated[Optional[str], Field(
                default="NONE",
                description=(
                    "Results field. Copy verbatim if present. "
                    "Do not paraphrase, summarize, normalize, or rewrite it."
                )
            )],
        )

        system_prompt = (
            "You are a JSON transcriber, not an editor.\n"
            "Return exactly one valid JSON object with keys: recipient, task, results.\n"
            "If the input already contains any of these keys, copy the value verbatim.\n"
            "Do not paraphrase, summarize, infer, normalize, translate, repair, or rewrite any existing field value.\n"
            "Only use NONE for missing fields.\n"
            "Valid states are strictly:\n"
            "1) recipient != NONE and task != NONE and results == NONE\n"
            "2) results != NONE and recipient == NONE and task == NONE\n"
            f"Allowed recipient values are exactly: {executor_options} or NONE.\n"
            "Output raw JSON only. No markdown. No explanation."
        )

        return get_json_parser(
            TaskTransferJSON,
            mode=mode,
            system_prompt=system_prompt,
            enable_direct_parse=True,
            postprocess=lambda result, raw_query: self._task_transfer_postprocess(
                result, raw_query, executor_options
            ),
            llm=ChatOpenAI(model="gpt-4o-2024-11-20"),
        )

    def _output_format_lst2str(self, output_format):
        final_str = 'Your only function is to output a single JSON object specifying the recipient of the task/message and the task/message itself. You can communicate with one of [{}], with the following format:\n'.format(', '.join(self.executor_options))
        for items in output_format:
            final_str += '- To {}, output (JSON): {}. Guideline for the INPUT: {}.\n\n'.format(items['to'][1], json.dumps({"recipient": items['to'][1], "task": "INPUT"}), items['format'])
        final_str += '- When the overall workflow is completed, output: {"results": OUTPUT}. The OUTPUT should be a string that summarizes the final results of the workflow.'
        return final_str 

    def _concat_initial_user_message(self, background, output_format, workflow):
        return '# **Background**\n\n{}\n\n# **Workflow**\n\n{}\n\n# **Delegation Targets & Output Format**\n\n{}'.format(background, workflow, output_format)

    def receive_task(self, task_file_path, sender, task):
        self.last_sender = sender
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_data["current_agent"] = self.name
        messages = [
            SystemMessage(content=self.system_prompt),
            *self._get_chat_history(),
            HumanMessage(content=self._format_message(task))
        ]
        if len(messages) > 100:
            task_data['cur_task_type'] = 'Failed, too much iterations'
            assert False
        if self.use_llm:
            response = self.llm.invoke(messages).content
        else:
            response = "test_agent_call"
        self._save_to_memory(self._format_message(task), response)  # TODO
        if self.use_llm:
            parsed_response = self.task_transfer_parser.invoke({"query": response})
            parsed_response['sender'] = self.name
        else:
            parsed_response = {"sender": self.name, "recipient": "test", "task": "test", "results": "test"}

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'agent next step'
        task_data['cur_task_content'] = parsed_response
        task_data["messages"].append(gen_new_message(task_data))

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def receive_feedback(self, task_file_path, sender, feedback):
        task = 'Feedback from {}: {}'.format(sender, feedback)

        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        task_data["current_agent"] = self.name
        messages = [
            SystemMessage(content=self.system_prompt),
            *self._get_chat_history(),
            HumanMessage(content=self._format_message(task))
        ]
        if len(messages) > 100:
            task_data['cur_task_type'] = 'Failed, too much iterations'
            assert False
        if self.use_llm:
            response = self.llm.invoke(messages).content
        else:
            response = "test_agent_call"
        self._save_to_memory(self._format_message(task), response)  # use response instead of feedback to adapt to the ReAct workflow
        if self.use_llm:
            parsed_response = self.task_transfer_parser.invoke({"query": response})
            parsed_response['sender'] = self.name
        else:
            parsed_response = {"sender": self.name, "recipient": "test", "task": "test", "results": "test"}

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'agent next step'
        task_data['cur_task_content'] = parsed_response
        task_data["messages"].append(gen_new_message(task_data))

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def self_reflection(self, task_file_path, task):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_data["current_agent"] = self.name
        interact_history = '\n'.join(
            f"{'Human to AI Message' if isinstance(item, HumanMessage) else 'AI Response'}: {item.content}" 
            for item in self._get_chat_history()[2:-1]
        )
        messages = [
            SystemMessage(content="You are an experienced chemistry expert."),
            HumanMessage(content="# **Background**\n---{}\n---\n\nHere is the previous interaction history:\n---{}\n--- Your should finish the given task (typically a thinking task) based on the above content.".format(self.background_promt, interact_history)),
            AIMessage(content="I understand! Please give me the task."),
            HumanMessage(content=self._format_message(task))
        ]
        
        if len(messages) > 100:
            task_data['cur_task_type'] = 'Failed, too much iterations'
            assert False
        if self.use_llm:
            response = self.llm.invoke(messages).content
        else:
            response = "test_agent_call"
        # task_data["messages"].append(gen_new_message({"cur_task_type": "self reflection completed", "cur_task_content": {"sender": self.name, "recipient": self.name, 'results': response}}))

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'self reflection completed'
        task_data['cur_task_content'] = {"sender": self.name, "recipient": self.name, 'results': response}
        task_data["messages"].append(gen_new_message(task_data))

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def reflection_completed(self, task_file_path, feedback):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_data["current_agent"] = self.name
        messages = [
            SystemMessage(content=self.system_prompt),
            *self._get_chat_history(),
            HumanMessage(content=self._format_message("Results from Self-reflection:\n {}\n\nNow, you can enter the next round.".format(feedback)))
        ]
        if len(messages) > 100:
            task_data['cur_task_type'] = 'Failed, too much iterations'
            assert False
        if self.use_llm:
            response = self.llm.invoke(messages).content
        else:
            response = "test_agent_call"
        self._save_to_memory(self._format_message("Results from Self-reflection:\n {}".format(response)), response)  # use response instead of feedback to adapt to the ReAct workflow
        if self.use_llm:
            parsed_response = self.task_transfer_parser.invoke({"query": response})
            parsed_response['sender'] = self.name
        else:
            parsed_response = {"sender": self.name, "recipient": "test", "task": "test", "results": "test"}

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'agent next step'
        task_data['cur_task_content'] = parsed_response
        task_data["messages"].append(gen_new_message(task_data))

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)

    def clear_memory_after_done(self):
        agent_manager = AgentManager()
        if agent_manager.agents[self.name]['is_memory_forgot']:
            self.previous_memory.append([])
            for msg in self.memory.chat_memory.messages:
                if isinstance(msg, HumanMessage):
                    self.previous_memory[-1].append({ "type": "human", "content": msg.content })
                else:
                    self.previous_memory[-1].append({ "type": "ai", "content": msg.content })
            self.memory.chat_memory.messages = self.memory.chat_memory.messages[:2]
        else:
            return
    
    def to_next_step(self, task_file_path):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        parsed_response = task_data['cur_task_content']
        if "results" in parsed_response and isinstance(parsed_response["results"], str) and parsed_response["results"] != '' and parsed_response["results"].upper() != 'NONE':
            if self.name == 'ManagerAgent':
                task_data['cur_task_type'] = 'completed'
                task_data['task_status'] = 'completed'
                task_data['final_results'] = parsed_response['results']
                if 'recipient' not in task_data["messages"][-1]["task_content"]:
                    task_data["messages"][-1]["task_content"]["recipient"] = "Human"
                task_data["messages"].append({"role": "assistant", "content": f"C-{datetime.now().strftime('%Y%m%d-%H%M%S')} | The overall workflow is finished!", "time": f"C-{datetime.now().strftime('%Y%m%d-%H%M%S')}", "task_type": "completed", "task_content": "The overall workflow is finished!"})
            else:
                task_data['task_status'] = 'waiting for server process'
                task_data['cur_task_type'] = 'agent send back'
                task_data['cur_task_content'] = {"sender": self.name, "recipient": self.last_sender, 'feedback': parsed_response['results']}
                if 'recipient' not in task_data["messages"][-1]["task_content"]:
                    task_data["messages"][-1]["task_content"]["recipient"] = self.last_sender
                task_data["messages"].append(gen_new_message(task_data))
        else:
            task_data['task_status'] = 'waiting for server process'
            if parsed_response["recipient"].lower().replace('-', '') == 'selfreflection':
                task_data["messages"][-1]["task_content"]["recipient"] = self.name  # NOTE
                task_data['cur_task_type'] = 'self reflection'
                task_data['cur_task_content'] = {"sender": self.name, "recipient": self.name, 'task': parsed_response['task']}
                task_data["messages"].append(gen_new_message(task_data))
            else:
                task_data['cur_task_type'] = 'send task to others'
                task_data['cur_task_content'] = {"sender": self.name, "recipient": parsed_response["recipient"], 'task': parsed_response['task']}
                task_data["messages"].append(gen_new_message(task_data))
        
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)


class DeviceTemplate(ABC):
    def __init__(self) -> None:
        self.use_llm = True

    # def msg2json(self, msg: str) -> Dict:
    #     json_data = self.json_chain.invoke({"query": msg})
    #     return json_data
    @abstractmethod
    def msg2json(self, msg: str) -> Dict:
        pass

    def receive_task(self, task_file_path, sender, task_msg):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'waiting tool or device'
        task_data['cur_task_content'] = {"sender": sender, "recipient": self.__class__.__name__}
        task_data.setdefault("waiting_info", {})
        if self.use_llm:
            parsed_response = self.msg2json(task_msg)
        else:
            parsed_response = json.loads(task_msg) if isinstance(task_msg, str) else task_msg
        task_data["waiting_info"][self.__class__.__name__] = {"sender": sender, 'task': json.dumps(parsed_response), 'results': 'waiting'}

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def get_results(self, task_file_path):
        self.process_locally(task_file_path)

        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        if task_data["waiting_info"][self.__class__.__name__]['results'] != 'waiting':
            self.send_feedback(task_file_path)
    
    def send_feedback(self, task_file_path):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'tool or device send feedback'
        task_data['cur_task_content'] = {"sender": self.__class__.__name__, "recipient": task_data["waiting_info"][self.__class__.__name__]["sender"], 'feedback': task_data["waiting_info"][self.__class__.__name__]['results']}
        task_data["messages"].append(gen_new_message(task_data))
        task_data["waiting_info"].pop(self.__class__.__name__)

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)

    @abstractmethod
    def process_locally(self, task_file_path) -> str:
        pass

    def _load_device_config(self) -> Dict:
        """Load device configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                # Ensure all default keys exist
                for key in self.default_config:
                    if key not in config:
                        config[key] = self.default_config[key]
                return config
            except Exception as e:
                print(f"Error loading device config: {e}")
                return self.default_config
        else:
            # Create default config file
            self._save_device_config(self.default_config)
            return self.default_config

    def _save_device_config(self, config: Dict) -> None:
        """Save device configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving device config: {e}")


class ToolTemplate(ABC):
    def __init__(self) -> None:
        self.use_llm = True

    def msg2json(self, msg: str) -> Dict:
        json_data = self.json_chain.invoke({"query": msg})
        return json_data

    def receive_task(self, task_file_path, sender, task_msg):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'waiting tool or device'
        task_data['cur_task_content'] = {"sender": sender, "recipient": self.__class__.__name__}
        task_data.setdefault("waiting_info", {})
        if self.use_llm:
            parsed_response = self.msg2json(task_msg)
        else:
            parsed_response = json.loads(task_msg) if isinstance(task_msg, str) else task_msg
        task_data["waiting_info"][self.__class__.__name__] = {"sender": sender, 'task': json.dumps(parsed_response), 'results': 'waiting'}

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def get_results(self, task_file_path):
        self.process_locally(task_file_path)

        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        if task_data["waiting_info"][self.__class__.__name__]['results'] != 'waiting':
            self.send_feedback(task_file_path)
    
    def send_feedback(self, task_file_path):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'tool or device send feedback'
        task_data['cur_task_content'] = {"sender": self.__class__.__name__, "recipient": task_data["waiting_info"][self.__class__.__name__]["sender"], 'feedback': task_data["waiting_info"][self.__class__.__name__]['results']}
        task_data["messages"].append(gen_new_message(task_data))
        task_data["waiting_info"].pop(self.__class__.__name__)

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)

    @abstractmethod
    def process_locally(self, task_file_path) -> str:
        pass

    def _load_tool_config(self) -> Dict:
        """Load tool configuration from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                # Ensure all default keys exist
                for key in self.default_config:
                    if key not in config:
                        config[key] = self.default_config[key]
                return config
            except Exception as e:
                print(f"Error loading tool config: {e}")
                return self.default_config
        else:
            # Create default config file
            self._save_tool_config(self.default_config)
            return self.default_config

    def _save_tool_config(self, config: Dict) -> None:
        """Save tool configuration to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Error saving tool config: {e}")


class Human():
    def receive_task(self, task_file_path, sender, task_msg):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)

        task_data['task_status'] = 'paused'
        task_data['cur_task_type'] = 'waiting tool or device'
        task_data['cur_task_content'] = {"sender": sender, "recipient": self.__class__.__name__}
        task_data.setdefault("waiting_info", {})
        task_data["waiting_info"][self.__class__.__name__] = {"sender": sender, 'task': str(task_msg), 'results': 'waiting'}

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def get_results(self, task_file_path):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        if task_data["waiting_info"][self.__class__.__name__]['results'] != 'waiting':
            self.send_feedback(task_file_path)
    
    def send_feedback(self, task_file_path):
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        
        task_data['task_status'] = 'waiting for server process'
        task_data['cur_task_type'] = 'tool or device send feedback'
        task_data['cur_task_content'] = {"sender": self.__class__.__name__, "recipient": task_data["waiting_info"][self.__class__.__name__]["sender"], 'feedback': task_data["waiting_info"][self.__class__.__name__]['results']}
        task_data["messages"].append(gen_new_message(task_data))
        task_data["waiting_info"][self.__class__.__name__] = {'task': 'no pending task'}

        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
