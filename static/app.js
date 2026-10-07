const $ = s => document.querySelector(s);
const monthEl = $('#month'), board = $('#leaderboard'), loading = $('#loading'), empty = $('#empty'), count = $('#count'), label = $('#monthLabel');
const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

function esc(s){return String(s??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}
function medal(i){return i===1?'🥇':i===2?'🥈':i===3?'🥉':i}
function avatar(m){return m.photo_url || `/avatar/${m.user_id}`}
function initDataHeaders(){return tg?.initData?{'X-Telegram-Init-Data':tg.initData}: {}}

let currentMember = null;
let currentMedia = null;

function load(){
  const month = monthEl.value;
  loading.classList.remove('hidden'); empty.classList.add('hidden'); board.innerHTML='';
  fetch(`/api/leaderboard?month=${encodeURIComponent(month)}`)
    .then(r=>r.json())
    .then(d=>{
      loading.classList.add('hidden');
      if(!d.ok){empty.textContent=d.error;empty.classList.remove('hidden');return}
      label.textContent=d.month; count.textContent=`${d.count} eligible members`;
      if(!d.members.length){empty.classList.remove('hidden');return}
      board.innerHTML=d.members.map(m=>`<div class="row ${m.rank<=3?'top':''}"><div class="pos">${medal(m.rank)}</div><img class="row-avatar" src="${avatar(m)}" loading="lazy" onerror="this.style.visibility='hidden'"><div class="person"><div class="name">${esc(m.first_name)}</div><div class="handle">Eligible member</div></div><div class="score">${Number(m.score).toFixed(2)}<small>/100</small></div></div>`).join('');
    })
    .catch(()=>{loading.classList.add('hidden');empty.textContent='Could not load leaderboard.';empty.classList.remove('hidden')});
}

const ADMIN_COMMENTS=[
'👑 আপনি Admin! আপনার আবার Activity Score কীসের? আপনি তো activity-র হিসাব রাখেন! 😎','😂 আপনি হিসাব রাখেন সবার, আপনার হিসাব রাখবে কে?','🫡 Admin সাহেব, নিজের rank নিয়ে এত চিন্তা কেন? Group সামলান!','🏆 আপনার Rank: Admin Supreme! এই leaderboard-এ সেই rank-এর জায়গা নেই।','📢 আপনি Admin, আপনার activity গোপনীয়… অন্তত এই বটের কাছে! 🤫','🤣 আপনি /myrank দিয়েছেন কেন? নিজের কাছে নিজের রিপোর্ট জমা দেবেন নাকি?','👀 Admin হয়েও নিজের activity দেখতে চান? সন্দেহজনক ব্যাপার!','☕ আগে চা খান Admin সাহেব, Activity Score দিয়ে কী করবেন?','🫵 আপনি তো নিয়ম বানান! নিজের জন্য আবার নিয়মের দরকার কী?','🚨 সতর্কবার্তা: Admin-এর অতিরিক্ত rank-checking শনাক্ত করা হয়েছে!','🤖 আমার database-এ আপনার rank নেই, কারণ আপনাকে হিসাবের বাইরে রাখা হয়েছে!','😎 আপনি leaderboard দেখেন, leaderboard আপনাকে দেখে না!','📊 আপনার Activity Report: Admin হওয়াটাই আপনার সবচেয়ে বড় activity!','😂 আপনি কি নিজেকেও group থেকে ban করে activity বাড়াতে চান?','👑 Admin-এর rank জানতে হলে আগে Bot-এর permission নিতে হবে!','🫡 আপনার কাজ member-দের active রাখা, নিজের score দেখে active হওয়া নয়!','🤔 আপনি Admin, নাকি নিজের fan club-এর president?','📢 এই command সাধারণ সদস্যদের জন্য। Admin-দের জন্য আছে শুধু দায়িত্ব আর দুশ্চিন্তা!','💀 আবার /myrank? Admin সাহেব, আপনার কি leaderboard-এর সঙ্গে personal শত্রুতা আছে?','🎖️ অভিনন্দন! আপনি আজও Admin পদে বহাল আছেন। এর চেয়ে বড় achievement আর কী!'
];
function adminComment(){let i=Number(localStorage.getItem('odvut-admin-comment-index')||0);const text=ADMIN_COMMENTS[i%ADMIN_COMMENTS.length];localStorage.setItem('odvut-admin-comment-index',String((i+1)%ADMIN_COMMENTS.length));return text}

function openActivityCard(m){
  currentMember = m;
  currentMedia = null;
  $('#cardAvatar').src=avatar(m);
  $('#cardName').textContent=m.first_name||'Member';
  $('#cardHandle').textContent=m.username?`@${m.username}`:'ODVUT INFO member';
  const admin=m.is_admin===true;
  if(admin){
    $('#cardScore').textContent='ADMIN'; $('#cardRank').textContent='∞'; $('#cardDays').textContent='—'; $('#cardTime').textContent='—'; $('#cardMessages').textContent='—';
    $('#cardStatus').textContent=adminComment(); $('#cardStatus').classList.add('admin-comment');
  } else {
    $('#cardScore').textContent=Number(m.score).toFixed(2); $('#cardRank').textContent=m.rank?`#${m.rank}`:'—'; $('#cardDays').textContent=m.active_days; $('#cardTime').textContent=m.estimated_time; $('#cardMessages').textContent=m.message_count;
    $('#cardStatus').textContent=m.eligible?'✓ LEADERBOARD ELIGIBLE':'NOT ELIGIBLE • 5 ACTIVE DAYS REQUIRED'; $('#cardStatus').classList.remove('admin-comment');
  }
  $('#shareStatus').textContent='';
  $('#cardModal').classList.remove('hidden'); $('#cardModal').setAttribute('aria-hidden','false');
}

async function getMyActivityCard(){
  const btn=$('#getMyCard'); btn.disabled=true; btn.textContent='Loading…';
  try{
    if(!tg?.initData) throw new Error('এই অপশনটি Telegram Mini App-এর ভেতর থেকে ব্যবহার করুন।');
    const r=await fetch(`/api/me?month=${encodeURIComponent(monthEl.value)}`,{headers:initDataHeaders()});
    const d=await r.json(); if(!r.ok||!d.ok) throw new Error(d.error||'Activity card পাওয়া যায়নি।');
    openActivityCard(d.member);
  }catch(e){tg?.showAlert?tg.showAlert(e.message):alert(e.message)}
  finally{btn.disabled=false;btn.textContent='🎴 Get Your Activity Card'}
}

function canvasToBlob(canvas){return new Promise((resolve,reject)=>canvas.toBlob(b=>b?resolve(b):reject(new Error('PNG তৈরি করা যায়নি।')),'image/png',1));}

async function renderCardBlob(){
  const el=$('#activityCard');
  if(!window.html2canvas) throw new Error('Card renderer is still loading. Please try again.');
  const canvas=await html2canvas(el,{scale:3,useCORS:true,allowTaint:false,backgroundColor:null,logging:false});
  return {canvas,blob:await canvasToBlob(canvas)};
}

function safeFilename(){return `odvut-info-activity-card-${($('#cardName').textContent||'member').replace(/[^a-z0-9_-]+/gi,'-').replace(/^-+|-+$/g,'')||'member'}.png`}
function setShareStatus(text){$('#shareStatus').textContent=text||''}
function setActionBusy(busy){document.querySelectorAll('.share-btn').forEach(b=>b.disabled=busy)}

async function uploadCard(blob, filename){
  if(currentMedia?.filename===filename) return currentMedia;
  const form=new FormData(); form.append('file',blob,filename);
  const r=await fetch('/api/card-media',{method:'POST',headers:initDataHeaders(),body:form});
  const d=await r.json(); if(!r.ok||!d.ok) throw new Error(d.error||'Card image upload failed.');
  currentMedia={url:d.url,downloadUrl:d.download_url,filename};
  return currentMedia;
}

async function downloadCard(){
  setActionBusy(true); setShareStatus('Preparing PNG…');
  try{
    const {blob}=await renderCardBlob();
    const filename=safeFilename();
    if(tg?.downloadFile && tg?.initData){
      const media=await uploadCard(blob,filename);
      tg.downloadFile({url:media.downloadUrl||media.url,file_name:filename},ok=>setShareStatus(ok?'Download started.':'Download cancelled.'));
    }else{
      const url=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=url; a.download=filename; document.body.appendChild(a); a.click(); a.remove(); setTimeout(()=>URL.revokeObjectURL(url),2000); setShareStatus('PNG download started.');
    }
  }catch(e){tg?.showAlert?tg.showAlert(e.message):alert(e.message);setShareStatus('')}
  finally{setActionBusy(false)}
}

async function shareToStory(){
  if(!tg?.shareToStory){tg?.showAlert?tg.showAlert('আপনার Telegram version-এ Story sharing support নেই।'):alert('Story sharing is not supported here.');return}
  setActionBusy(true); setShareStatus('Preparing Story…');
  try{
    const {blob}=await renderCardBlob(); const media=await uploadCard(blob,safeFilename());
    tg.shareToStory(media.url,{text:`${$('#cardName').textContent} • ODVUT INFO Activity`,widget_link:{url:window.location.origin,text:'ODVUT INFO'}});
    setShareStatus('Story editor opened.');
  }catch(e){tg?.showAlert?tg.showAlert(e.message):alert(e.message);setShareStatus('')}
  finally{setActionBusy(false)}
}

async function shareToGroup(){
  if(!tg?.shareMessage){tg?.showAlert?tg.showAlert('আপনার Telegram version-এ media sharing support নেই।'):alert('Media sharing is not supported here.');return}
  setActionBusy(true); setShareStatus('Preparing group share…');
  try{
    const {blob}=await renderCardBlob(); const media=await uploadCard(blob,safeFilename());
    const r=await fetch('/api/prepare-share',{method:'POST',headers:{...initDataHeaders(),'Content-Type':'application/json'},body:JSON.stringify({media_url:media.url,caption:`${$('#cardName').textContent} • ODVUT INFO Activity`})});
    const d=await r.json(); if(!r.ok||!d.ok) throw new Error(d.error||'Could not prepare group share.');
    tg.shareMessage(d.id,ok=>setShareStatus(ok?'Activity Card shared successfully.':'Share cancelled.'));
  }catch(e){tg?.showAlert?tg.showAlert(e.message):alert(e.message);setShareStatus('')}
  finally{setActionBusy(false)}
}

function close(id){$(id).classList.add('hidden');$(id).setAttribute('aria-hidden','true');currentMedia=null}
function setTheme(mode){document.documentElement.dataset.theme=mode;localStorage.setItem('odvut-theme',mode);$('#themeToggle').textContent=mode==='dark'?'☀️':'🌙'}
const saved=localStorage.getItem('odvut-theme');setTheme(saved||'dark');
$('#themeToggle').addEventListener('click',()=>setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark'));
$('#refresh').addEventListener('click',load); monthEl.addEventListener('change',load); $('#getMyCard').addEventListener('click',getMyActivityCard);
$('#closeCard').addEventListener('click',()=>close('#cardModal')); document.querySelectorAll('[data-close-card]').forEach(x=>x.addEventListener('click',()=>close('#cardModal')));
$('#downloadCard').addEventListener('click',downloadCard); $('#storyCard').addEventListener('click',shareToStory); $('#groupCard').addEventListener('click',shareToGroup);
load();
