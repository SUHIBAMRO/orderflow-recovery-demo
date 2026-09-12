"use strict";
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));
const escapeHTML = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const scenarios = [
  ['success','Clean completion','Payment, policy and roadtax all succeed.'],
  ['missing_photos','Missing vehicle photos','Underwriting requests photos. Confirm synthetic receipt to continue.'],
  ['owner_mismatch','Owner data mismatch','The roadtax request stops until an operator corrects the data.'],
  ['blacklist','Blacklist → refund','A roadtax-only refund requires explicit supervisor approval.'],
  ['insurer_timeout','Temporary insurer outage','Two transient failures, then recovery on the third attempt.'],
  ['timeout_after_issue','Lost acknowledgement','The policy is issued before timeout. A retry retrieves the same policy.'],
  ['persistent_outage','Retry budget exhausted','Three failed attempts route the case to manual review.']
];
const statuses = {
 RUNNING:['Processing','blue'], RETRYING:['Retrying','blue'], WAITING_PHOTOS:['Photos needed','amber'],
 WAITING_CORRECTION:['Data correction','amber'], REFUND_REQUIRED:['Refund approval','red'],
 MANUAL_REVIEW:['Manual review','amber'], COMPLETED:['Completed','green'], ROADTAX_REFUNDED:['Roadtax refunded','green']
};
const blocked = ['WAITING_PHOTOS','WAITING_CORRECTION','REFUND_REQUIRED','MANUAL_REVIEW'];
const done = ['COMPLETED','ROADTAX_REFUNDED'];
let token='', session=null, orders=[], current=null, selected=null, busy=false, detailVersion=null, actionType=null, actionVersion=null, refreshBusy=false;
let createKey=null, actionKey=null, toastTimer=null;
const badge = status => `<span class="pill ${statuses[status]?.[1] || 'neutral'}">${escapeHTML(statuses[status]?.[0] || status)}</span>`;
const money = o => new Intl.NumberFormat('en-MY',{style:'currency',currency:o.currency}).format(o.roadtax_cents/100);
const date = t => new Date(t*1000).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'});
function age(t){const m=Math.floor((Date.now()/1000-t)/60);return m<1?'Just now':m<60?`${m}m ago`:`${Math.floor(m/60)}h ${m%60}m ago`;}
function toast(message){clearTimeout(toastTimer);$('#toast').textContent=message;$('#toast').classList.remove('hidden');toastTimer=setTimeout(()=>$('#toast').classList.add('hidden'),4000);}
async function api(path, options={}){
 const headers={'Authorization':`Bearer ${token}`,...(options.headers||{})};
 if(options.body) headers['Content-Type']='application/json';
 const response=await fetch('/api'+path,{...options,headers});
 let data;try{data=await response.json();}catch{throw new Error('The server returned an unreadable response.');}
 if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'Request validation failed.');error.status=response.status;throw error;}
 return data;
}
function view(name){$$('.view').forEach(e=>e.classList.add('hidden'));$(`#${name}-view`).classList.remove('hidden');$$('[data-view]').forEach(e=>e.classList.toggle('active',e.dataset.view===name));$('#breadcrumb').textContent={queue:'Order queue',lab:'Scenario lab',guide:'Recovery rules'}[name];}
$$('[data-view]').forEach(b=>b.addEventListener('click',()=>view(b.dataset.view)));
function renderList(){
 const search=$('#search').value.toLowerCase(), filter=$('#status-filter').value;
 const list=orders.filter(o=>(filter==='all'||(filter==='action'?blocked.includes(o.status):o.status===filter))&&`${o.id} ${o.customer} ${o.vehicle}`.toLowerCase().includes(search));
 $('#queue-count').textContent=orders.filter(o=>!done.includes(o.status)).length;
 $('#stat-open').textContent=orders.filter(o=>!done.includes(o.status)).length;
 $('#stat-action').textContent=orders.filter(o=>blocked.includes(o.status)).length;
 $('#stat-retry').textContent=orders.filter(o=>o.status==='RETRYING').length;
 $('#stat-done').textContent=orders.filter(o=>done.includes(o.status)).length;
 $('#visible-count').textContent=`${list.length} of ${orders.length} loaded orders`;
 $('#order-list').innerHTML=list.length?list.map(o=>`<button class="order-row ${o.id===selected?'selected':''}" data-order="${escapeHTML(o.id)}" aria-pressed="${o.id===selected}"><div class="row-top"><span class="order-id">${escapeHTML(o.id)}</span>${badge(o.status)}</div><h3>${escapeHTML(o.customer)}</h3><p>${escapeHTML(o.vehicle)}</p><div class="row-bottom"><span class="reason">${escapeHTML(o.reason?o.reason.replaceAll('_',' '):o.phase+' • '+money(o))}</span><span>${age(o.created_at)}</span></div></button>`).join(''):`<div class="empty"><span>▤</span><h3>${orders.length?'No matching orders':'Your queue is clear'}</h3><p>${orders.length?'Try another search or status.':'Create a test order to run a recovery scenario.'}</p></div>`;
 $$('[data-order]').forEach(b=>b.addEventListener('click',async()=>{selected=b.dataset.order;detailVersion=null;renderList();try{await loadDetail();}catch(e){toast(e.message);}}));
}
function actionInfo(o){
 const entries={
 WAITING_PHOTOS:['Vehicle photos are required.','A synthetic request was recorded. Confirm only after reviewing the required front and rear photos in this test scenario.','confirm_photos','Confirm photo receipt'],
 WAITING_CORRECTION:['Owner information needs correction.','Automatic roadtax retries are disabled. Correct the synthetic identity data to resume the existing order.','correct_owner','Correct & continue'],
 REFUND_REQUIRED:['Roadtax refund needs approval.',`${money(o)} for roadtax only. The active insurance policy remains unchanged. No money has been refunded.`,'approve_refund','Approve roadtax refund'],
 MANUAL_REVIEW:['This order needs manual review.',o.reason==='RETRIES_EXHAUSTED'?'The retry budget is exhausted. Investigate the provider before allowing another bounded attempt cycle.':'The case has been escalated. Investigate outside this demo; no automated resolution is available.',o.reason==='RETRIES_EXHAUSTED'?'retry':null,'Authorize another retry cycle'],
 RETRYING:['Recovery is in progress.',`A transient failure is being retried with the same operation key. Next attempt: ${date(o.next_attempt)}.`,null,null],
 RUNNING:['Workflow is processing.','The backend is executing the next durable step. This view refreshes automatically.',null,null],
 COMPLETED:['Order completed.','The synthetic policy and roadtax references are recorded. No further action is required.',null,null],
 ROADTAX_REFUNDED:['Roadtax refund completed.','The synthetic provider confirmed the roadtax-only refund. The insurance policy remains active.',null,null]
 };return entries[o.status]||['Review required',o.reason,null,null];
}
async function loadDetail(){
 if(!selected)return;const id=selected;const data=await api('/orders/'+encodeURIComponent(id));if(selected!==id)return;current=data.order;
 if(detailVersion===current.version)return;detailVersion=current.version;renderDetail(data);
}
function renderDetail({order:o,events}){
 const [title,description,action,label]=actionInfo(o), success=done.includes(o.status),info=['RUNNING','RETRYING'].includes(o.status);
 const canAct=session.role!=='viewer', canRefund=['supervisor','demo'].includes(session.role);
 const stages=[['Payment',o.phase!=='PAYMENT',o.phase==='PAYMENT'],['Policy',!!o.policy_ref,['INSURER','NOTIFY_PHOTOS'].includes(o.phase)],['Roadtax',!!o.roadtax_ref,['ROADTAX','REFUND'].includes(o.phase)&&!done.includes(o.status)]];
 $('#detail').innerHTML=`<div class="detail-header"><div class="detail-title"><h2>${escapeHTML(o.id)}</h2>${badge(o.status)}</div><p>${escapeHTML(o.customer)} <span>·</span> ${escapeHTML(o.vehicle)}</p></div><div class="workflow-track">${stages.map(([name,isDone,isCurrent],i)=>`<div class="step ${isDone?'done':isCurrent?'current':''}"><span class="step-icon">${isDone?'✓':i+1}</span>${name}</div>`).join('')}</div><div class="detail-body"><div class="action-box ${success?'success':info?'info':''}"><span class="overline">${success?'RESOLUTION':info?'WORKFLOW STATUS':'NEXT SAFE ACTION'}</span><h3>${escapeHTML(title)}</h3><p>${escapeHTML(description)}</p>${action?`<div class="action-buttons"><button class="button primary" data-action="${action}" ${!canAct||(action==='approve_refund'&&!canRefund)?'disabled':''}>${escapeHTML(label)}</button>${blocked.includes(o.status)&&o.reason!=='ESCALATED'?`<button class="button secondary" data-action="escalate" ${!canAct?'disabled':''}>Escalate</button>`:''}</div>${action==='approve_refund'&&!canRefund?'<p>Sign in as a supervisor to approve this refund.</p>':''}`:''}</div><dl class="facts"><div><dt>Roadtax amount</dt><dd>${money(o)}</dd></div><div><dt>Synthetic identity suffix</dt><dd>•••• ${escapeHTML(o.owner_last4)}</dd></div><div><dt>Policy reference</dt><dd>${escapeHTML(o.policy_ref||'Not issued')}</dd></div><div><dt>Attempts in current phase</dt><dd>${o.attempt} / 3</dd></div>${o.refund_ref?`<div><dt>Refund reference</dt><dd>${escapeHTML(o.refund_ref)}</dd></div>`:''}${o.roadtax_ref?`<div><dt>Roadtax reference</dt><dd>${escapeHTML(o.roadtax_ref)}</dd></div>`:''}</dl><div class="section-title"><h3>Audit timeline</h3><span>${events.length} events · v${o.version}</span></div><ol class="timeline">${events.slice().reverse().map(e=>`<li><span class="event-dot"></span><div><div class="event-head"><strong>${escapeHTML(e.kind.replaceAll('.',' › ').replaceAll('_',' '))}</strong><time datetime="${new Date(e.occurred_at*1000).toISOString()}">${date(e.occurred_at)}</time></div><small>${escapeHTML(e.actor)} · ${escapeHTML(e.policy_version)}</small><details><summary>Inspect evidence</summary><pre>${escapeHTML(JSON.stringify(e.details,null,2))}</pre></details></div></li>`).join('')}</ol></div>`;
 $$('[data-action]').forEach(b=>b.addEventListener('click',()=>openAction(b.dataset.action)));
}
async function refresh(){if(!token||refreshBusy)return;refreshBusy=true;try{orders=await api('/orders');renderList();await loadDetail();$('#connection').textContent='Connected';$('.environment').classList.add('connected');}catch(e){$('#connection').textContent='Connection issue';$('.environment').classList.remove('connected');if(e.status===401){token='';session=null;$('#login-error').textContent='Session ended. Sign in again.';if(!$('#login-dialog').open)$('#login-dialog').showModal();}}finally{refreshBusy=false;}}
$('#refresh').addEventListener('click',refresh);$('#search').addEventListener('input',renderList);$('#status-filter').addEventListener('change',renderList);
function openCreate(scenario='owner_mismatch'){if(!session||session.role==='viewer'){toast('An operator or supervisor token is required.');return;}$('#scenario').value=scenario;$('#create-form .form-error').textContent='';createKey=crypto.randomUUID();$('#create-dialog').showModal();}
$('#new-order').addEventListener('click',()=>openCreate());
$('#scenario').innerHTML=scenarios.map(([id,title])=>`<option value="${id}">${title}</option>`).join('');
$('#scenario-grid').innerHTML=scenarios.map(([id,title,description],i)=>`<article class="panel scenario-card"><span class="scenario-number">SCENARIO 0${i+1}</span><h2>${title}</h2><p>${description}</p><button class="button secondary" data-scenario="${id}">Run scenario →</button></article>`).join('');
$$('[data-scenario]').forEach(b=>b.addEventListener('click',()=>openCreate(b.dataset.scenario)));
$$('.close-dialog').forEach(b=>b.addEventListener('click',()=>{if(!busy)b.closest('dialog').close();}));
$('#create-form').addEventListener('input',()=>{if(!busy)createKey=crypto.randomUUID();});
$('#create-form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;const b=e.submitter;b.disabled=true;try{
 const order=await api('/orders',{method:'POST',headers:{'Idempotency-Key':createKey},body:JSON.stringify({scenario:$('#scenario').value,customer:$('#customer').value,vehicle:$('#vehicle').value,owner_last4:$('#owner').value,roadtax_cents:Math.round(Number($('#amount').value)*100)})});
 selected=order.id;detailVersion=null;$('#create-dialog').close();view('queue');await refresh();toast('Test order created. The backend is processing it.');
 }catch(error){$('#create-form .form-error').textContent=error.message;}finally{busy=false;b.disabled=false;}});
