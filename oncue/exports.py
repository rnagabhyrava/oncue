"""Download complete history and original output without the preview size limit."""
import json
import tempfile
import zipfile
from pathlib import Path


def archive(store, slug):
    job=store.job(slug,include_archived=True)
    if not job:raise ValueError('Task not found')
    result=tempfile.TemporaryFile()
    try:
        with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED) as target:
            messages=[dict(r) for r in store.connection.execute('SELECT * FROM messages WHERE job_id=? ORDER BY id',(job['id'],))]
            runs=[dict(r) for r in store.connection.execute('SELECT * FROM runs WHERE job_id=? ORDER BY id',(job['id'],))]
            root=(store.path.parent/'runs').resolve()
            for run in runs:
                for key,extension in (('response_path','response.txt'),('output_path','log')):
                    if not run[key]:continue
                    source=Path(run[key]).resolve()
                    if not source.is_relative_to(root):raise ValueError('Output is outside scheduler storage')
                    name=f"runs/{run['id']}.{extension}"
                    if source.is_file():target.write(source,name)
                    run[key]=name
                run.pop('config_snapshot',None)
            target.writestr('history.json',json.dumps({'title':job['title'],'slug':slug,'messages':messages,'runs':runs},indent=2))
        result.seek(0)
        return result
    except Exception:
        result.close()
        raise
