#!/usr/bin/env python3
"""Build a Linux x86_64 folder bundle with Python and both native AI runtimes.
Build prerequisites: Python 3.11+, PyInstaller, npm. Run from the repository root.
"""
import argparse
import os
import platform
import shutil
import subprocess
import tarfile
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('--runtime-prefix',type=Path,help='Reuse an npm prefix with pinned packages installed')
args=parser.parse_args()
if platform.system()!='Linux' or platform.machine()!='x86_64':
    raise SystemExit('This bundle target currently supports Linux x86_64 only.')
root=Path(__file__).resolve().parent.parent
os.chdir(root)
prefix=args.runtime_prefix or root/'build/provider-packages'
if not args.runtime_prefix:
    subprocess.run(['npm','install','--prefix',str(prefix),'@openai/codex@0.153.4','opencode-ai@1.18.30','--ignore-scripts','--no-audit','--no-fund'],check=True)
subprocess.run([__import__('sys').executable,'-m','PyInstaller','--noconfirm','--clean','--name','oncue','--paths',str(root),'--collect-all','oncue','--add-data',str(root/'oncue/static')+':oncue/static','--specpath','build','scripts/portable_entry.py'],check=True)
bundle=root/'dist/oncue'
runtimes=bundle/'runtimes';runtimes.mkdir(exist_ok=True)
vendor=prefix/'node_modules/@openai/codex-linux-x64/vendor/x86_64-unknown-linux-musl'
shutil.copytree(vendor,runtimes/'codex-native',dirs_exist_ok=True)
link=runtimes/'codex'
if link.is_symlink():link.unlink()
link.symlink_to('codex-native/bin/codex')
shutil.copy2(prefix/'node_modules/opencode-linux-x64-baseline/bin/opencode',runtimes/'opencode')
licenses=bundle/'licenses';licenses.mkdir(exist_ok=True)
shutil.copy2(prefix/'node_modules/opencode-ai/LICENSE',licenses/'OpenCode-MIT.txt')
# Codex's Apache-2.0 license is fetched separately by the release build when absent
# from npm. Never redistribute the runtime without its license.
license_path=root/'scripts/licenses/Codex-Apache-2.0.txt'
if not license_path.exists():raise SystemExit('Missing Codex license in scripts/licenses')
shutil.copy2(license_path,licenses/license_path.name)
shutil.copy2(root/'scripts/licenses/Codex-NOTICE.txt',licenses/'Codex-NOTICE.txt')
shutil.copy2(root/'LICENSE',licenses/'OnCue-MIT.txt')
shutil.copy2(root/'scripts/install_portable.sh',bundle/'install.sh')
shutil.copytree(root/'integrations',bundle/'integrations',dirs_exist_ok=True)
shutil.copy2(root/'START.md',bundle/'START.md')
shutil.copy2(root/'README.md',bundle/'README.md')
shutil.copytree(root/'docs',bundle/'docs',dirs_exist_ok=True)
with tarfile.open(root/'dist/oncue-linux-x86_64.tar.gz','w:gz',compresslevel=1) as archive:
    archive.add(bundle,arcname='oncue')
print(bundle/'oncue')