function openAction(action){actionType=action;actionVersion=current.version;actionKey=crypto.randomUUID();const texts={confirm_photos:['Confirm photo receipt','Confirm the front and rear photos were reviewed in this synthetic scenario. This demo does not upload or verify documents.'],correct_owner:['Correct owner information','This resumes only the blocked roadtax step. The issued insurance policy is not recreated.'],approve_refund:['Approve roadtax refund',`Authorize one synthetic refund of ${money(current)}. The active insurance policy is not cancelled.`],retry:['Authorize another retry cycle','The same provider operation key will be reused. A maximum of three additional attempts is permitted.'],escalate:['Escalate to manual review','This pauses automatic work. Record the investigation or handoff required.']};$('#action-title').textContent=texts[action][0];$('#action-description').textContent=texts[action][1];$('#correction-field').classList.toggle('hidden',action!=='correct_owner');$('#corrected-owner').required=action==='correct_owner';$('#action-note').value='';$('#action-form .form-error').textContent='';$('#action-dialog').showModal();}
$('#action-form').addEventListener('input',()=>{if(!busy)actionKey=crypto.randomUUID();});
$('#action-form').addEventListener('submit',async e=>{e.preventDefault();if(busy)return;busy=true;const b=e.submitter;b.disabled=true;try{const payload={note:$('#action-note').value,expected_version:actionVersion};if(actionType==='correct_owner')payload.owner_last4=$('#corrected-owner').value;await api(`/orders/${encodeURIComponent(selected)}/actions/${actionType}`,{method:'POST',headers:{'Idempotency-Key':actionKey},body:JSON.stringify(payload)});$('#action-dialog').close();detailVersion=null;await refresh();toast('Action recorded in the audit trail.');}catch(error){$('#action-form .form-error').textContent=error.message;if(error.status===409){detailVersion=null;await refresh();}}finally{busy=false;b.disabled=false;}});
$('#classify').addEventListener('click',async e=>{e.target.disabled=true;try{$('#classifier-result').textContent=JSON.stringify(await api('/classify',{method:'POST',body:JSON.stringify({text:$('#classifier-text').value})}),null,2);}catch(error){toast(error.message);}finally{e.target.disabled=false;}});
$('#login-dialog').addEventListener('cancel',e=>e.preventDefault());
$('#login-form').addEventListener('submit',async e=>{e.preventDefault();const b=e.submitter;b.disabled=true;token=$('#access-token').value.trim();try{session=await api('/session');$('#actor').textContent=session.actor;$('#role').textContent=session.role;$('#runtime-info').textContent=`Runtime: ${session.mode}. Providers: ${session.providers}.`;$('#new-order').disabled=session.role==='viewer';$('#login-dialog').close();$('#access-token').value='';$('#login-error').textContent='';await refresh();}catch(error){token='';$('#login-error').textContent=error.message;}finally{b.disabled=false;}});
$('#signout').addEventListener('click',()=>location.reload());
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
setInterval(()=>{if(!document.hidden)refresh();},2000);
async function boot(){
 try{token='';session=await api('/session');if(!session.public_demo)throw new Error('TOKEN_REQUIRED');
   token='public-demo';$('#actor').textContent='Public demo';$('#role').textContent='synthetic sandbox';
   $('#runtime-info').textContent=`Runtime: ${session.mode}. Providers: ${session.providers}.`;
   await refresh();
 }catch(error){token='';$('#login-dialog').showModal();}
}
boot();

