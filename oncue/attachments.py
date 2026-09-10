"""Private text attachments and deterministic run-context snapshots."""
import base64
import json
import os
from pathlib import Path

MAX_FILE=64*1024
MAX_CONTEXT=128*1024

def _owner(store, owner_type, owner):
    if owner_type=='project':
        row=store.connection.execute('SELECT id FROM task_projects WHERE id=?',(owner,)).fetchone()
    elif owner_type=='task':
        row=store.connection.execute('SELECT id FROM jobs WHERE slug=?',(owner,)).fetchone()
        if row: owner=row['id']
    else: raise ValueError('Unknown attachment owner')
    if not row: raise ValueError('Attachment owner not found')
    return int(owner)

def list_attachments(store, owner_type, owner):
    owner=_owner(store,owner_type,owner)
    return [dict(r) for r in store.connection.execute("SELECT id,name,version,size,created_at FROM attachments WHERE owner_type=? AND owner_id=? AND deleted_at IS NULL AND replaced_by IS NULL ORDER BY name",(owner_type,owner))]

def upload(store, owner_type, owner, name, content_b64):
    owner=_owner(store,owner_type,owner)
    name=Path(str(name)).name
    if not name.lower().endswith(('.txt','.md')): raise ValueError('Only .txt and .md files are supported')
    if not name or len(name)>255: raise ValueError('Invalid attachment name')
    try: content=base64.b64decode(content_b64,validate=True)
    except Exception as error: raise ValueError('Attachment content must be base64') from error
    if len(content)>MAX_FILE: raise ValueError('Attachments must be at most 64 KiB')
    try: content.decode('utf-8')
    except UnicodeDecodeError as error: raise ValueError('Attachments must be UTF-8 text') from error
    total=store.connection.execute("SELECT COALESCE(SUM(size),0) FROM attachments WHERE owner_type=? AND owner_id=? AND deleted_at IS NULL AND replaced_by IS NULL",(owner_type,owner)).fetchone()[0]
    if total+len(content)>MAX_CONTEXT: raise ValueError('Attachments for this item exceed the 128 KiB context limit')
    old=store.connection.execute("SELECT * FROM attachments WHERE owner_type=? AND owner_id=? AND name=? AND deleted_at IS NULL AND replaced_by IS NULL",(owner_type,owner,name)).fetchone()
    version=(old['version']+1) if old else 1
    root=store.path.parent/'attachments'/owner_type/str(owner);root.mkdir(parents=True,exist_ok=True,mode=0o700)
    target=root/(str(version)+'-'+name); target.write_bytes(content);os.chmod(target,0o600)
    cur=store.connection.execute('INSERT INTO attachments(owner_type,owner_id,name,version,path,size) VALUES (?,?,?,?,?,?)',(owner_type,owner,name,version,str(target.resolve()),len(content)))
    if old: store.connection.execute('UPDATE attachments SET replaced_by=? WHERE id=?',(cur.lastrowid,old['id']))
    store.connection.commit();return cur.lastrowid

def remove(store, attachment_id):
    cur=store.connection.execute('UPDATE attachments SET deleted_at=CURRENT_TIMESTAMP WHERE id=? AND deleted_at IS NULL',(attachment_id,));store.connection.commit()
    if not cur.rowcount: raise ValueError('Attachment not found')

def read(store, attachment_id):
    row=store.connection.execute('SELECT * FROM attachments WHERE id=?',(attachment_id,)).fetchone()
    if not row: raise ValueError('Attachment not found')
    root=(store.path.parent/'attachments').resolve(); path=Path(row['path']).resolve()
    if not path.is_relative_to(root): raise ValueError('Attachment is outside storage')
    return row['name'],path.read_bytes()

def context_snapshot(store, job):
    project_id=job.get('task_project_id') if isinstance(job,dict) else job['task_project_id']
    parts=[]; total=0
    if project_id:
        project=store.connection.execute('SELECT name,instructions FROM task_projects WHERE id=?',(project_id,)).fetchone()
        if project and project['instructions'].strip(): parts.append(('Project instructions',project['instructions']))
        owners=[('project',project_id)]
    else: owners=[]
    owners.append(('task',job['id']))
    for typ,oid in owners:
        for row in store.connection.execute("SELECT * FROM attachments WHERE owner_type=? AND owner_id=? AND deleted_at IS NULL AND replaced_by IS NULL ORDER BY id",(typ,oid)):
            content=Path(row['path']).read_text(encoding='utf-8')
            total+=len(content.encode())
            if total>MAX_CONTEXT: raise ValueError('Attached reference material exceeds the 128 KiB context limit')
            parts.append((f'Reference file: {row["name"]}',content))
    return '\n\n'.join(f'[{label}]\n{text}' for label,text in parts)

def snapshot_run(store, job, run_id):
    row=store.connection.execute('SELECT config_snapshot FROM runs WHERE id=?',(run_id,)).fetchone()
    if row['config_snapshot']: return json.loads(row['config_snapshot'])
    value=dict(job); value['_reference_context']=context_snapshot(store,value)
    store.connection.execute('UPDATE runs SET config_snapshot=? WHERE id=?',(json.dumps(value),run_id));store.connection.commit();return value
