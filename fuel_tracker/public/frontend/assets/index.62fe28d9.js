var p=(e,t,n)=>new Promise((o,r)=>{var s=c=>{try{l(n.next(c))}catch(m){r(m)}},i=c=>{try{l(n.throw(c))}catch(m){r(m)}},l=c=>c.done?o(c.value):Promise.resolve(c.value).then(s,i);l((n=n.apply(e,t)).next())});import{c as g,r as y,a as k,b as E,d as w,_ as P,e as C,o as O,f as U,g as b,h as A,s as I,i as R,j as S,C as W,I as j,D as $,k as q}from"./vendor.499e631e.js";const x=function(){const t=document.createElement("link").relList;if(t&&t.supports&&t.supports("modulepreload"))return;for(const r of document.querySelectorAll('link[rel="modulepreload"]'))o(r);new MutationObserver(r=>{for(const s of r)if(s.type==="childList")for(const i of s.addedNodes)i.tagName==="LINK"&&i.rel==="modulepreload"&&o(i)}).observe(document,{childList:!0,subtree:!0});function n(r){const s={};return r.integrity&&(s.integrity=r.integrity),r.referrerpolicy&&(s.referrerPolicy=r.referrerpolicy),r.crossorigin==="use-credentials"?s.credentials="include":r.crossorigin==="anonymous"?s.credentials="omit":s.credentials="same-origin",s}function o(r){if(r.ep)return;r.ep=!0;const s=n(r);fetch(r.href,s)}};x();const D="fuel-tracker-cache-v1",F=["./"];self.addEventListener("install",e=>{e.waitUntil(caches.open(D).then(t=>(console.log("Opened cache"),t.addAll(F))))});self.addEventListener("fetch",e=>{e.respondWith(caches.match(e.request).then(t=>t||fetch(e.request)))});self.addEventListener("activate",e=>{const t=["fuel-tracker-cache-v1"];e.waitUntil(caches.keys().then(n=>Promise.all(n.map(o=>{if(t.indexOf(o)===-1)return caches.delete(o)}))))});const H="modulepreload",v={},B="/assets/fuel_tracker/frontend/",L=function(t,n){return!n||n.length===0?t():Promise.all(n.map(o=>{if(o=`${B}${o}`,o in v)return;v[o]=!0;const r=o.endsWith(".css"),s=r?'[rel="stylesheet"]':"";if(document.querySelector(`link[href="${o}"]${s}`))return;const i=document.createElement("link");if(i.rel=r?"stylesheet":H,r||(i.as="script",i.crossOrigin=""),i.href=o,document.head.appendChild(i),r)return new Promise((l,c)=>{i.addEventListener("load",l),i.addEventListener("error",c)})})).then(()=>t())},h=g({url:"frappe.auth.get_logged_user",cache:"User",onError(e){e&&e.exc_type==="AuthenticationError"&&d.push({name:"LoginPage"})}});function _(){let t=new URLSearchParams(document.cookie.split("; ").join("&")).get("user_id");return t==="Guest"&&(t=null),t}const u=y({login:g({url:"login",makeParams({email:e,password:t}){return{usr:e,pwd:t}},onSuccess(e){h.reload(),u.user=_(),u.login.reset(),d.replace(e.default_route||"/")}}),logout:g({url:"logout",onSuccess(){h.reset(),u.user=_(),d.replace({name:"Login"})}}),user:_(),isLoggedIn:k(()=>!!u.user)}),N=[{path:"/",name:"Home",component:()=>L(()=>import("./Home.e7f357a8.js"),["assets/Home.e7f357a8.js","assets/vendor.499e631e.js","assets/vendor.1875b906.css"])},{name:"Login",path:"/account/login",component:()=>L(()=>import("./Login.7009f4bb.js"),["assets/Login.7009f4bb.js","assets/vendor.499e631e.js","assets/vendor.1875b906.css"])}];let d=E({history:w("/frontend"),routes:N});d.beforeEach((e,t,n)=>p(void 0,null,function*(){let o=u.isLoggedIn;try{yield h.promise}catch(r){o=!1}e.name==="Login"&&o?n({name:"Home"}):e.name!=="Login"&&!o?n({name:"Login"}):n()}));const T={};function V(e,t){const n=C("router-view");return O(),U("div",null,[b(n)])}var G=P(T,[["render",V]]);let a=A(G);I("resourceFetcher",q);a.use(d);a.use(R);a.component("Button",S);a.component("Card",W);a.component("Input",j);a.mount("#app");"serviceWorker"in navigator&&window.addEventListener("load",()=>{navigator.serviceWorker.register("sw.js").then(e=>{console.log("SW registered: ",e)}).catch(e=>{console.log("SW registration failed: ",e)})});const f=new $("FuelTrackerDB");f.version(1).stores({fuelUsed:"++id, date, fuel_tanker, site, reg_no, resource_type, make, type, resource"});function z(e){return p(this,null,function*(){f.fuelUsed.add(e).then(()=>{console.log("Fuel used saved for syncing")})})}window.addEventListener("online",()=>{f.fuelUsed.each(e=>{console.log(e),f.fuelUsed.delete(e.id)})});export{u as a,f as d,z as s};