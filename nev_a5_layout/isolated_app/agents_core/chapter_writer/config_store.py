from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile

from chapter_writer.config import Settings

DEFAULT_CONFIG_PATH=Path.home()/"Library"/"Application Support"/"ChapterWriter"/"config.json"


class LocalConfigStore:
    def __init__(self,path:Path|None=None):
        configured=os.getenv("CHAPTER_WRITER_CONFIG_PATH","").strip()
        self.path=path or (Path(configured).expanduser() if configured else DEFAULT_CONFIG_PATH)
    @property
    def exists(self)->bool: return self.path.is_file()
    def load(self,fallback:Settings)->Settings:
        if not self.exists: return fallback
        try: payload=json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError): return fallback
        values={k:str(payload[k]).strip() for k in ("llm_api_key","llm_base_url","llm_model") if payload.get(k)}
        return replace(fallback,**values)
    def save(self,settings:Settings)->None:
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700); os.chmod(self.path.parent,0o700)
        fd,name=tempfile.mkstemp(prefix="config-",suffix=".tmp",dir=self.path.parent)
        temp=Path(name)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle:
                json.dump({"llm_api_key":settings.llm_api_key,"llm_base_url":settings.llm_base_url,"llm_model":settings.llm_model},handle,ensure_ascii=False,indent=2); handle.write("\n")
            os.chmod(temp,0o600); os.replace(temp,self.path); os.chmod(self.path,0o600)
        finally:
            if temp.exists(): temp.unlink()