// Lightweight client-side localization. English remains the source language.
const nl = {
 'RECOVERY WORKSPACE':'HERSTELWERKRUIMTE','OPERATIONS':'OPERATIES','Order queue':'Orderwachtrij','Scenario lab':'Scenariolab','Recovery rules':'Herstelregels',
 'SAFE DEMONSTRATION':'VEILIGE DEMONSTRATIE','Synthetic customers.':'Synthetische klanten.','No real policies or money.':'Geen echte polissen of geld.',
 'Independent prototype.':'Onafhankelijk prototype.','Not affiliated with BJAK or JPJ.':'Niet verbonden aan BJAK of JPJ.','Not signed in':'Niet ingelogd',
 'Access token required':'Toegangstoken vereist','Public demo':'Openbare demo','synthetic sandbox':'synthetische sandbox','Sign out':'Uitloggen',
 'Operations':'Operaties','Disconnected':'Niet verbonden','Connected':'Verbonden','Connection issue':'Verbindingsprobleem','SANDBOX':'TESTOMGEVING',
 'EXCEPTION MANAGEMENT':'UITZONDERINGSBEHEER','Keep every order moving.':'Houd elke bestelling in beweging.','Find the blocker. Take the next safe action.':'Vind de blokkade. Neem de volgende veilige actie.',
 '＋ Create test order':'＋ Testbestelling maken','Open orders':'Open bestellingen','Needs intervention':'Interventie vereist','Automatic retries':'Automatische pogingen','Resolved':'Afgerond',
 'Across the loaded queue':'In de geladen wachtrij','Waiting on a person':'Wacht op een medewerker','Scheduled, with backoff':'Gepland, met wachttijd','Completed or roadtax refunded':'Voltooid of wegenbelasting terugbetaald',
 'Refresh ↻':'Vernieuwen ↻','Search order or customer':'Zoek bestelling of klant','Filter status':'Filter status','All statuses':'Alle statussen','Needs action':'Actie vereist','Retrying':'Opnieuw proberen','Completed':'Voltooid','Roadtax refunded':'Wegenbelasting terugbetaald',
 'Your queue is clear':'Uw wachtrij is leeg','Create a test order to run a recovery scenario.':'Maak een testbestelling om een herstelscenario uit te voeren.','Updates every 2 seconds':'Wordt elke 2 seconden bijgewerkt',
 'Every exception has a next step.':'Elke uitzondering heeft een volgende stap.','Select an order to inspect its progress, evidence and recovery actions.':'Selecteer een bestelling om voortgang, bewijs en herstelacties te bekijken.',
 'Payment':'Betaling','Policy':'Polis','Roadtax':'Wegenbelasting','Evidence before action.':'Bewijs vóór actie.','CONTROLLED FAILURE INJECTION':'GECONTROLEERDE FOUTSIMULATIE',
 'Every scenario creates a persisted order and calls synthetic provider APIs.':'Elk scenario maakt een opgeslagen bestelling en roept synthetische provider-API’s aan.',
 'Clean completion':'Probleemloze voltooiing','Payment, policy and roadtax all succeed.':'Betaling, polis en wegenbelasting slagen allemaal.','Missing vehicle photos':'Ontbrekende voertuigfoto’s',
 'Underwriting requests photos. Confirm synthetic receipt to continue.':'Acceptatie vraagt om foto’s. Bevestig de synthetische ontvangst om door te gaan.','Owner data mismatch':'Eigenaarsgegevens komen niet overeen',
 'The roadtax request stops until an operator corrects the data.':'De wegenbelastingaanvraag stopt totdat een medewerker de gegevens corrigeert.','Blacklist → refund':'Blokkadelijst → terugbetaling',
 'A roadtax-only refund requires explicit supervisor approval.':'Een terugbetaling van alleen wegenbelasting vereist expliciete goedkeuring van een supervisor.','Temporary insurer outage':'Tijdelijke storing bij verzekeraar',
 'Two transient failures, then recovery on the third attempt.':'Twee tijdelijke fouten, daarna herstel bij de derde poging.','Lost acknowledgement':'Ontbrekende ontvangstbevestiging',
 'The policy is issued before timeout. A retry retrieves the same policy.':'De polis wordt vóór de time-out uitgegeven. Een nieuwe poging haalt dezelfde polis op.','Retry budget exhausted':'Maximum aantal pogingen bereikt',
 'Three failed attempts route the case to manual review.':'Na drie mislukte pogingen gaat de zaak naar handmatige beoordeling.','Run scenario →':'Scenario uitvoeren →','What is real here?':'Wat is hier echt?',
 'ASSISTIVE ONLY':'ALLEEN ONDERSTEUNEND','Response interpretation':'Interpretatie van reacties','A deterministic text-classification baseline. Not an LLM and never an action executor.':'Een deterministische basis voor tekstclassificatie. Geen LLM en nooit een uitvoerder van acties.',
 'Provider message':'Providerbericht','Classify message':'Bericht classificeren','POLICY VERSION • DEMO-1.0':'BELEIDSVERSIE • DEMO-1.0','Explicit rules. Bounded retries. Human approval for refunds.':'Expliciete regels. Begrensde pogingen. Menselijke goedkeuring voor terugbetalingen.',
 'Provider outcome':'Providerresultaat','Recovery path':'Herstelpad','Retry policy':'Pogingenbeleid','Prototype boundaries':'Grenzen van het prototype','Welcome to OrderFlow.':'Welkom bij OrderFlow.',
 'OPERATIONS ACCESS':'TOEGANG VOOR OPERATIES','Access token':'Toegangstoken','Open workspace →':'Werkruimte openen →','SYNTHETIC ORDER':'SYNTHETISCHE BESTELLING','Create a test order':'Testbestelling maken',
 'Failure scenario':'Foutscenario','Synthetic customer label':'Synthetisch klantlabel','Vehicle label':'Voertuiglabel','Synthetic identity: last 4':'Synthetische identiteit: laatste 4','Roadtax amount (MYR)':'Wegenbelasting (MYR)',
 'No real customer information. Payment and policy issuance are simulated.':'Geen echte klantgegevens. Betaling en polisuitgifte worden gesimuleerd.','Create & run workflow →':'Maken en workflow uitvoeren →',
 'AUDITED OPERATOR ACTION':'GECONTROLEERDE MEDEWERKERSACTIE','Resolve order':'Bestelling oplossen','Corrected synthetic identity: last 4':'Gecorrigeerde synthetische identiteit: laatste 4','Reason / evidence reviewed':'Reden / beoordeeld bewijs','Confirm action':'Actie bevestigen',
 'Processing':'Bezig','Photos needed':'Foto’s nodig','Data correction':'Gegevenscorrectie','Refund approval':'Goedkeuring terugbetaling','Manual review':'Handmatige beoordeling','Roadtax refunded':'Wegenbelasting terugbetaald',
 'Vehicle photos are required.':'Voertuigfoto’s zijn vereist.','Confirm photo receipt':'Ontvangst foto’s bevestigen','Owner information needs correction.':'Eigenaarsgegevens moeten worden gecorrigeerd.','Correct & continue':'Corrigeren en doorgaan',
 'Roadtax refund needs approval.':'Terugbetaling van wegenbelasting vereist goedkeuring.','Approve roadtax refund':'Terugbetaling goedkeuren','This order needs manual review.':'Deze bestelling vereist handmatige beoordeling.',
 'Authorize another retry cycle':'Nieuwe pogingencyclus toestaan','Recovery is in progress.':'Herstel is bezig.','Workflow is processing.':'Workflow wordt verwerkt.','Order completed.':'Bestelling voltooid.','Roadtax refund completed.':'Terugbetaling wegenbelasting voltooid.',
 'Just now':'Zojuist','Demo customer':'Demoklant','The synthetic policy and roadtax references are recorded. No further action is required.':'De synthetische polis- en wegenbelastingreferenties zijn opgeslagen. Er is geen verdere actie nodig.',
 'The backend is executing the next durable step. This view refreshes automatically.':'De backend voert de volgende duurzame stap uit. Deze weergave wordt automatisch vernieuwd.','The synthetic provider confirmed the roadtax-only refund. The insurance policy remains active.':'De synthetische provider bevestigde de terugbetaling van alleen de wegenbelasting. De verzekeringspolis blijft actief.',
 'Automatic roadtax retries are disabled. Correct the synthetic identity data to resume the existing order.':'Automatische nieuwe pogingen voor de wegenbelasting zijn uitgeschakeld. Corrigeer de synthetische identiteitsgegevens om de bestaande bestelling te hervatten.','A synthetic request was recorded. Confirm only after reviewing the required front and rear photos in this test scenario.':'Er is een synthetisch verzoek vastgelegd. Bevestig pas nadat u de vereiste voor- en achterfoto’s in dit testscenario hebt beoordeeld.',
 'NEXT SAFE ACTION':'VOLGENDE VEILIGE ACTIE','WORKFLOW STATUS':'WORKFLOWSTATUS','RESOLUTION':'OPLOSSING','Roadtax amount':'Wegenbelasting','Synthetic identity suffix':'Synthetisch identiteitssuffix','Policy reference':'Polisreferentie','Not issued':'Niet uitgegeven','Attempts in current phase':'Pogingen in huidige fase','Refund reference':'Terugbetalingsreferentie','Roadtax reference':'Wegenbelastingreferentie','Audit timeline':'Audit-tijdlijn','Inspect evidence':'Bewijs bekijken','Escalate':'Escaleren',
 'Confirm photo receipt':'Ontvangst foto’s bevestigen','Correct owner information':'Eigenaarsgegevens corrigeren','Approve roadtax refund':'Terugbetaling wegenbelasting goedkeuren','Authorize another retry cycle':'Nieuwe pogingencyclus toestaan','Escalate to manual review':'Naar handmatige beoordeling escaleren','Action recorded in the audit trail.':'Actie vastgelegd in het auditspoor.','Test order created. The backend is processing it.':'Testbestelling gemaakt. De backend verwerkt deze.'
};
const sourceText = new WeakMap(), sourceAttrs = new WeakMap();
function translated(value){
 const trimmed=value.trim(); let result=nl[trimmed];
 if(!result){let m=trimmed.match(/^(\d+) of (\d+) loaded orders$/);if(m)result=`${m[1]} van ${m[2]} geladen bestellingen`;}
 if(!result){let m=trimmed.match(/^(\d+) orders$/);if(m)result=`${m[1]} bestellingen`;}
 if(!result){let m=trimmed.match(/^(\d+) events · v(\d+)$/);if(m)result=`${m[1]} gebeurtenissen · v${m[2]}`;}
 return result?value.replace(trimmed,result):value;
}
function localize(root=document){
 const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let node;
 while((node=walker.nextNode())){if(!sourceText.has(node))sourceText.set(node,node.nodeValue);node.nodeValue=currentLanguage==='nl'?translated(sourceText.get(node)):sourceText.get(node);}
 root.querySelectorAll?.('[placeholder],[title],[aria-label]').forEach(el=>{let attrs=sourceAttrs.get(el);if(!attrs){attrs={};for(const a of ['placeholder','title','aria-label'])if(el.hasAttribute(a))attrs[a]=el.getAttribute(a);sourceAttrs.set(el,attrs);}for(const [a,v] of Object.entries(attrs))el.setAttribute(a,currentLanguage==='nl'?(nl[v]||v):v);});
 document.documentElement.lang=currentLanguage;
 $$('[data-language]').forEach(b=>b.classList.toggle('active',b.dataset.language===currentLanguage));
}
let currentLanguage=localStorage.getItem('orderflow-language')==='nl'?'nl':'en';
$$('[data-language]').forEach(b=>b.addEventListener('click',()=>{currentLanguage=b.dataset.language;localStorage.setItem('orderflow-language',currentLanguage);localize();}));
new MutationObserver(records=>{for(const record of records)for(const node of record.addedNodes)if(node.nodeType===1)localize(node);}).observe(document.body,{childList:true,subtree:true});
localize();
