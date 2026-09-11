import sys, os, importlib.util

class DirectFinder:
    def find_spec(self, fullname, path, target=None):
        search_paths = sys.path if path is None else path
        mod_name = fullname.split('.')[-1]
        for p in search_paths:
            pkg_init = os.path.join(p, mod_name, '__init__.py')
            if os.path.exists(pkg_init):
                return importlib.util.spec_from_file_location(fullname, pkg_init, submodule_search_locations=[os.path.join(p, mod_name)])
            file_cand = os.path.join(p, mod_name + '.py')
            if os.path.exists(file_cand):
                return importlib.util.spec_from_file_location(fullname, file_cand)
        return None

sys.meta_path.insert(0, DirectFinder())
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn
from app.main import app
from app.config import settings

if __name__ == "__main__":
    print(f"Starting {settings.APP_NAME} on http://{settings.HOST}:{settings.PORT}")
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
