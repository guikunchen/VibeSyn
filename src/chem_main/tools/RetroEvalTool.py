from typing import Dict
from pydantic import Field, create_model
import os
import json
from langchain_openai import ChatOpenAI

from chem_main.template import ToolTemplate
from chem_main.utils import get_json_parser


class RetroEvalTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "RetroEvalToolJSON",
            folder=(str, Field(..., description="the folder containing retrosynthesis paths")),
        ))
        # self.ana_chain = get_json_parser(create_model(
        #     "SummaryJSON",
        #     safety=(str, Field(..., description="Analysis summary about the the retrosynthesis path")),
        # ))
        # self.choose_chain = get_json_parser(create_model(
        #     "ChooseJSON",
        #     selected_path=(List[str], Field(..., description="The selected retrosynthesis paths that match the criteria, e.g., [\"Path 3\", \"Path 7\", \"Path 15\"]."))
        # ))
        self.llm = ChatOpenAI(model='o3-2025-04-16', base_url=os.environ.get("OPENAI_API_BASE"))

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
            path_ana_results = os.path.join('history_files', 'tasks', task_data['task_name'],tool_input_task['folder'], 'analysis_results.json')
            if os.path.exists(path_ana_results):
                with open(path_ana_results, 'r', encoding='utf-8') as f:
                    ana_results = json.load(f)
            else:
                ana_results = []
                for i in range(10):
                    with open(os.path.join('history_files', 'tasks', task_data['task_name'], tool_input_task['folder'], f'path{i+1}.json'), 'r') as f:
                        data = json.load(f)
                    analysis_result = self.analysis_llm(data)
                    print(analysis_result)
                    # analysis_json = self.ana_chain.invoke({"query": analysis_result})
                    # print(analysis_json)

                    formatted = f"Path {i+1}:\n{analysis_result.content.strip()}"
                    ana_results.append(formatted)

                    with open(path_ana_results, 'w', encoding='utf-8') as f:
                        json.dump(ana_results, f, indent=4)
            res = "\n\n".join(ana_results)
        else:
            res = "waiting"
            task_data["waiting_info"][self.__class__.__name__]['task_send_flag'] = True

        task_data["waiting_info"][self.__class__.__name__]['results'] = res
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def analysis_llm(self, data):
        """Use LLM to analyze retrosynthesis path"""
        data = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else data
        analysis_prompt = f"""Analyze the retrosynthesis path provided in the JSON format below:
{data}

The JSON contains multiple steps (the synthesis of molecules is performed in ascending order of step 1, step 2, step 3). Each step includes Product and Reactants, their SMILES, names, molecular weights, and price (in USD/unit). A price value of "N.A." means no specific price available.

Please evaluate the retrosynthesis path, provide concise but professional overall assessment (100-200 words is enough):
Your evaluation must explicitly consider the following criteria:
- **Safety / Practical Feasibility**: Ensure the path avoids hazardous reagents such as cyanides, aluminum chloride (AlCl₃), phosgene (COCl₂), trimethylaluminum (AlMe₃), hydrogen fluoride (HF), phosphorus chlorides (e.g., POCl₃, PCl₃), heavy metal oxidants (e.g., CrO₃, K₂Cr₂O₇), organotin compounds (e.g., Bu₃SnH), and highly reactive organolithium reagents (e.g., n-BuLi, MeLi). Ensure the path avoids reaction conditions with low yield (lower than 30%).
- **Functional group compatibility / Competitive reactive sites**: In each step, identify all reactive functional groups that may compete as potential reaction sites (e.g., free carboxyl, hydroxyl, amino, carbonate, or other reactive moieties) within the reactants.
- **Retrosynthetic logic**: Comment on whether the overall disconnection logic is chemically reasonable, classical, and structurally sound. Note whether the synthetic sequence appears overly complex relative to the target molecule.
- **Economic feasibility**: The path should be economical. Prefer routes that minimize expensive intermediates and high E-factor burden when possible. Penalize routes that rely heavily on reactants costing more than 15-20 USD per unit.
- **Output requirement**: Provide ONE integrated, professional overall evaluation paragraph. No bullet points. No stepwise commentary.
"""
        
        response = self.llm.invoke(analysis_prompt)
        return response
    
    def unit_test(self):
        with open('/home/cgk_cj/chem_agents/v0/history_files/tasks/T-20251228-222707-Peptide-1228-1/resources/RetroDesTool/Execution_01/path2.json', 'r') as f:
            path_json_data = json.load(f)
        ana_results = []
        for data in [path_json_data]:
            analysis_result = self.analysis_llm(data)
            print(analysis_result)
            # analysis_json = self.ana_chain.invoke({"query": analysis_result})
            # print(analysis_json)
            ana_results.append(analysis_result)


if __name__ == "__main__":
    tool = RetroEvalTool()
    tool.unit_test()
    # tool.process_locally('/path/to/task_file.json')  # Uncomment to process a task file locally
