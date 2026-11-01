from typing import Dict, List
from pydantic import Field, create_model
import os
import re
import json
from langchain_openai import ChatOpenAI

from chem_main.template import ToolTemplate
from chem_main.utils import get_json_parser
from chem_main.tools.HandbookSearchHelper import HandbookRAGConfig, get_handbook_rag_service


class HandbookSearchTool(ToolTemplate):
    def __init__(self) -> None:
        super().__init__()
        self.json_chain = get_json_parser(create_model(
            "HandbookSearchToolJSON",
            query=(str, Field(..., description="The specific search query or topic to look up in the handbook")),
        ))
        self.decompose_chain = get_json_parser(
            create_model(
                "HandbookSearchToolDecomposeJSON",
                queries=(List[str], Field(..., description="A list of standalone atomic search questions")),
            )
        )
        self.llm = ChatOpenAI(model='gpt-5', base_url=os.environ.get("OPENAI_API_BASE"))
        
        base_dir = "src/chem_main/tools/config/HandbookSearchHelper"
        self.rag_config = HandbookRAGConfig(
            pdf_dir=os.path.join(base_dir, "raw_files"),
            cache_dir=os.path.join(base_dir, "cache"),
            catalog_json=os.path.join(base_dir, "raw_files", "pdf_catalog.json"),
            model='gpt-5',
            embedding_model=os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small"),
            api_key=os.environ.get("OPENAI_API_KEY"),
            api_base=os.environ.get("OPENAI_API_BASE"),
            llama_cloud_api_key=os.environ.get("LLAMA_CLOUD_API_KEY"),
            parse_tier="agentic",
            parse_version="latest",
            rebuild=False,
            chunk_size=900,
            chunk_overlap=120,
            similarity_top_k=4,
            show_trajectory=False,
        )

    def msg2json(self, msg: str) -> Dict:
        json_data = self.json_chain.invoke({"query": msg})

        #  NOTE: postprocessing

        return json_data

    def _normalize_query_text(self, text: str) -> str:
        if not isinstance(text, str):
            return ""
        text = text.strip()
        text = re.sub(r"\s+", " ", text)
        text = text.strip(" ,;")
        if not text:
            return ""
        if not re.search(r"[?.!]$", text):
            text += "?"
        return text

    def _deduplicate_queries(self, queries: List[str]) -> List[str]:
        seen = set()
        out = []
        for q in queries:
            nq = self._normalize_query_text(q)
            key = nq.casefold()
            if nq and key not in seen:
                seen.add(key)
                out.append(nq)
        return out

    def _decompose_query(self, rag_query: str) -> List[str]:
        rag_query = (rag_query or "").strip()
        if not rag_query:
            raise ValueError("Empty query is not allowed")

        prompt = f"""
You are a chemistry handbook retrieval query decomposition engine.

The downstream retrieval service only accepts ONE standalone question at a time.

Your task:
- Split the user's input into multiple standalone sub-queries only when needed.
- If the input is already atomic, keep it as a single query.
- Preserve chemistry entities, formulas, molecule names, bond labels, units, symbols, abbreviations, and terminology.
- Do not answer the questions.
- Do not add explanations.
- Each sub-query must be understandable independently.
- Output must be valid JSON with a single field:
  {{"queries": ["...", "..."]}}

Examples:
Input:
C–H bond dissociation energy (BDE) for the α-C–H bond in 1,4-dioxane, and the BDEs for H–Cl and H–Br
Output:
{{"queries": [
  "What is the C–H bond dissociation energy (BDE) for the α-C–H bond in "1,4-dioxane"?",
  "What is the bond dissociation energy (BDE) for "H–Cl"?",
  "What is the bond dissociation energy (BDE) for "H–Br"?"
]}}

Input:
Find the C-H BDE for 1,4-dioxane
Output:
{{"queries": [
  "Find the C-H BDE for "1,4-dioxane"."
]}}

Now decompose this input:
{rag_query}
""".strip()

        raw = self.llm.invoke(prompt)
        raw_text = raw.content if hasattr(raw, "content") else str(raw)
        data = self.decompose_chain.invoke(raw_text)
        queries = data.get("queries", [])

        if not isinstance(queries, list) or not queries:
            raise ValueError("Invalid decomposition result: 'queries' must be a non-empty list")

        queries = self._deduplicate_queries(queries)
        if not queries:
            raise ValueError("Invalid decomposition result: empty query list after normalization")

        return queries

    def _run_single_rag_query(self, query: str) -> str:
        service = get_handbook_rag_service(self.rag_config)
        return service.query(query)

    def _run_rag_query(self, query: str) -> str:
        sub_queries = self._decompose_query(query)
        outputs = []

        for sub_query in sub_queries:
            sub_res = self._run_single_rag_query(sub_query)
            outputs.append(str(sub_res).strip())

        return "\n".join(outputs)
    
    def process_locally(self, task_file_path) -> str:
        with open(task_file_path, 'r', encoding='utf-8') as f:
            task_data = json.load(f)
        task_send_flag = task_data["waiting_info"][self.__class__.__name__].get("task_send_flag", False)
        tool_input_task = task_data["waiting_info"][self.__class__.__name__]['task']
        tool_input_task = json.loads(tool_input_task) if isinstance(tool_input_task, str) else tool_input_task
        
        if task_send_flag:
            rag_query = tool_input_task['query']
            res = self._run_rag_query(rag_query)
        else:
            res = "waiting"
            task_data["waiting_info"][self.__class__.__name__]['task_send_flag'] = True

        task_data["waiting_info"][self.__class__.__name__]['results'] = res
        with open(task_file_path, 'w', encoding='utf-8') as f:
            json.dump(task_data, f, indent=2)
    
    def unit_test(self):
        query = 'C–H bond dissociation energy (BDE) for the α-C–H bond in 1,4-dioxane, and the BDEs for Cl–H and Br–H'
        self._run_rag_query(query)

if __name__ == "__main__":
    tool = HandbookSearchTool()
    tool.unit_test()
