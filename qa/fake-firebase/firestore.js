// Stand-in for firebase-firestore.js, backed by a Python dict through window.__srv (exposed by qa/regress.py).
export function getFirestore(){ return {}; }
export function doc(db,...p){ return {path:p.join("/")}; }
export function collection(db,...p){ return {path:p.join("/")}; }
export async function getDoc(r){ const d=JSON.parse(await window.__srv("get",r.path,"",false)); return {exists:()=>d!=null,data:()=>d}; }
export async function getDocs(r){ const l=JSON.parse(await window.__srv("list",r.path,"",false)); return {docs:l.map(([id,d])=>({id,data:()=>d}))}; }
export async function setDoc(r,data,o){ await window.__srv("set",r.path,JSON.stringify(data),!!(o&&o.merge)); }
