import { type FormEvent, useEffect, useMemo, useState } from 'react';
import DoctoratesPanel from './DoctoratesPanel';
import ImmigrationPanel from './ImmigrationPanel';
import RecruitersPanel from './RecruitersPanel';
import { CheckCircle2, Search, Plus, BriefcaseBusiness, MapPin, Sparkles, ChartNoAxesCombined, FileText, Trash2, ExternalLink, X, ShieldCheck, RefreshCw, Sun, Moon, GraduationCap, Globe2, Users } from 'lucide-react';

type Job = {id:number;created_at?:string|null;title:string;company:string;location:string;country:string;work_mode:string;contract_type:string;description:string;url?:string;source:string;skills:string[];match_score:number;match_reasons?:string[];missing_skills?:string[];published_at?:string|null;collected_at?:string|null;status:string;notes:string;role_category?:'Full Stack'|'Mobile'|'Autre';remote_type?:string;relocation_supported?:boolean;international_recruitment?:boolean;relocation_evidence?:string};
type SyncStatus = {auto_sync_enabled:boolean;interval_minutes:number;collected_offers:number;last_run?:{started_at:string;finished_at?:string;status:string;inserted:number;updated:number;skipped:number;sources:Record<string,{received:number;error?:string|null;enabled?:boolean}>;error?:string}|null};
type Draft = {subject:string;email:string;letter:string;warning:string;requires_human_approval:boolean;language?:'fr'|'en';cv_suggestion?:string};
const API = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000/api';
const emptyForm = {title:'',company:'',location:'',country:'Sénégal',work_mode:'Hybride',contract_type:'CDI',description:'',url:'',source:'Ajout manuel',skills:''};
function jobDateTimestamp(job: Pick<Job, 'published_at' | 'created_at'>) {
 for (const raw of [job.published_at, job.created_at]) {
  if (!raw) continue;
  const timestamp = Date.parse(raw);
  if (Number.isFinite(timestamp)) return timestamp;
 }
 return NaN;
}

function hasKnownJobDate(job: Pick<Job, 'published_at' | 'created_at'>) {
 return Number.isFinite(jobDateTimestamp(job));
}

function isRecentJob(job: Pick<Job, 'published_at' | 'created_at'>) {
 const timestamp = jobDateTimestamp(job);
 return Number.isFinite(timestamp) &&
  timestamp >= Date.now() - 7 * 24 * 60 * 60 * 1000;
}

