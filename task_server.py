import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import json
import os
import logging
import importlib
import time
import traceback

from chem_main.agent_manager import AgentManager


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("history_files/task_server.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class TaskMonitoringServer:
    def __init__(self, tasks_directory="history_files/tasks", scan_interval=3):
        """
        Initialize the Task Monitoring Server.
        
        Args:
            tasks_directory (str): Root directory containing task subdirectories
            scan_interval (int): Time between scans in seconds
        """
        self.tasks_directory = tasks_directory
        self.scan_interval = scan_interval
        self.running = False
        logger.info(f"Server initialized. Monitoring directory: {tasks_directory}")
        
    def start(self):
        """Start the server's monitoring loop."""
        self.running = True
        logger.info("Server started")
        
        try:
            while self.running:
                self.scan_tasks()
                time.sleep(self.scan_interval)
        except KeyboardInterrupt:
            logger.info("Server stopped by user")
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            logger.error(traceback.format_exc())
        finally:
            self.running = False
            
    def stop(self):
        """Stop the server."""
        self.running = False
        logger.info("Server stopped")
    
    def scan_tasks(self):
        """Scan all subdirectories for task.json files and process them."""
        # logger.info(f"Scanning for tasks in {self.tasks_directory}")
        
        # Check if the directory exists
        if not os.path.exists(self.tasks_directory):
            logger.error(f"Tasks directory {self.tasks_directory} does not exist")
            return
            
        try:
            # Get all subdirectories
            subdirectories = [d for d in os.listdir(self.tasks_directory) 
                             if os.path.isdir(os.path.join(self.tasks_directory, d))]
            
            for subdir in subdirectories:
                task_path = os.path.join(self.tasks_directory, subdir, "task.json")
                
                # Check if the task.json file exists
                if os.path.exists(task_path):
                    self.process_task_file(task_path)
                    
        except Exception as e:
            logger.error(f"Error scanning tasks: {str(e)}")
            logger.error(traceback.format_exc())
    
    def process_task_file(self, task_file_path):
        """
        Process a single task.json file.
        
        Args:
            task_file_path (str): Path to the task.json file
        """
        # try:
        with open(task_file_path, 'r') as file:
            task_data = json.load(file)
            
        # Check if the task is waiting for server process
        if task_data.get("task_status") == "waiting for server process":
            task_id = task_data.get("task_name", "unknown")
            logger.info(f"Processing task {task_id} in {task_file_path}")
            
            # Process the task
            self.process_waiting_task(task_data, task_file_path)
    
    def _get_object(self, task_file_path, cls_name, **kwargs):
        """Get an object by cls_name."""
        agent_history_path = os.path.join(os.path.dirname(task_file_path), 'all_agent_history.json')
        if not os.path.exists(agent_history_path):
            with open(agent_history_path, 'w') as fp:
                json.dump({}, fp)

        with open(agent_history_path, 'r') as fp:
            name2agent_history = json.load(fp)
        
        if cls_name.endswith('Agent'):
            import chem_main.template
            importlib.reload(chem_main.template)
            agent_manager = AgentManager()
            cur_agent = chem_main.template.WorkerAgent(agent_name=cls_name, system_prompt=agent_manager.agents[cls_name]['system_prompt'], background=agent_manager.agents[cls_name]['background'], output_format=agent_manager.agents[cls_name]['output_format'], workflow=agent_manager.agents[cls_name]['workflow'], model_name=agent_manager.agents[cls_name]['model'], temperature=agent_manager.agents[cls_name]['temperature'], api_key=agent_manager.agents[cls_name]['api_key'], api_url=agent_manager.agents[cls_name]['api_url'])
            if cls_name  in name2agent_history:
                cur_agent.import_memory(name2agent_history[cls_name])
            return cur_agent
        elif cls_name.endswith('Tool'):
            import chem_main.tools
            importlib.reload(chem_main.tools)
            return getattr(chem_main.tools, cls_name)(**kwargs)
        elif cls_name.endswith('Device'):
            import chem_main.devices
            importlib.reload(chem_main.devices)
            return getattr(chem_main.devices, cls_name)(**kwargs)
        elif cls_name.endswith('Human'):
            import chem_main.template
            importlib.reload(chem_main.template)
            return getattr(chem_main.template, cls_name)(**kwargs)
        else:
            raise ValueError(f"Unknown class name: {cls_name}")

    def _save_object(self, task_file_path, cls_name, obj):
        """Save an object by cls_name."""
        agent_history_path = os.path.join(os.path.dirname(task_file_path), 'all_agent_history.json')
        if not os.path.exists(agent_history_path):
            with open(agent_history_path, 'w') as fp:
                json.dump({}, fp, indent=2)

        with open(agent_history_path, 'r') as fp:
            name2agent_history = json.load(fp)
        
        if cls_name.endswith('Agent'):
            name2agent_history[cls_name] = obj.export_memory()
            with open(agent_history_path, 'w') as fp:
                json.dump(name2agent_history, fp, indent=2)
    
    def process_waiting_task(self, task_data, task_file_path):
        """
        Process a task that is waiting for server processing.
        
        Args:
            task_data (dict): The task data from the JSON file
            task_file_path (str): Path to the task.json file for updating
        """
        cur_task_type = task_data.get("cur_task_type")
        cur_task_content = task_data.get("cur_task_content")

        # print(cur_task_type, cur_task_content)
        if cur_task_type == "send task to others":
            target_obj = self._get_object(task_file_path, cur_task_content['recipient'])
            target_obj.receive_task(task_file_path, cur_task_content['sender'], cur_task_content['task'])
            if cur_task_content['sender'].endswith('Agent'):
                src_obj = self._get_object(task_file_path, cur_task_content['sender'])
                src_obj.memory.chat_memory.messages[-1].content = json.dumps({"recipient": cur_task_content['recipient'], "task": cur_task_content['task'], "results": "NONE"})
                self._save_object(task_file_path, cur_task_content['sender'], src_obj)
            self._save_object(task_file_path, cur_task_content['recipient'], target_obj)
        elif cur_task_type == "self reflection":
            target_obj = self._get_object(task_file_path, cur_task_content['sender'])
            target_obj.self_reflection(task_file_path, cur_task_content['task'])
            self._save_object(task_file_path, cur_task_content['sender'], target_obj)
        elif cur_task_type == "agent send back":
            target_obj = self._get_object(task_file_path, cur_task_content['recipient'])
            target_obj.receive_feedback(task_file_path, cur_task_content['sender'], cur_task_content['feedback'])
            if cur_task_content['sender'].endswith('Agent'):
                src_obj = self._get_object(task_file_path, cur_task_content['sender'])
                src_obj.memory.chat_memory.messages[-1].content = json.dumps({"recipient": "NONE", "task": "NONE", "results": cur_task_content['feedback']})
                src_obj.clear_memory_after_done()
                self._save_object(task_file_path, cur_task_content['sender'], src_obj)
            self._save_object(task_file_path, cur_task_content['recipient'], target_obj)
        elif cur_task_type == "waiting tool or device":
            target_obj = self._get_object(task_file_path, cur_task_content["recipient"])
            if cur_task_content['sender'].endswith('Agent'):
                src_obj = self._get_object(task_file_path, cur_task_content['sender'])
                src_obj.memory.chat_memory.messages[-1].content = json.dumps({"recipient": cur_task_content["recipient"], "task": task_data["waiting_info"][cur_task_content["recipient"]]['task'], "results": "NONE"})
                self._save_object(task_file_path, cur_task_content['sender'], src_obj)
            target_obj.get_results(task_file_path)
            self._save_object(task_file_path, cur_task_content["recipient"], target_obj)
        elif cur_task_type == "tool or device send feedback":
            target_obj = self._get_object(task_file_path, cur_task_content['recipient'])
            target_obj.receive_feedback(task_file_path, cur_task_content['sender'], cur_task_content['feedback'])
            self._save_object(task_file_path, cur_task_content['recipient'], target_obj)
        elif cur_task_type == "self reflection completed":  # NOTE
            target_obj = self._get_object(task_file_path, cur_task_content['recipient'])
            target_obj.reflection_completed(task_file_path, cur_task_content['results'])
            self._save_object(task_file_path, cur_task_content['recipient'], target_obj)
        elif cur_task_type == "agent next step":
            target_obj = self._get_object(task_file_path, cur_task_content['sender'])
            target_obj.to_next_step(task_file_path)
            self._save_object(task_file_path, cur_task_content['sender'], target_obj)
        elif cur_task_type == "none":
            pass
        else:
            assert False, "Unknown task type"
        
        # task_data.update({ "cur_task_type": 'none', "cur_task_content": {}})
        # self.update_task_file(task_data, task_file_path)
    
    def update_task_file(self, task_data, task_file_path):
        """
        Update the task.json file with new data.
        
        Args:
            task_data (dict): Updated task data
            task_file_path (str): Path to the task.json file
        """
        try:
            with open(task_file_path, 'w') as file:
                json.dump(task_data, file, indent=2)
        except Exception as e:
            logger.error(f"Error updating task file {task_file_path}: {str(e)}")


if __name__ == "__main__":
    server = TaskMonitoringServer()
    server.start()
