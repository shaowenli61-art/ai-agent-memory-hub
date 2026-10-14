import json
from pathlib import Path
from memory_hub.local_server import stop
settings=json.loads((Path(__file__).resolve().parent/'local-settings.json').read_text(encoding='utf-8'))
if settings['mode']=='demo':
    print('体验服务请在其控制台按 Ctrl+C 停止。')
else:
    print(json.dumps(stop(Path(settings['vault'])),ensure_ascii=False))
