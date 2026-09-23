from __future__ import annotations
from dataclasses import replace
import json,os,tempfile
from pathlib import Path
from report_fusion.config import Settings

DEFAULT_CONFIG_PATH=Path.home()/"Library"/"Application Support"/"ReportFusion"/"config.json"
class LocalConfigStore:
    def __init__(self,path:Path|None=None):
        configured=os.getenv("REPORT_FUSION_CONFIG_PATH","").strip(); self.path=path or (Path(configured).expanduser() if configured else DEFAULT_CONFIG_PATH)
    @property
    def exists(self): return self.path.is_file()
    def load(self,fallback:Settings)->Settings:
        if not self.exists:return fallback
        try:data=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError):return fallback
        return replace(fallback,**{k:str(data[k]).strip() for k in ("llm_api_key","llm_base_url","llm_model") if data.get(k)})
    def save(self,settings:Settings):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(self.path.parent,0o700);fd,name=tempfile.mkstemp(dir=self.path.parent,prefix="config-",suffix=".tmp");tmp=Path(name)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as f:json.dump({"llm_api_key":settings.llm_api_key,"llm_base_url":settings.llm_base_url,"llm_model":settings.llm_model},f,ensure_ascii=False,indent=2);f.write("\n")
            os.chmod(tmp,0o600);os.replace(tmp,self.path);os.chmod(self.path,0o600)
        finally:
            if tmp.exists():tmp.unlink()

