// Stand-in for firebase-app.js so the QA suite can run sign-in and sync offline.
export function initializeApp(cfg){ return {cfg}; }
