import {useRef,useState} from 'react';

interface Backup {name:string;size:number}
interface Props {
 backups:Backup[];
 loading:boolean;
 recoveryCount:number;
 onExport:()=>Promise<void>;
 onImport:(file:File)=>Promise<void>;
 onBackup:()=>Promise<void>;
 onRestore:(name:string)=>Promise<void>;
 onRecovery:()=>void;
}

function backupDate(name:string){
 const match=/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})\d*Z/.exec(name);
 if(!match)return null;
 return new Date(`${match[1]}-${match[2]}-${match[3]}T${match[4]}:${match[5]}:${match[6]}Z`);
}
function backupKind(name:string){
 return name.endsWith('-scheduled.sqlite3')?'Automatic':name.endsWith('-manual.sqlite3')?'Manual':name.endsWith('-before-restore.sqlite3')?'Before restore':'Backup';
}
const dateFormat=new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'});

export function Settings({backups,loading,recoveryCount,onExport,onImport,onBackup,onRestore,onRecovery}:Props){
 const fileInput=useRef<HTMLInputElement>(null);
 const [busy,setBusy]=useState<string|null>(null),[selectedName,setSelectedName]=useState<string|null>(null);
 const selected=backups.find(backup=>backup.name===selectedName);
 async function run(action:string,operation:()=>Promise<void>){
  if(busy)return;
  setBusy(action);
  try{await operation()}finally{setBusy(null)}
 }
 function activity(action:string){return busy===action?<span className="busy" aria-label="In progress"/>:null}
 return <div className="settings-content">
  <div className="settings-actions">
   <button disabled={!!busy} onClick={()=>void run('export',onExport)}>{activity('export')}Export</button>
   <button disabled={!!busy} onClick={()=>fileInput.current?.click()}>{activity('import')}Import</button>
   <button className="backup-now" disabled={!!busy||loading} onClick={()=>void run('backup',onBackup)}>{activity('backup')}Back up now</button>
   <input ref={fileInput} hidden type="file" accept="application/json,.json" aria-label="Import saved work" onChange={event=>{
    const file=event.target.files?.[0];event.target.value='';
    if(file)void run('import',()=>onImport(file));
   }}/>
  </div>
  <details className="backup-history">
   <summary>Backup history <span className="backup-count">{loading?'…':backups.length}</span></summary>
   {loading?<span className="busy" role="status" aria-label="Loading backups"/>:backups.length?<>
    <div className="backup-list" role="radiogroup" aria-label="Saved backups">
     {backups.map(backup=>{
      const date=backupDate(backup.name);
      return <label className="backup-option" key={backup.name}>
       <input type="radio" name="saved-backup" checked={selected?.name===backup.name} disabled={!!busy} onChange={()=>setSelectedName(backup.name)}/>
       <span>{date?<time dateTime={date.toISOString()}>{dateFormat.format(date)}</time>:<span>Saved backup</span>}<small>{backupKind(backup.name)}</small></span>
      </label>;
     })}
    </div>
    <div className="backup-actions">
     {selected&&<a href={'/api/backups/'+encodeURIComponent(selected.name)} download>Download</a>}
     <button disabled={!!busy||!selected} onClick={()=>selected&&void run('restore',()=>onRestore(selected.name))}>{activity('restore')}Restore selected backup</button>
    </div>
   </>:<p className="backups-empty">No backups yet.</p>}
  </details>
  {recoveryCount>0&&<button className="settings-recovery" disabled={!!busy} onClick={onRecovery}>Recovery <span className="backup-count">{recoveryCount}</span></button>}
 </div>;
}