function localDateInput() {
 const d = new Date();
 return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function matchesCollectionFilters(
 job: Pick<Job, 'collected_at' | 'created_at'>,
 period: string,
 interval: string,
 dateFrom: string,
 dateTo: string
) {
 const raw = job.collected_at || job.created_at;
 const timestamp = raw ? Date.parse(raw) : NaN;

 if (!Number.isFinite(timestamp)) {
  return period === 'all' && interval === 'all';
 }

 const collected = new Date(timestamp);
 const now = new Date();

 if (period === 'today') {
  const start = new Date(now);
  start.setHours(0,0,0,0);
  const end = new Date(start);
  end.setDate(end.getDate()+1);
  if (collected < start || collected >= end) return false;
 } else if (period === 'yesterday') {
  const end = new Date(now);
  end.setHours(0,0,0,0);
  const start = new Date(end);
  start.setDate(start.getDate()-1);
  if (collected < start || collected >= end) return false;
 } else if (period === '7days' && timestamp < now.getTime()-7*86400000) {
  return false;
 } else if (period === '30days' && timestamp < now.getTime()-30*86400000) {
  return false;
 } else if (period === 'custom') {
  if (dateFrom) {
   const start = new Date(`${dateFrom}T00:00:00`);
   if (collected < start) return false;
  }
  if (dateTo) {
   const end = new Date(`${dateTo}T00:00:00`);
   end.setDate(end.getDate()+1);
   if (collected >= end) return false;
  }
 }

 if (interval !== 'all') {
  const hours = Number(interval);
  if (!Number.isFinite(hours) || timestamp < now.getTime()-hours*3600000) {
   return false;
  }
 }

 return true;
}

function isITJob(job: Job) {
 const text = `${job.title} ${job.description} ${job.skills.join(' ')} ${job.role_category || ''}`.toLowerCase();
 return job.role_category === 'Full Stack' || job.role_category === 'Mobile' ||
  /\b(software|developer|développeur|developpeur|développement|informatique|engineer|ingénieur|ingenieur|programmer|programmeur|java|spring boot|spring batch|angular|react|vue\.js|javascript|typescript|php|laravel|symfony|flutter|dart|mobile|android|ios|kotlin|swift|devops|cloud|data engineer|cybersecurity|cybersécurité|qa engineer|test automation|database|base de données|api|full.?stack|backend|back.?end|frontend|front.?end|webmaster|système d'information|system administrator|administrateur système|it support|support informatique)\b/i.test(text);
}
function isSenegalJob(job: Job) {
 return /sénégal|senegal|dakar|pikine|thiès|thies|saint-louis|kaolack|ziguinchor/i.test(`${job.country} ${job.location}`);
}
function isInternationalMobilityJob(job: Job) {
 return !isSenegalJob(job) && (job.international_recruitment === true || job.relocation_supported === true);
}
function isUNNGOJob(job: Job) {
 const identity = `${job.company} ${job.title} ${job.source}`;
 const text = `${identity} ${job.description}`;
 const identityPattern = /\b(united nations|nations unies|onu|undp|pnud|unicef|unops|unhcr|hcr|who|oms|wfp|pam|unesco|fao|iom|oim|iaea|ilo|oit|world bank|banque mondiale|african development bank|banque africaine de développement|afdb|european union|union européenne|european commission|commission européenne|giz|afd|usaid|ngo|ong|ingo)\b/i;
 const fullNamePattern = /\b(united nations|nations unies|unicef|united nations development programme|united nations children's fund|international rescue committee|save the children|norwegian refugee council|conseil norvégien pour les réfugiés|care international|oxfam|plan international|médecins sans frontières|medecins sans frontieres|action contre la faim|humanity & inclusion|humanity and inclusion|solidarités international|solidarites international|world vision|danish refugee council|conseil danois pour les réfugiés|international organization for migration|organisation internationale pour les migrations|world health organization|organisation mondiale de la santé|world food programme|programme alimentaire mondial)\b/i;
 return identityPattern.test(identity) || fullNamePattern.test(text);
}

function classifyEmployer(job: Pick<Job, 'company' | 'title' | 'description'>) {
 const identity = `${job.company || ''} ${job.title || ''}`;
 const body = `${job.description || ''}`;

 const agencyIdentity = /\b(recruitment agency|staffing agency|employment agency|executive search|headhunter|cabinet de recrutement|agence de recrutement|intérim|interim agency|talent acquisition agency|recruitment consultant|consulting en recrutement)\b/i;
 const agencyEvidence = /\b(for our client|on behalf of our client|for one of our clients|pour le compte de notre client|pour l'un de nos clients|pour un de nos clients|recrutons pour notre client|recruiting on behalf of|recruitment agency|cabinet de recrutement|agence de recrutement)\b/i;
 const directEvidence = /\b(join our (?:own )?(?:internal )?team|join our engineering team|for our internal team|within our own team|directly employed by us|rejoindre nos équipes|rejoignez notre équipe|au sein de notre équipe|intégrer nos équipes|pour nos besoins internes|renforcer notre équipe interne)\b/i;

 const agency = agencyIdentity.test(identity) || agencyEvidence.test(body);
 const direct = directEvidence.test(body);

 if (agency && direct) return 'MIXTE';
 if (agency) return 'CABINET';
 if (direct) return 'EMPLOYEUR_DIRECT';
 return 'A_VERIFIER';
}

function App(){
 const [theme,setTheme]=useState<'light'|'dark'>(()=>{try{return localStorage.getItem('jobhunter-theme')==='dark'?'dark':'light'}catch{return 'light'}});
 useEffect(()=>{try{localStorage.setItem('jobhunter-theme',theme)}catch{}},[theme]);
 const [jobs,setJobs]=useState<Job[]>([]); const [stats,setStats]=useState<any>({total:0,statuses:{},countries:{},sources:{}}); const [syncStatus,setSyncStatus]=useState<SyncStatus|null>(null); const [syncing,setSyncing]=useState(false); const [q,setQ]=useState(''); const [country,setCountry]=useState(''); const [minScore,setMinScore]=useState(0); const [roleFilter,setRoleFilter]=useState(''); const [workFilter,setWorkFilter]=useState(''); const [mobilityFilter,setMobilityFilter]=useState(''); const [employerFilter,setEmployerFilter]=useState(''); const [showAdd,setShowAdd]=useState(false); const [form,setForm]=useState(emptyForm); const [busy,setBusy]=useState(false); const [error,setError]=useState(''); const [draft,setDraft]=useState<Draft|null>(null); const [draftJob,setDraftJob]=useState<Job|null>(null); const [tab,setTab]=useState<'offres'|'senegal'|'international'|'onu'|'suivi'|'doctorats'|'immigration'|'recruteurs'>('offres'); const [offersTab,setOffersTab]=useState<'recent'|'old'>('recent');
 const [collectionPeriod,setCollectionPeriod]=useState('all');
 const [collectionInterval,setCollectionInterval]=useState('all');
 const [dateFrom,setDateFrom]=useState(()=>localDateInput());
 const [dateTo,setDateTo]=useState(()=>localDateInput());
 async function load(){try{const [j,s,sy]=await Promise.all([fetch(`${API}/jobs`).then(r=>r.json()),fetch(`${API}/stats`).then(r=>r.json()),fetch(`${API}/sync/status`).then(r=>r.ok?r.json():null)]);setJobs(j);setStats(s);setSyncStatus(sy);setError('')}catch{setError('API indisponible. Démarrez le backend FastAPI (voir README).')}}
 async function runSync(){setSyncing(true);setError('');try{const r=await fetch(`${API}/sync/run`,{method:'POST'});const data=await r.json();if(!r.ok)throw new Error(data.detail||'La collecte a échoué.');await load()}catch(e:any){setError(e.message||'La collecte a échoué.')}finally{setSyncing(false)}}
 useEffect(()=>{load();const timer=window.setInterval(()=>{load()},60000);return()=>window.clearInterval(timer)},[]);
 const recentCount=jobs.filter(j=>isRecentJob(j)||!hasKnownJobDate(j)).length;
 const oldCount=jobs.filter(j=>!isRecentJob(j)||!hasKnownJobDate(j)).length;
  const dedicatedJobsTab = tab==='senegal' || tab==='international' || tab==='onu';
  const visible=useMemo(()=>jobs.filter(j=>
  (dedicatedJobsTab || (offersTab==='recent'?(isRecentJob(j)||!hasKnownJobDate(j)):(!isRecentJob(j)||!hasKnownJobDate(j)))) &&
  (dedicatedJobsTab || matchesCollectionFilters(j,collectionPeriod,collectionInterval,dateFrom,dateTo)) &&
  (tab!=='senegal' || (isITJob(j) && isSenegalJob(j))) &&
  (tab!=='international' || (isITJob(j) && isInternationalMobilityJob(j))) &&
  (tab!=='onu' || (isITJob(j) && isUNNGOJob(j))) &&
  (!q||`${j.title} ${j.company} ${j.description} ${j.skills.join(' ')}`.toLowerCase().includes(q.toLowerCase())) &&
  (!country||(country==='__SENEGAL__'?/sénégal|senegal/i.test(`${j.country} ${j.location}`):country==='__INTERNATIONAL__'?!/sénégal|senegal|non précisé|non precise/i.test(j.country||''):`${j.country} ${j.location}`.toLowerCase().includes(country.toLowerCase()))) &&
  (!roleFilter||j.role_category===roleFilter) &&
  (!employerFilter||classifyEmployer(j)===employerFilter) &&
  (!workFilter||j.remote_type===workFilter) &&
  (mobilityFilter!=='__RELOCATION__'||(j.international_recruitment&&j.relocation_supported)) &&
  (mobilityFilter!=='__INTERNATIONAL__'||j.international_recruitment) &&
  j.match_score>=minScore
 ).sort((a,b)=>{
   const scoreDiff = b.match_score - a.match_score;
   if (scoreDiff !== 0) return scoreDiff;
   const dateA = Date.parse(a.published_at || a.collected_at || a.created_at || '') || 0;
   const dateB = Date.parse(b.published_at || b.collected_at || b.created_at || '') || 0;
   return dateB - dateA;
 }),[jobs,q,country,minScore,roleFilter,workFilter,mobilityFilter,employerFilter,offersTab,collectionPeriod,collectionInterval,dateFrom,dateTo,tab,dedicatedJobsTab]);
 async function addJob(e:FormEvent){e.preventDefault();setBusy(true);try{const res=await fetch(`${API}/jobs`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...form,skills:form.skills.split(',').map(x=>x.trim()).filter(Boolean)})});if(!res.ok)throw new Error('Vérifiez les champs du formulaire.');setForm(emptyForm);setShowAdd(false);await load()}catch(e:any){setError(e.message||'Erreur pendant l’ajout.')}finally{setBusy(false)}}
 async function removeJob(id:number){if(!confirm('Supprimer cette offre ?'))return;await fetch(`${API}/jobs/${id}`,{method:'DELETE'});await load()}
 async function makeDraft(job:Job){setDraftJob(job);setBusy(true);try{const r=await fetch(`${API}/drafts`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:job.id})});if(!r.ok)throw new Error('Impossible de préparer la candidature');setDraft(await r.json())}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 async function updateStatus(job:Job,status:string){await fetch(`${API}/jobs/${job.id}/application`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status,notes:job.notes||''})});await load()}
 const tracked=jobs.filter(j=>j.status&&j.status!=='À examiner');
 return <div className="app-shell" data-theme={theme}><aside className="sidebar"><div className="brand"><div className="brand-icon"><Sparkles size={20}/></div><div><b>JobHunter <span>AI</span></b><small>Career workspace</small></div></div><div className="workspace-label">ESPACE PERSONNEL</div><button className={`nav-item ${tab==='offres'?'active':''}`} onClick={()=>setTab('offres')}><BriefcaseBusiness size={18}/> Toutes les offres <span className="nav-count">{jobs.length}</span></button>
