import json
import os
from typing import Any

class JsonStorage:
    def __init__(self, filepath: str):
        self.filepath = filepath

    def load(self, default: Any = None) -> Any:
        if default is None:
            default = {}
            
        if not os.path.exists(self.filepath):
            return default
            
        try:
            with open(self.filepath, 'r') as f:
                content = f.read()
                if not content:
                    return default
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return default

    def save(self, data: Any):
        with open(self.filepath, 'w') as f:
            json.dump(data, f, indent=4)
