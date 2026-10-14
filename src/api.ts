let sessionToken='';
let tokenRequest:Promise<string>|undefined;
export class ApiError extends Error {constructor(message:string,public status:number){super(message);this.name='ApiError'}}
async function token(){if(sessionToken)return sessionToken;if(!tokenRequest)tokenRequest=fetch('/api/session').then(async response=>{if(!response.ok)throw new Error('Session unavailable');return response.json()}).then(result=>sessionToken=result.token).finally(()=>{tokenRequest=undefined});return tokenRequest}
async function responseFor(path:string,options:RequestInit={}):Promise<Response>{
 const method=options.method||'GET',modifies=method!=='GET'&&method!=='HEAD',headers=new Headers(options.headers);
 if(modifies)headers.set('X-Shas-Token',await token());
 if(options.body&&!(options.body instanceof FormData))headers.set('Content-Type','application/json');
 let response=await fetch('/api'+path,{...options,headers});
 if(response.status===403&&modifies){sessionToken='';headers.set('X-Shas-Token',await token());response=await fetch('/api'+path,{...options,headers})}
 if(!response.ok){const error=await response.json().catch(()=>({detail:response.statusText}));throw new ApiError(typeof error.detail==='string'?error.detail:response.statusText,response.status)}
 return response;
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{return (await responseFor(path,options)).json()}
export async function pdfRequest(path:string,body:unknown,signal:AbortSignal){return new Uint8Array(await (await responseFor(path,{method:'POST',body:JSON.stringify(body),signal})).arrayBuffer())}