<button className={`nav-item ${tab==='senegal'?'active':''}`} onClick={()=>{setTab('senegal');setQ('');setCountry('');setRoleFilter('');setWorkFilter('');setMobilityFilter('');setMinScore(0);setCollectionPeriod('all');setCollectionInterval('all')}}><MapPin size={18}/> Informatique au Sénégal</button>
<button className={`nav-item ${tab==='international'?'active':''}`} onClick={()=>{setTab('international');setQ('');setCountry('');setRoleFilter('');setWorkFilter('');setMobilityFilter('');setMinScore(0);setCollectionPeriod('all');setCollectionInterval('all')}}><ExternalLink size={18}/> International & mobilité</button>
<button className={`nav-item ${tab==='onu'?'active':''}`} onClick={()=>{setTab('onu');setQ('');setCountry('');setRoleFilter('');setWorkFilter('');setMobilityFilter('');setMinScore(0);setCollectionPeriod('all');setCollectionInterval('all')}}><ShieldCheck size={18}/> ONU, ONG & organisations</button>
<button className={`nav-item ${tab==='suivi'?'active':''}`} onClick={()=>setTab('suivi')}><ChartNoAxesCombined size={18}/> Suivi candidatures</button>
<button className={`nav-item ${tab==='doctorats'?'active':''}`} onClick={()=>setTab('doctorats')}><GraduationCap size={18}/> Opportunités académiques</button>
<button className={`nav-item ${tab==='immigration'?'active':''}`} onClick={()=>setTab('immigration')}><Globe2 size={18}/> Immigration & programmes légaux</button>
<button className={`nav-item ${tab==='recruteurs'?'active':''}`} onClick={()=>setTab('recruteurs')}><Users size={18}/> Recruteurs internationaux</button><div className="sidebar-bottom"><div className="local-card"><ShieldCheck size={18}/><div><b>Mode local</b><small>Vos données restent sur cette machine.</small></div></div><div className="profile"><div className="avatar">FN</div><div><b>Fallou Ndiaye</b><small>Full Stack Engineer</small></div></div></div></aside>
 <main className="main"><header className="topbar"><div><span className="eyebrow">VOTRE ESPACE CARRIÈRE</span><h1>{tab==='offres'?'Toutes les offres d’emploi':tab==='senegal'?'Emplois informatiques au Sénégal':tab==='international'?'Recrutements internationaux avec mobilité':tab==='onu'?'Informatique · ONU, ONG & organisations':tab==='suivi'?'Suivi des candidatures':tab==='immigration'?'Immigration & programmes légaux':tab==='recruteurs'?'Recruteurs internationaux':'Opportunités académiques'}</h1><p>{tab==='offres'?'Toutes les offres déjà collectées, sans remplacer votre historique.':tab==='senegal'?'Postes IT au Sénégal : développement web, logiciel, mobile, données, cloud et systèmes.':tab==='international'?'Priorité aux annonces informatiques explicitement signalées comme recrutement international ou mobilité. Le visa et le financement restent à vérifier dans l’annonce officielle.':tab==='onu'?'Postes informatiques repérés auprès de l’ONU, de ses agences, d’ONG et d’organisations internationales. La mobilité n’est confirmée que si l’annonce le précise.':tab==='suivi'?'Gardez une vue claire sur les candidatures préparées et les prochaines étapes.':tab==='immigration'?'Parcours migratoires officiels, visas de travail et immigration qualifiée. Les critères et le parrainage doivent être vérifiés auprès des autorités.':tab==='recruteurs'?'Répertoire de recruteurs internationaux, contacts professionnels publics et offres reliées à leurs sources.':'Explorez les doctorats, bourses, aides et postes de recherche, puis suivez vos candidatures.'}</p></div><div className="topbar-actions"><button className="theme-toggle" onClick={()=>setTheme(theme==='light'?'dark':'light')} aria-label={theme==='light'?'Activer le mode sombre':'Activer le mode clair'} title={theme==='light'?'Mode sombre':'Mode clair'}>{theme==='light'?<Moon size={17}/>:<Sun size={17}/>}<span>{theme==='light'?'Mode sombre':'Mode clair'}</span></button>{tab!=='doctorats'&&tab!=='immigration'&&tab!=='recruteurs'&&<button className="btn btn-primary" onClick={()=>setShowAdd(true)}><Plus size={17}/> Ajouter une offre</button>}</div></header>
 {error&&<div className="error-banner">{error}<button onClick={()=>setError('')}><X size={16}/></button></div>}
 <section className="stats-grid"><div className="stat-card"><div className="stat-icon purple"><BriefcaseBusiness size={18}/></div><span>Offres collectées</span><strong>{stats.total||0}</strong><small>Dans votre espace local</small></div><div className="stat-card"><div className="stat-icon green"><Sparkles size={18}/></div><span>Matching ≥ 70%</span><strong>{jobs.filter(j=>j.match_score>=70).length}</strong><small>Priorités potentielles</small></div><div className="stat-card"><div className="stat-icon orange"><FileText size={18}/></div><span>Candidatures suivies</span><strong>{tracked.length}</strong><small>Avec un statut défini</small></div><div className="stat-card"><div className="stat-icon blue"><ChartNoAxesCombined size={18}/></div><span>Sources présentes dans les offres</span><strong>{Object.keys(stats.sources||{}).length}</strong><small>Sources ayant au moins une offre</small></div></section>
 <section className="sync-panel"><div className="sync-intro"><div className="sync-icon"><RefreshCw size={19}/></div><div><div className="sync-title-row"><h2>Collecte automatique</h2><span className={`sync-state ${syncStatus?.auto_sync_enabled?'sync-on':'sync-off'}`}>{syncStatus?.auto_sync_enabled?'Automatique activée':'Automatique désactivée'}</span></div><p>Offres réelles depuis des API publiques et des pages carrière autorisées. Synchronisation toutes les {syncStatus?.interval_minutes||60} min.</p><small>{syncStatus?.last_run?.finished_at?`Dernière synchronisation : ${new Date(syncStatus.last_run.finished_at).toLocaleString('fr-FR')}`:'Première synchronisation en cours ou pas encore exécutée'}{syncStatus?.last_run?` · ${syncStatus.last_run.inserted||0} nouvelle(s) offre(s) à la dernière collecte`:''}</small></div></div><button className="btn btn-primary" onClick={runSync} disabled={syncing}>{syncing?<span className="spin"><RefreshCw size={16}/></span>:<RefreshCw size={16}/>} {syncing?'Collecte en cours…':'Collecter maintenant'}</button></section>
 {syncStatus?.last_run?.sources&&<div className="source-health">{(Object.entries(syncStatus.last_run.sources) as [string,{received:number;error?:string|null;enabled?:boolean}][]).map(([name,info])=><span className={`source-chip ${info.error?'source-error':info.enabled===false?'source-disabled':'source-ok'}`} key={name}><i/> {name} · {info.error?'erreur':info.enabled===false?'non configurée':`${info.received} offres lues`}</span>)}</div>}
 {['offres','senegal','international','onu'].includes(tab)?<>{tab!=='offres'&&<section className="jobhunter-module-banner"><b>{tab==='senegal'?'Filtre métier : informatique au Sénégal':tab==='international'?'Filtre mobilité : recrutement international / relocalisation explicitement signalé':'Filtre organisations : ONU, agences, ONG et institutions internationales'}</b><p>{tab==='senegal'?'Cette vue est calculée à partir des offres déjà présentes dans votre base ; elle ne lance aucune collecte.':tab==='international'?'Les annonces sans preuve explicite de mobilité ne sont pas présentées comme financées ou sponsorisées.':'Vérifiez l’éligibilité, le type de contrat, le visa et la prise en charge dans la source officielle avant de candidater.'}</p><span>{visible.length} offre(s) correspondant aux critères dans votre base actuelle</span></section>}<section className="toolbar"><div className="searchbox"><Search size={18}/><input value={q} onChange={e=>setQ(e.target.value)} placeholder="Titre, entreprise, compétence…"/></div><select aria-label="Zone géographique" value={country} onChange={e=>setCountry(e.target.value)}><option value="">Tous les pays</option><option value="__SENEGAL__">Sénégal</option><option value="__INTERNATIONAL__">International</option>{['France','Canada','Québec','Maroc','Luxembourg','Remote'].map(x=><option key={x}>{x}</option>)}</select><select aria-label="Métier" value={roleFilter} onChange={e=>setRoleFilter(e.target.value)}><option value="">Tous les métiers</option><option value="Full Stack">Développeur Full Stack</option><option value="Mobile">Développeur mobile</option></select><select aria-label="Mode de travail" value={workFilter} onChange={e=>setWorkFilter(e.target.value)}><option value="">Tous les modes</option><option value="Remote">Télétravail complet</option><option value="Hybride">Hybride</option><option value="Sur site">Sur site</option><option value="À vérifier">Mode à vérifier</option></select><select aria-label="Type d’employeur" value={employerFilter} onChange={e=>setEmployerFilter(e.target.value)}><option value="">Tous les employeurs</option><option value="EMPLOYEUR_DIRECT">Employeur direct identifié</option><option value="CABINET">Cabinet identifié</option><option value="MIXTE">Recrutement mixte</option><option value="A_VERIFIER">Employeur à vérifier</option></select><select aria-label="Mobilité internationale" value={mobilityFilter} onChange={e=>setMobilityFilter(e.target.value)}><option value="">Toute mobilité</option><option value="__INTERNATIONAL__">Recrutement international</option><option value="__RELOCATION__">Déplacement / visa pris en charge</option></select><select value={minScore} onChange={e=>setMinScore(Number(e.target.value))}><option value={0}>Tous les scores</option><option value={50}>Matching ≥ 50%</option><option value={70}>Matching ≥ 70%</option><option value={85}>Matching ≥ 85%</option></select><button className="btn btn-ghost" onClick={load}><RefreshCw size={16}/> Actualiser</button></section><section className="date-filters" aria-label="Filtres de collecte">
 <label className="date-filter-field">Date de collecte
  <select aria-label="Période de collecte" value={collectionPeriod} onChange={e=>setCollectionPeriod(e.target.value)}>
   <option value="today">Aujourd'hui</option>
   <option value="yesterday">Hier</option>
   <option value="7days">7 derniers jours</option>
   <option value="30days">30 derniers jours</option>
   <option value="custom">Intervalle personnalisé</option>
   <option value="all">Toutes les dates</option>
  </select>
 </label>
 {collectionPeriod==='custom'&&<>
  <label className="date-filter-field">Du
   <input aria-label="Date de début" type="date" value={dateFrom} max={dateTo||undefined} onChange={e=>setDateFrom(e.target.value)}/>
  </label>
  <label className="date-filter-field">Au
   <input aria-label="Date de fin" type="date" value={dateTo} min={dateFrom||undefined} onChange={e=>setDateTo(e.target.value)}/>
  </label>
 </>}
 <label className="date-filter-field">Intervalle de collecte
  <select aria-label="Intervalle de collecte" value={collectionInterval} onChange={e=>setCollectionInterval(e.target.value)}>
   <option value="all">Toutes les collectes</option>
   <option value="24">Dernières 24 heures</option>
   <option value="48">Dernières 48 heures</option>
   <option value="72">Dernières 72 heures</option>
  </select>
 </label>
 <button type="button" className="btn btn-ghost date-reset" onClick={()=>{setCollectionPeriod('today');setCollectionInterval('all');setDateFrom(localDateInput());setDateTo(localDateInput())}}>Réinitialiser les dates</button>
</section>
<div className="offer-tabs" role="tablist" aria-label="Ancienneté des offres">
 <button type="button" role="tab" aria-selected={offersTab==='recent'} className={offersTab==='recent'?'offer-tab active':'offer-tab'} onClick={()=>setOffersTab('recent')}>Récentes (7 jours) <span>{recentCount}</span></button>
 <button type="button" role="tab" aria-selected={offersTab==='old'} className={offersTab==='old'?'offer-tab active':'offer-tab'} onClick={()=>setOffersTab('old')}>Anciennes <span>{oldCount}</span></button>
</div>
<div className="section-heading"><div><h2>{offersTab==='recent'?'Offres récentes':'Anciennes offres'}</h2><p>{visible.length} résultat(s) · score indicatif expliqué selon le métier, les compétences et la localisation</p></div><span className="pill">MVP local</span></div>
 <div className="job-list">{visible.map(job=><article className="job-card" key={job.id}><div className="company-mark">{job.company.slice(0,2).toUpperCase()}</div><div className="job-content"><div className="job-topline"><span className="source-label">{job.source||'Source inconnue'}</span><span className={`score ${job.match_score>=70?'high':job.match_score>=45?'medium':'low'}`}><Sparkles size={13}/>{job.match_score}% match</span></div><h3>{job.title}</h3><div className="company-line">{job.company}<span>·</span><MapPin size={14}/>{job.location||job.country}</div><div className="tags"><span>{classifyEmployer(job)==='CABINET'?'Cabinet identifié · vérifier le client':classifyEmployer(job)==='EMPLOYEUR_DIRECT'?'Employeur direct probable · vérifier la source':classifyEmployer(job)==='MIXTE'?'Recrutement mixte · vérifier le contexte':'Employeur à vérifier'}</span><span>{job.contract_type||'Contrat à préciser'}</span><span>{job.work_mode||'Mode à préciser'}</span>{job.role_category&&job.role_category!=='Autre'&&<span>{job.role_category==='Mobile'?'Développeur mobile':'Développeur Full Stack'}</span>}{job.international_recruitment&&<span>International</span>}{job.relocation_supported&&<span className="mobility-tag">Mobilité annoncée</span>}{job.skills.slice(0,4).map(s=><span className="skill-tag" key={s}>{s}</span>)}</div><p className="job-description">{job.description||'Aucune description ajoutée. Consultez l’annonce originale pour plus de détails.'}</p>{job.international_recruitment&&<p className="relocation-note">{job.relocation_supported?'Prise en charge de la mobilité mentionnée dans l’annonce : vérification humaine recommandée.':'Recrutement international potentiel · prise en charge du déplacement/visa non confirmée.'}</p>}<div className="job-meta"><span>Publication : {job.published_at?new Date(job.published_at).toLocaleDateString('fr-FR'):'date non fournie par la source'}</span><span>Collectée : {job.collected_at?new Date(job.collected_at).toLocaleDateString('fr-FR'):'—'}</span></div>{(job.match_reasons?.length ?? 0)>0&&<details className="match-details"><summary>Pourquoi {job.match_score}% ? Voir les raisons</summary><ul>{job.match_reasons?.map((reason,i)=><li key={i}>{reason}</li>)}</ul>{(job.missing_skills?.length ?? 0)>0&&<p><b>Compétences non détectées dans l’annonce :</b> {job.missing_skills?.join(', ')}</p>}</details>}<div className="job-actions"><button className="btn btn-primary btn-small" onClick={()=>makeDraft(job)} disabled={busy}><Sparkles size={14}/> Préparer candidature</button>{job.url&&<a className="btn btn-ghost btn-small" href={job.url} target="_blank" rel="noreferrer">Voir l’offre <ExternalLink size={14}/></a>}<button type="button" className={job.status==='Candidature envoyée'?'btn btn-small applied-button':'btn btn-ghost btn-small'} onClick={()=>updateStatus(job,'Candidature envoyée')} disabled={busy||job.status==='Candidature envoyée'}><CheckCircle2 size={14}/>{job.status==='Candidature envoyée'?'Candidature envoyée':'Marquer comme postulé'}</button><select aria-label="Statut candidature" value={job.status||'À examiner'} onChange={e=>updateStatus(job,e.target.value)}>{['À examiner','À candidater','Candidature préparée','Candidature envoyée','Entretien','Refus','Acceptée'].map(s=><option key={s}>{s}</option>)}</select><button className="icon-btn danger" title="Supprimer" onClick={()=>removeJob(job.id)}><Trash2 size={15}/></button></div></div></article>)}{visible.length===0&&<div className="empty-state"><div className="empty-icon"><Search size={24}/></div><h3>Aucune offre ne correspond à ces filtres</h3><p>Essayez d’élargir les filtres, ou lancez une collecte pour importer de nouvelles annonces depuis les sources connectées.</p><button className="btn btn-ghost" onClick={runSync} disabled={syncing}><RefreshCw size={16}/> {syncing?'Collecte en cours…':'Lancer une collecte'}</button><button className="btn btn-primary" onClick={()=>setShowAdd(true)}><Plus size={16}/> Ajouter une première offre</button></div>}</div></>:tab==='doctorats'?<DoctoratesPanel apiBase={API}/>:tab==='immigration'?<ImmigrationPanel apiBase={API}/>:tab==='recruteurs'?<RecruitersPanel apiBase={API}/>:<section className="tracking-panel"><h2>Vos candidatures en cours</h2>{tracked.length?tracked.map(j=><div className="tracking-row" key={j.id}><div><b>{j.title}</b><small>{j.company} · {j.country}</small></div><select value={j.status} onChange={e=>updateStatus(j,e.target.value)}>{['À examiner','À candidater','Candidature préparée','Candidature envoyée','Entretien','Refus','Acceptée'].map(s=><option key={s}>{s}</option>)}</select><span className="score high">{j.match_score}%</span></div>):<div className="empty-state"><h3>Aucune candidature suivie</h3><p>Choisissez un statut sur une offre pour la retrouver ici.</p><button className="btn btn-primary" onClick={()=>setTab('offres')}>Voir les offres</button></div>}</section>}
 <footer><span>JobHunter AI · MVP 0.1</span><span><ShieldCheck size={14}/> Validation humaine obligatoire avant envoi</span></footer></main>
 {showAdd&&<div className="modal-backdrop" onClick={()=>setShowAdd(false)}><div className="modal" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><h2>Ajouter une offre</h2><p>Copiez les détails d’une annonce issue d’une source autorisée.</p></div><button className="icon-btn" onClick={()=>setShowAdd(false)}><X size={18}/></button></div><form onSubmit={addJob} className="job-form"><label>Titre du poste *<input required minLength={2} value={form.title} onChange={e=>setForm({...form,title:e.target.value})} placeholder="Développeur Java / Spring Boot"/></label><label>Entreprise *<input required value={form.company} onChange={e=>setForm({...form,company:e.target.value})} placeholder="Nom de l’entreprise"/></label><div className="form-row"><label>Pays<input value={form.country} onChange={e=>setForm({...form,country:e.target.value})}/></label><label>Ville / localisation<input value={form.location} onChange={e=>setForm({...form,location:e.target.value})} placeholder="Dakar, Paris, Remote…"/></label></div><div className="form-row"><label>Contrat<select value={form.contract_type} onChange={e=>setForm({...form,contract_type:e.target.value})}>{['CDI','CDD','Freelance','Stage','Alternance','Mission','Non précisé'].map(x=><option key={x}>{x}</option>)}</select></label><label>Mode de travail<select value={form.work_mode} onChange={e=>setForm({...form,work_mode:e.target.value})}>{['Hybride','Télétravail','Sur site','Flexible','Non précisé'].map(x=><option key={x}>{x}</option>)}</select></label></div><label>Compétences (séparées par des virgules)<input value={form.skills} onChange={e=>setForm({...form,skills:e.target.value})} placeholder="Java, Spring Boot, Angular, PostgreSQL"/></label><label>URL de l’offre<input type="url" value={form.url} onChange={e=>setForm({...form,url:e.target.value})} placeholder="https://…"/></label><label>Description<textarea rows={4} value={form.description} onChange={e=>setForm({...form,description:e.target.value})} placeholder="Missions, compétences, expérience requise…"/></label><div className="modal-actions"><button type="button" className="btn btn-ghost" onClick={()=>setShowAdd(false)}>Annuler</button><button className="btn btn-primary" disabled={busy}>{busy?'Enregistrement…':'Enregistrer l’offre'}</button></div></form></div></div>}
 {draft&&draftJob&&<div className="modal-backdrop" onClick={()=>{setDraft(null);setDraftJob(null)}}><div className="modal draft-modal" onClick={e=>e.stopPropagation()}><div className="modal-head"><div><span className="eyebrow">ASSISTANT DE CANDIDATURE</span><h2>{draftJob.title}</h2><p>{draftJob.company} · Brouillon à personnaliser</p></div><button className="icon-btn" onClick={()=>{setDraft(null);setDraftJob(null)}}><X size={18}/></button></div><div className="human-check"><ShieldCheck size={18}/><div><b>Validation humaine obligatoire</b><p>{draft.warning}</p></div></div><div className="cv-recommendation"><FileText size={17}/><div><b>CV recommandé : {draft.language==='en'?'English CV':'CV français'}</b><small>Vérifiez que le document est à jour avant de l’envoyer.</small></div><a className="btn btn-ghost btn-small" href={draft.language==='en'?'/cv/CV_Fallou_Ndiaye_EN.pdf':'/cv/CV_Fallou_Ndiaye_FR.pdf'} target="_blank" rel="noreferrer">Ouvrir le CV <ExternalLink size={13}/></a></div><label>Objet de l’email<div className="copy-field">{draft.subject}<button onClick={()=>navigator.clipboard?.writeText(draft.subject)}>Copier</button></div></label><label>Email de candidature<textarea rows={7} readOnly value={draft.email}/></label><button className="btn btn-ghost" onClick={()=>navigator.clipboard?.writeText(draft.email)}>Copier l’email</button><label>Lettre de motivation<textarea rows={10} readOnly value={draft.letter}/></label><div className="modal-actions"><button className="btn btn-ghost" onClick={()=>navigator.clipboard?.writeText(draft.letter)}>Copier la lettre</button><button className="btn btn-primary" onClick={()=>{updateStatus(draftJob,'Candidature préparée');setDraft(null);setDraftJob(null)}}>Marquer comme préparée</button></div><p className="fine-print">Cette version ne se connecte à aucune boîte mail et n’envoie aucune candidature. Vérifiez les faits et adaptez le contenu avant tout usage.</p></div></div>}
 </div>
}
export default App;
