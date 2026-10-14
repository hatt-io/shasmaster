const {spawnSync}=require('node:child_process');
const path=require('node:path');
const fs=require('node:fs');
if(process.argv.slice(2).join(' ')!=='--configuration Release')throw Error('Explicit Release configuration required');
process.env.NODE_ENV='production';
const root=path.resolve(__dirname,'..');process.chdir(root);
const work=path.join(root,'.desktop-build');fs.mkdirSync(work,{recursive:true});
const temporary=path.join(root,'codex-tmp-desktop');fs.mkdirSync(temporary,{recursive:true});
process.env.TMPDIR=temporary;process.env.TMP=temporary;process.env.TEMP=temporary;
process.on('exit',()=>fs.rmSync(temporary,{recursive:true,force:true}));
const python=process.env.SHAS_BUILD_PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
function run(command,args){const result=spawnSync(command,args,{stdio:'inherit',env:process.env,shell:process.platform==='win32'&&command.endsWith('.cmd')});if(result.error)throw result.error;if(result.signal||result.status!==0)process.exit(result.status||1)}
if(process.platform==='darwin'&&!process.env.SHAS_SIGN_IDENTITY)throw Error('SHAS_SIGN_IDENTITY must identify a Developer ID Application certificate');
if(process.platform==='win32'){
 run('pwsh',['-NoProfile','-File','native/build-windows.ps1','-Configuration','Release']);
 process.exit(0);
}
if(process.platform==='linux'&&!process.env.SHAS_GPG_KEY)throw Error('SHAS_GPG_KEY must identify the Linux release signing key');
run(python,['-c','import sqlite3; import sys; sys.exit("Build Python must include SQLite 3.43 or newer; use uv managed Python") if sqlite3.sqlite_version_info < (3,43,0) else None']);
run(process.platform==='win32'?'npm.cmd':'npm',['run','build']);
run(python,['-m','PyInstaller','--noconfirm','--distpath',path.join(work,'runtime'),'--workpath',path.join(work,'python'),'desktop/backend.spec']);
if(process.platform==='darwin'){
 run('sh',['native/build-mac.sh','Release']);
 if(process.env.SHAS_NOTARY_PROFILE)run(process.execPath,['native/notarize-mac.cjs','Release']);
 else {console.error('Installer signed. Apple approval still requires SHAS_NOTARY_PROFILE and npm run native:mac:approve.');process.exitCode=2;}
}
if(process.platform==='linux'){
 process.env.SHAS_LINUX_BACKEND=path.join(work,'runtime','shas-backend');
 run('sh',['native/build-linux.sh','Release']);
 const files=fs.readdirSync(path.join(root,'release')).filter(file=>file.endsWith('.deb'));
 if(!files.length)throw Error('No Linux installer was produced');
 for(const file of files)run('gpg',['--batch','--yes','--local-user',process.env.SHAS_GPG_KEY,'--armor','--detach-sign',path.join(root,'release',file)]);
}
