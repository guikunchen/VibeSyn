import json
import os
from typing import Dict


class AgentManager:
    def __init__(self, storage_path: str = "src/chem_main/agents.json"):
        self.storage_path = storage_path
        self.agents = self._load_agents()

    def _load_agents(self) -> Dict:
        if not os.path.exists(self.storage_path):
            default_agents = {
                "ManagerAgent": {
                    "system_prompt": "",
                    "enabled": True,
                    "model": "glm-4-plus",
                    "temperature": 0.5,
                    "background": "",
                    "output_format": [],
                    "workflow": "",
                    "initial_assistant_message": "",
                    "api_key": "",
                    "api_url": ""
                }
            }
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(default_agents, f, ensure_ascii=False, indent=2)
            return default_agents
        
        with open(self.storage_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def _save_agents(self, agents: Dict) -> None:
        with open(self.storage_path, 'w', encoding='utf-8') as f:
            json.dump(agents, f, ensure_ascii=False, indent=2)

    def get_all_agents(self) -> Dict:
        return self.agents

    def add_agent(self, name: str, is_memory_forgot: bool, system_prompt: str,
                  model: str = "glm-4-plus", temperature: float = 0.5,
                  background: str = "", output_format: list = [], workflow: str = "",
                  initial_assistant_message: str = "", api_key: str = "", api_url: str = "") -> None:
        if name in self.agents:
            raise ValueError(f"Agent '{name}' already exists")
        
        self.agents[name] = {
            "is_memory_forgot": is_memory_forgot,
            "system_prompt": system_prompt,
            "enabled": True,
            "model": model,
            "temperature": temperature,
            "background": background,
            "output_format": output_format,
            "workflow": workflow,
            "initial_assistant_message": initial_assistant_message,
            "api_key": api_key,
            "api_url": api_url
        }
        self._save_agents(self.agents)

    def update_agent(self, name: str, is_memory_forgot: bool = None, 
                    system_prompt: str = None, enabled: bool = None,
                    model: str = None, temperature: float = None, 
                    background: str = None, output_format: list = None,
                    workflow: str = None, initial_assistant_message: str = None, 
                    api_key: str = None, api_url: str = None) -> None:  # NOTE, need set to None by default
        if name not in self.agents:
            raise ValueError(f"Agent '{name}' does not exist")
        
        updates = [
            ("is_memory_forgot", is_memory_forgot),
            ("system_prompt", system_prompt),
            ("enabled", enabled),
            ("model", model),
            ("temperature", temperature),
            ("background", background),
            ("output_format", output_format),
            ("workflow", workflow),
            ("initial_assistant_message", initial_assistant_message),
            ("api_key", api_key),
            ("api_url", api_url)
        ]
        
        for field, value in updates:
            if value is not None:
                self.agents[name][field] = value
                
        self._save_agents(self.agents)

    def delete_agent(self, name: str) -> None:
        if name not in self.agents:
            raise ValueError(f"Agent '{name}' does not exist")
        
        del self.agents[name]
        self._save_agents(self.agents)

    def get_enabled_agents(self) -> Dict:
        return {name: data for name, data in self.agents.items() 
                if data["enabled"]}
