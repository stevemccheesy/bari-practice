// Stand-in for firebase-auth.js. window.__nextUser picks who signs in; window.__closePopup makes the popup fail as if closed.
let user = JSON.parse(localStorage.getItem("__fakeAuth")||"null"); const cbs=[];
export function getAuth(){ return {}; }
export class GoogleAuthProvider{ setCustomParameters(){} }
export function onAuthStateChanged(a,cb){ cbs.push(cb); setTimeout(()=>cb(user),0); return ()=>{}; }
export async function signInWithPopup(){ if(window.__closePopup){ const e=new Error("closed"); e.code="auth/popup-closed-by-user"; throw e; }
  user = window.__nextUser || {uid:"u1",email:"player@example.com"};
  localStorage.setItem("__fakeAuth",JSON.stringify(user)); cbs.forEach(c=>c(user)); return {user}; }
export async function signOut(){ user=null; localStorage.removeItem("__fakeAuth"); cbs.forEach(c=>c(null)); }
