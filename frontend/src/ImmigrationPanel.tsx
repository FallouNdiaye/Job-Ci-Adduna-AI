import { useEffect, useMemo, useState } from 'react';
import {
  ArrowUpRight, BriefcaseBusiness, CheckCircle2, Globe2,
  Search, ShieldCheck, GraduationCap, CalendarDays, Wallet, MapPin
} from 'lucide-react';

type Route = {
  id: string;
  country: string;
  title: string;
  category: string;
  offer: string;
  sponsorship: string;
  summary: string;
  requirements: string;
  url: string;
};

const fallbackRoutes: Route[] = [
  {
    id: 'germany-opportunity',
    country: 'Allemagne',
    title: 'Chancenkarte — carte des opportunités',
    category: 'Recherche d’emploi sans offre préalable',
    offer: 'Pas nécessaire au départ',
    sponsorship: 'Pas de parrainage employeur initial',
    summary: 'Permet, sous conditions, de venir chercher un emploi qualifié en Allemagne.',
    requirements: 'Vérifier la reconnaissance du diplôme ou les critères du système à points, les langues et les ressources financières.',
    url: 'https://www.make-it-in-germany.com/en/visa-residence/opportunity-card'
  },
  {
    id: 'canada-express-entry',
    country: 'Canada',
    title: 'Express Entry — immigration qualifiée',
    category: 'Résidence permanente',
    offer: 'Pas systématiquement nécessaire',
    sponsorship: 'Parcours indépendant de l’employeur selon le programme',
    summary: 'Système fédéral qui gère plusieurs programmes d’immigration économique qualifiée.',
    requirements: 'Vérifier le programme admissible, les tests linguistiques, l’évaluation des diplômes, l’expérience et les fonds. Une invitation n’est pas garantie.',
    url: 'https://www.canada.ca/en/immigration-refugees-citizenship/services/immigrate-canada/express-entry.html'
  },
  {
    id: 'eu-blue-card',
    country: 'Union européenne',
    title: 'Carte bleue européenne',
    category: 'Emploi hautement qualifié',
    offer: 'Généralement nécessaire',
    sponsorship: 'Contrat ou offre admissible selon le pays',
    summary: 'Voie de séjour et de travail pour certains travailleurs hautement qualifiés hors UE.',
    requirements: 'Les conditions de diplôme, de rémunération, de contrat et les démarches dépendent du pays de destination.',
    url: 'https://home-affairs.ec.europa.eu/policies/migration-and-asylum/eu-immigration-portal/eu-blue-card_en'
  },
  {
    id: 'france-talent',
    country: 'France',
    title: 'Passeport talent',
    category: 'Travail qualifié et talents internationaux',
    offer: 'Contrat ou situation admissible généralement requis',
    sponsorship: 'À vérifier selon la catégorie',
    summary: 'Plusieurs catégories permettent à des profils qualifiés de séjourner et travailler en France.',
    requirements: 'Les critères varient selon la catégorie, le contrat, la rémunération et la situation professionnelle.',
    url: 'https://www.france-visas.gouv.fr/web/france-visas/talents-internationaux-et-attractivite-economique'
  },
  {
    id: 'netherlands-skilled',
    country: 'Pays-Bas',
    title: 'Highly skilled migrant',
    category: 'Emploi qualifié',
    offer: 'Contrat de travail requis',
    sponsorship: 'Employeur reconnu par l’IND requis',
    summary: 'Parcours de séjour professionnel reposant sur un employeur sponsor reconnu.',
    requirements: 'Vérifier le statut de sponsor de l’employeur, le salaire minimal applicable et les conditions en vigueur.',
    url: 'https://ind.nl/en/residence-permits/work/highly-skilled-migrant'
  },
  {
    id: 'us-employment-green-card',
    country: 'États-Unis',
    title: 'Green Card — immigration fondée sur l’emploi',
    category: 'Résidence permanente',
    offer: 'Souvent requise, selon la catégorie',
    sponsorship: 'Souvent une procédure employeur ; exceptions selon la catégorie',
    summary: 'Plusieurs catégories permettent de demander la résidence permanente sur une base professionnelle.',
    requirements: 'Les critères, les éventuelles certifications de travail et les possibilités de pétition personnelle dépendent de la catégorie.',
    url: 'https://www.uscis.gov/green-card/green-card-eligibility/green-card-for-employment-based-immigrants'
  },

  {
    id: 'ireland-critical-skills',
    country: 'Irlande',
    title: 'Critical Skills Employment Permit',
    category: 'Permis de travail qualifié',
    offer: 'Offre d’emploi admissible requise',
    sponsorship: 'Employeur et critères officiels requis',
    summary: 'Permis destiné à certains métiers qualifiés en pénurie, dont des professions informatiques admissibles.',
    requirements: 'Vérifier la profession exacte dans la liste officielle, le diplôme si exigé, la rémunération minimale et les conditions du contrat.',
    url: 'https://enterprise.gov.ie/en/what-we-do/workplace-and-skills/employment-permits/permit-types/critical-skills-employment-permit/'
  },
  {
    id: 'canada-foreign-candidates',
    country: 'Canada',
    title: 'Job Bank — emplois ouverts aux candidats étrangers',
    category: 'Portail officiel de recherche d’emploi',
    offer: 'Offres ouvertes aux candidats internationaux uniquement',
    sponsorship: 'Permis et conditions à vérifier',
    summary: 'Portail canadien permettant de repérer les offres qui acceptent les candidatures de l’étranger.',
    requirements: 'Vérifier l’annonce, l’employeur, les compétences requises et la procédure de permis. Une annonce ne garantit pas un visa.',
    url: 'https://www.jobbank.gc.ca/findajob/foreign-candidates'
  },
  {
    id: 'canada-work-permit-outside',
    country: 'Canada',
    title: 'Permis de travail — demande depuis l’étranger',
    category: 'Autorisation de travail temporaire',
    offer: 'Souvent requise pour un permis lié à un employeur',
    sponsorship: 'Dépend du type de permis',
    summary: 'Guide officiel pour vérifier les conditions et déposer une demande depuis l’extérieur du Canada.',
    requirements: 'Déterminer le type de permis, les exigences propres au programme et les documents nécessaires.',
    url: 'https://www.canada.ca/en/immigration-refugees-citizenship/services/work-canada/permit-outside.html'
  },
  {
    id: 'us-diversity-visa',
    country: 'États-Unis',
    title: 'Diversity Visa — loterie de résidence permanente',
    category: 'Loterie annuelle d’immigration',
    offer: 'Pas d’offre d’emploi exigée pour participer',
    sponsorship: 'Pas de sponsor employeur initial',
    summary: 'Programme annuel distinct de la Green Card fondée sur l’emploi.',
    requirements: 'Vérifier les pays admissibles, les critères de formation ou d’expérience et les dates officielles. La sélection ne garantit pas un visa ; l’inscription officielle est gratuite.',
    url: 'https://travel.state.gov/content/travel/en/us-visas/immigrate/diversity-visa-program-entry/diversity-visa-instructions.html'
  },
  {
    id: 'us-h1b',
    country: 'États-Unis',
    title: 'H-1B — emploi spécialisé',
    category: 'Visa temporaire de travail',
    offer: 'Offre d’un employeur américain généralement requise',
    sponsorship: 'Pétition employeur généralement nécessaire',
    summary: 'Voie temporaire pour certains emplois spécialisés répondant aux conditions du programme.',
    requirements: 'Vérifier la qualification du poste, les diplômes ou équivalences, la pétition employeur, les règles de sélection et les exigences en vigueur. Ce visa n’est pas une Green Card.',
    url: 'https://www.uscis.gov/working-in-the-united-states/temporary-workers/h-1b-specialty-occupations'
  },
  {
    id: 'us-l1b-intracompany',
    country: 'États-Unis',
    title: 'L-1B — transfert intragroupe de connaissances spécialisées',
    category: 'Mobilité interne internationale',
    offer: 'Transfert proposé par une entreprise admissible',
    sponsorship: 'Employeur et relation entre entités du groupe requis',
    summary: 'Piste à étudier si une multinationale au Sénégal possède une entité américaine admissible et propose un transfert interne.',
    requirements: 'Vérifier la relation entre les entités, l’emploi spécialisé, l’ancienneté à l’étranger exigée et les autres conditions USCIS. La mobilité interne n’est jamais automatique.',
    url: 'https://www.uscis.gov/working-in-the-united-states/temporary-workers/l-1b-intracompany-transferee-specialized-knowledge'
  },
  {
    id: 'germany-job-listings',
    country: 'Allemagne',
    title: 'Make it in Germany — offres d’emploi',
    category: 'Portail officiel de recherche d’emploi',
    offer: 'Consulter les annonces et vérifier le recrutement international',
    sponsorship: 'À vérifier auprès de l’employeur',
    summary: 'Portail officiel pour rechercher des emplois en Allemagne, complémentaire à la Chancenkarte.',
    requirements: 'Vérifier la langue demandée, la reconnaissance des qualifications, le lieu de travail et la voie de séjour adaptée.',
    url: 'https://www.make-it-in-germany.com/en/working-in-germany/job-listings'
  },

];

const updatedLabel = new Intl.DateTimeFormat('fr-FR', {
  dateStyle: 'long'
}).format(new Date());

type ApiRoute = {
  id: string;
  country: string;
  title: string;
  category: string;
  offer_note: string;
  sponsorship_status: string;
  summary: string;
  requirements: string;
  official_url: string;
};

type Props = { apiBase: string };

function sponsorshipLabel(route: ApiRoute): string {
  switch (route.id) {
    case 'germany-opportunity':
      return 'Pas de parrainage employeur initial';
    case 'canada-express-entry':
      return 'Parcours indépendant de l’employeur selon le programme';
    case 'eu-blue-card':
      return 'Contrat ou offre admissible selon le pays';
    case 'france-talent':
      return 'À vérifier selon la catégorie';
    case 'netherlands-skilled':
      return 'Employeur reconnu par l’IND requis';
    case 'us-employment-green-card':
      return 'Souvent une procédure employeur ; exceptions selon la catégorie';
    case 'ireland-critical-skills':
      return 'Offre admissible et critères officiels requis';
    case 'canada-foreign-candidates':
      return 'Vérifier l’ouverture aux candidats étrangers et le permis';
    case 'canada-work-permit-outside':
      return 'Conditions dépendant du type de permis';
    case 'us-diversity-visa':
      return 'Inscription pendant la période officielle ; sélection non garantie';
    case 'us-h1b':
      return 'Pétition employeur généralement nécessaire';
    case 'us-l1b-intracompany':
      return 'Transfert intragroupe et conditions USCIS requis';
    case 'germany-job-listings':
      return 'Conditions de recrutement international à vérifier';
    default:
      return route.sponsorship_status.replaceAll('_', ' ').toLocaleLowerCase('fr');
  }
}


type MobilityJob = {
  id: number;
  title: string;
  company: string;
  country: string;
  location?: string;
  work_mode?: string;
  contract_type?: string;
  description?: string;
  url?: string;
  source?: string;
  skills?: string[];
  role_category?: string;
  remote_type?: string;
  international_recruitment?: boolean;
  relocation_supported?: boolean;
  relocation_evidence?: string;
  published_at?: string | null;
  collected_at?: string | null;
  match_score?: number;
};

type MobilityFunding = {
  id: number;
  title: string;
  institution?: string;
  country?: string;
  location?: string;
  field?: string;
  description?: string;
  url?: string;
  source?: string;
  funding_status?: string;
  funding_type?: string;
  funding_evidence?: string;
  salary_amount?: number | null;
  salary_currency?: string;
  salary_period?: string;
  deadline?: string | null;
  eligibility?: string;
  tuition_status?: string;
  opportunity_type?: string;
};

type Section = 'jobs' | 'procedures' | 'funding';

function displayDate(value?: string | null): string {
  if (!value) return 'Non précisée par la source';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('fr-FR', {
        day: '2-digit', month: 'short', year: 'numeric'
      });
}

function salaryFromDescription(description?: string): string {
  if (!description) return 'Non précisé par la source';
  const patterns = [
    /(?:salary|salary range|compensation|remuneration|rémunération|salaire)[^\n]{0,35}(?:€|EUR|USD|\$|GBP|£|CAD|CHF|XOF|CFA)\s?[\d.,]+(?:\s?[-–à]\s?(?:€|EUR|USD|\$|GBP|£|CAD|CHF|XOF|CFA)?\s?[\d.,]+)?/i,
    /(?:€|USD|\$|GBP|£|CAD|CHF|XOF|CFA)\s?[\d.,]+\s?(?:per year|\/year|\/an|annuel|annuellement|per month|\/month|\/mois|hourly|\/hour|\/heure)?/i
  ];
  for (const pattern of patterns) {
    const match = description.match(pattern);
    if (match) return match[0].replace(/\s+/g, ' ').trim();
  }
  return 'Non précisé par la source';
}

function deadlineFromDescription(description?: string): string {
  if (!description) return 'Non précisée par la source';
  const match = description.match(
    /(?:application deadline|deadline|apply by|date limite|candidatures jusqu'au|closing date)\s*[:\-]?\s*([^\n<]{3,55})/i
  );
  return match?.[1]?.trim().replace(/[.;]+$/, '') || 'Non précisée par la source';
}

function fundingStatusLabel(status?: string): string {
  switch ((status || '').toUpperCase()) {
    case 'CONFIRMED_FULL': return 'Financement intégral annoncé';
    case 'PARTIAL': return 'Financement partiel';
    case 'UNCONFIRMED': return 'Financement à vérifier';
    case 'UNKNOWN': return 'Financement inconnu';
    default: return status || 'Statut non précisé';
  }
}

export default function ImmigrationPanel({ apiBase }: Props) {
  const [section, setSection] = useState<Section>('jobs');
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState('');
  const [pathType, setPathType] = useState('');
  const [routes, setRoutes] = useState<Route[]>(fallbackRoutes);
  const [dataSource, setDataSource] = useState('Catalogue local de secours');
  const [jobs, setJobs] = useState<MobilityJob[]>([]);
  const [funding, setFunding] = useState<MobilityFunding[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [fundingLoading, setFundingLoading] = useState(true);
  const [jobsError, setJobsError] = useState('');
  const [fundingError, setFundingError] = useState('');
  const [fundingQuery, setFundingQuery] = useState('');

  useEffect(() => {
    let active = true;
    async function loadRoutes() {
      try {
        const response = await fetch(`${apiBase}/immigration`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: { routes?: ApiRoute[] } = await response.json();
        if (!Array.isArray(data.routes) || !data.routes.length) {
          throw new Error('Réponse API invalide');
        }
        const loaded = data.routes.map((item): Route => ({
          id: item.id,
          country: item.country,
          title: item.title,
          category: item.category,
          offer: item.offer_note,
          sponsorship: sponsorshipLabel(item),
          summary: item.summary,
          requirements: item.requirements,
          url: item.official_url
        }));
        if (active) {
          setRoutes(loaded);
          setDataSource('API locale · conditions officielles à revérifier');
        }
      } catch {
        if (active) {
          setRoutes(fallbackRoutes);
          setDataSource('Catalogue local de secours · API indisponible');
        }
      }
    }
    void loadRoutes();
    return () => { active = false; };
  }, [apiBase]);

  useEffect(() => {
    let active = true;
    async function loadJobs() {
      setJobsLoading(true);
      try {
        const response = await fetch(`${apiBase}/jobs`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: MobilityJob[] = await response.json();
        if (!Array.isArray(data)) throw new Error('Format de réponse inattendu');
        if (active) {
          setJobs(data);
          setJobsError('');
        }
      } catch {
        if (active) setJobsError('Impossible de charger les offres depuis l’API des emplois.');
      } finally {
        if (active) setJobsLoading(false);
      }
    }
    void loadJobs();
    return () => { active = false; };
  }, [apiBase]);

  useEffect(() => {
    let active = true;
    async function loadFunding() {
      setFundingLoading(true);
      try {
        const response = await fetch(`${apiBase}/doctorates`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: MobilityFunding[] = await response.json();
        if (!Array.isArray(data)) throw new Error('Format de réponse inattendu');
        if (active) {
          setFunding(data);
          setFundingError('');
        }
      } catch {
        if (active) setFundingError('Impossible de charger les financements depuis le catalogue académique.');
      } finally {
        if (active) setFundingLoading(false);
      }
    }
    void loadFunding();
    return () => { active = false; };
  }, [apiBase]);

  const countries = useMemo(
    () => [...new Set(routes.map(route => route.country))],
    [routes]
  );

  const visibleRoutes = useMemo(() => routes.filter(route => {
    const text = `${route.title} ${route.country} ${route.category} ${route.summary} ${route.requirements}`.toLocaleLowerCase();
    const matchesQuery = !query || text.includes(query.toLocaleLowerCase());
    const matchesCountry = !country || route.country === country;
    const offer = route.offer.toLocaleLowerCase();
    const matchesPath = !pathType ||
      (pathType === 'sans-offre'
        ? /pas nécessaire|pas systématiquement|sans offre/.test(offer)
        : /généralement nécessaire|contrat requis|offre admissible|généralement requis/.test(offer));
    return matchesQuery && matchesCountry && matchesPath;
  }), [routes, query, country, pathType]);

  const internationalJobs = useMemo(() => jobs.filter(job => {
    const countryText = `${job.country || ''} ${job.location || ''}`.toLocaleLowerCase();
    const isSenegal = /sénégal|senegal|dakar|pikine|thiès|thies/.test(countryText);
    const workText = `${job.work_mode || ''} ${job.remote_type || ''}`.toLocaleLowerCase();
    const isRemote = /remote|remote-first|télétravail|teletravail|worldwide|anywhere/.test(workText);
    const text = `${job.title} ${job.role_category || ''} ${(job.skills || []).join(' ')}`.toLocaleLowerCase();
    const isRelevant = /developer|développeur|développeuse|software engineer|ingénieur logiciel|full.?stack|backend|back-end|frontend|front-end|mobile|flutter|java|spring|angular|react|php|symfony|laravel|devops|data engineer|programmer|programmatrice/.test(text);
    return !isSenegal &&
      (job.international_recruitment === true ||
       job.relocation_supported === true ||
       (isRemote && isRelevant) ||
       isRelevant);
  }).sort((a, b) => {
    const relevance = (job: MobilityJob) => {
      const text = `${job.title} ${job.role_category || ''} ${(job.skills || []).join(' ')}`.toLocaleLowerCase();
      let score = 0;
      if (/full.?stack|backend|back-end|software engineer|ingénieur logiciel/.test(text)) score += 5;
      if (/developer|développeur|développeuse|développement|engineer|ingénieur/.test(text)) score += 3;
      if (/mobile|flutter|react native|android|ios/.test(text)) score += 3;
      if (/java|spring|angular|react|php|symfony|laravel|postgresql|docker/.test(text)) score += 2;
      return score;
    };

    return relevance(b) - relevance(a) ||
      Number(Boolean(b.relocation_supported)) - Number(Boolean(a.relocation_supported)) ||
      Number(Boolean(b.international_recruitment)) - Number(Boolean(a.international_recruitment)) ||
      (b.match_score || 0) - (a.match_score || 0);
  }), [jobs]);

  const visibleJobs = useMemo(() => internationalJobs.filter(job => {
    const text = `${job.title} ${job.company} ${job.country} ${job.location || ''} ${job.description || ''} ${(job.skills || []).join(' ')}`.toLocaleLowerCase();
    const matchesQuery = !query || text.includes(query.toLocaleLowerCase());
    const matchesCountry = !country || job.country === country;
    const matchesPath = !pathType ||
      (pathType === 'sans-offre'
        ? job.work_mode?.toLocaleLowerCase().includes('remote') || job.remote_type?.toLocaleLowerCase().includes('remote')
        : job.international_recruitment === true || job.relocation_supported === true);
    return matchesQuery && matchesCountry && Boolean(matchesPath);
  }), [internationalJobs, query, country, pathType]);

  const visibleFunding = useMemo(() => funding.filter(item => {
    const text = `${item.title} ${item.institution || ''} ${item.country || ''} ${item.location || ''} ${item.field || ''} ${item.description || ''} ${item.funding_type || ''} ${item.eligibility || ''}`.toLocaleLowerCase();
    return !fundingQuery || text.includes(fundingQuery.toLocaleLowerCase());
  }), [funding, fundingQuery]);

  return (
    <section className="immigration-panel">
      <div className="immigration-intro">
        <div className="immigration-heading-icon"><Globe2 size={24} /></div>
        <div>
          <h2>Immigration & mobilité internationale</h2>
          <p>Offres de recrutement, procédures officielles et programmes de financement accessibles à étudier depuis le Sénégal.</p>
        </div>
      </div>

      <div className="immigration-notice">
        <ShieldCheck size={19} />
        <p>Les informations affichées sont des pistes de recherche, pas une décision d’admissibilité. Une offre internationale ne garantit ni visa, ni parrainage, ni financement du déplacement. Vérifiez toujours les critères et dates sur la source officielle.</p>
      </div>

      <nav className="immigration-subnav" aria-label="Rubriques immigration et mobilité">
        <button type="button" className={section === 'jobs' ? 'active' : ''} onClick={() => setSection('jobs')}>
          <BriefcaseBusiness size={17} /> Offres internationales
        </button>
        <button type="button" className={section === 'procedures' ? 'active' : ''} onClick={() => setSection('procedures')}>
          <Globe2 size={17} /> Procédures d’immigration
        </button>
        <button type="button" className={section === 'funding' ? 'active' : ''} onClick={() => setSection('funding')}>
          <GraduationCap size={17} /> Financements & mobilité
        </button>
      </nav>

      {section === 'jobs' && (
        <>
          <div className="immigration-section-heading">
            <h3>Recrutement international</h3>
            <p>Offres issues de votre catalogue Emplois. Priorité aux annonces signalant le recrutement international ou la relocalisation, ainsi qu’aux postes techniques à distance à l’étranger.</p>
          </div>
          <div className="immigration-filters">
            <label className="immigration-search">
              <Search size={17} />
              <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Poste, entreprise, pays, compétence…" aria-label="Rechercher une offre internationale" />
            </label>
            <select value={country} onChange={event => setCountry(event.target.value)} aria-label="Filtrer les offres par pays">
              <option value="">Tous les pays</option>
              {[...new Set(internationalJobs.map(job => job.country).filter(Boolean))].sort().map(item => <option key={item}>{item}</option>)}
            </select>
            <select value={pathType} onChange={event => setPathType(event.target.value)} aria-label="Filtrer les offres par mobilité">
              <option value="">Toutes les possibilités</option>
              <option value="sans-offre">Télétravail potentiel</option>
              <option value="avec-offre">Recrutement international / mobilité signalé</option>
            </select>
          </div>
          <p className="immigration-count">
            {jobsLoading ? 'Chargement des offres…' : `${visibleJobs.length} offre(s) affichée(s) · Catalogue existant : ${jobs.length} offres`}
          </p>
          {jobsError && <p className="immigration-inline-error">{jobsError}</p>}
          {!jobsLoading && !jobsError && visibleJobs.length === 0 && (
            <div className="empty-state"><Search size={23} /><h3>Aucune offre internationale ne correspond</h3><p>Les offres sont filtrées à partir des indicateurs de recrutement international, de relocalisation et de télétravail. Modifiez les filtres ou vérifiez le module Emplois.</p></div>
          )}
          <div className="immigration-list">
            {visibleJobs.slice(0, 100).map(job => (
              <article className="immigration-card" key={job.id}>
                <div className="immigration-card-top">
                  <span className="immigration-country">{job.country || 'Pays non précisé'}</span>
                  <span className="immigration-category">{job.source || 'Source non précisée'}</span>
                </div>
                <h3>{job.title}</h3>
                <p className="immigration-summary"><strong>{job.company || 'Employeur non précisé'}</strong> · {job.location || job.country || 'Localisation non précisée'}</p>
                <div className="immigration-status-row">
                  <span className="mobility-status">
                    {job.relocation_supported
                      ? 'Mention de mobilité détectée · visa et pays à vérifier'
                      : job.international_recruitment
                        ? 'Recrutement international mentionné · pays éligibles à vérifier'
                        : 'Télétravail détecté · accès depuis le Sénégal à vérifier'}
                  </span>
                </div>
                <dl className="immigration-details">
                  <div><dt>Contrat</dt><dd>{job.contract_type || 'Non précisé par la source'}</dd></div>
                  <div><dt>Mode de travail</dt><dd>{job.work_mode || job.remote_type || 'Non précisé par la source'}</dd></div>
                  <div><dt>Salaire</dt><dd>{salaryFromDescription(job.description)}</dd></div>
                  <div><dt>Compétences</dt><dd>{job.skills?.length ? job.skills.join(', ') : 'À extraire ou vérifier dans la description'}</dd></div>
                  <div><dt>Visa / mobilité</dt><dd>{job.relocation_supported ? (job.relocation_evidence || 'Une aide à la mobilité est signalée ; confirmer si elle couvre le visa et le voyage.') : job.international_recruitment ? 'Recrutement international signalé ; prise en charge du visa non confirmée.' : 'Aucun engagement de parrainage ne peut être déduit des données disponibles.'}</dd></div>
                  <div><dt>Date limite</dt><dd>{deadlineFromDescription(job.description)}</dd></div>
                  <div><dt>Publication</dt><dd>{displayDate(job.published_at)}</dd></div>
                </dl>
                {job.description && <details className="immigration-description"><summary>Lire la description de l’offre</summary><p>{job.description}</p></details>}
                <div className="immigration-card-actions">
                  {job.url && <a className="immigration-source-link" href={job.url} target="_blank" rel="noreferrer">Candidater / consulter l’annonce <ArrowUpRight size={16} /></a>}
                </div>
              </article>
            ))}
          </div>
          {visibleJobs.length > 100 && <p className="immigration-count">100 offres affichées pour préserver la fluidité. Affinez la recherche pour consulter les suivantes.</p>}
        </>
      )}

      {section === 'procedures' && (
        <>
          <div className="immigration-section-heading">
            <h3>Procédures d’immigration et de mobilité</h3>
            <p>Parcours généraux à examiner pour une personne de nationalité sénégalaise résidant au Sénégal. Les frais, pièces et délais dépendent de la situation individuelle et des règles en vigueur.</p>
          </div>
          <div className="immigration-filters">
            <label className="immigration-search"><Search size={17} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Programme, pays ou critère…" aria-label="Rechercher un parcours" /></label>
            <select value={country} onChange={event => setCountry(event.target.value)} aria-label="Filtrer par destination">
              <option value="">Toutes les destinations</option>
              {countries.map(item => <option key={item}>{item}</option>)}
            </select>
            <select value={pathType} onChange={event => setPathType(event.target.value)} aria-label="Filtrer selon l'offre d'emploi">
              <option value="">Toutes les voies</option>
              <option value="sans-offre">Possiblement sans offre préalable</option>
              <option value="avec-offre">Offre ou contrat généralement requis</option>
            </select>
          </div>
          <p className="immigration-count">{visibleRoutes.length} parcours affiché(s) · {dataSource}</p>
          <div className="immigration-list">
            {visibleRoutes.map(route => (
              <article className="immigration-card" key={route.id}>
                <div className="immigration-card-top"><span className="immigration-country">{route.country}</span><span className="immigration-category">{route.category}</span></div>
                <h3>{route.title}</h3>
                <p className="immigration-summary">{route.summary}</p>
                <dl className="immigration-details">
                  <div><dt>Offre d’emploi</dt><dd>{route.offer}</dd></div>
                  <div><dt>Employeur / parrainage</dt><dd>{route.sponsorship}</dd></div>
                  <div><dt>Critères à examiner</dt><dd>{route.requirements}</dd></div>
                  <div><dt>Admissibilité personnelle</dt><dd>À vérifier selon le profil, les justificatifs, les règles actuelles et la procédure consulaire applicable depuis le Sénégal.</dd></div>
                  <div><dt>Frais et délais</dt><dd>À confirmer sur la source officielle selon la catégorie et la situation du demandeur.</dd></div>
                </dl>
                <a className="immigration-source-link" href={route.url} target="_blank" rel="noreferrer">Consulter la source officielle <ArrowUpRight size={16} /></a>
              </article>
            ))}
          </div>
          {visibleRoutes.length === 0 && <div className="empty-state"><Search size={23} /><h3>Aucun parcours correspondant</h3><p>Modifiez les filtres ou essayez un autre pays.</p></div>}
        </>
      )}

      {section === 'funding' && (
        <>
          <div className="immigration-section-heading">
            <h3>Financements, bourses et programmes de mobilité</h3>
            <p>Catalogue académique déjà intégré à Job Ci Adduna AI. Le statut de financement est repris de la source enregistrée ; il ne signifie pas que votre admissibilité personnelle a été confirmée.</p>
          </div>
          <label className="immigration-search immigration-funding-search">
            <Search size={17} />
            <input value={fundingQuery} onChange={event => setFundingQuery(event.target.value)} placeholder="Bourse, doctorat, organisme, pays, domaine…" aria-label="Rechercher un financement" />
          </label>
          <p className="immigration-count">
            {fundingLoading ? 'Chargement des programmes…' : `${visibleFunding.length} programme(s) affiché(s) · Catalogue académique : ${funding.length} opportunités`}
          </p>
          {fundingError && <p className="immigration-inline-error">{fundingError}</p>}
          {!fundingLoading && !fundingError && visibleFunding.length === 0 && <div className="empty-state"><Search size={23} /><h3>Aucun financement correspondant</h3><p>Essayez d’autres mots-clés.</p></div>}
          <div className="immigration-list">
            {visibleFunding.slice(0, 100).map(item => (
              <article className="immigration-card" key={item.id}>
                <div className="immigration-card-top">
                  <span className="immigration-country">{item.country || 'Pays à confirmer'}</span>
                  <span className="immigration-category">{item.opportunity_type || item.funding_type || 'Programme académique'}</span>
                </div>
                <h3>{item.title}</h3>
                <p className="immigration-summary">{item.institution || 'Organisme à confirmer'} · {item.location || item.field || 'Domaine ou lieu non précisé'}</p>
                <div className="immigration-status-row">
                  <span className="mobility-status">{fundingStatusLabel(item.funding_status)}</span>
                  <span className="mobility-status">{item.eligibility ? 'Critères d’éligibilité disponibles' : 'Éligibilité à vérifier'}</span>
                </div>
                <dl className="immigration-details">
                  <div><dt>Montant / allocation</dt><dd>{item.salary_amount != null ? `${item.salary_amount} ${item.salary_currency || ''} ${item.salary_period || ''}`.trim() : 'Montant non précisé par la source'}</dd></div>
                  <div><dt>Date limite</dt><dd>{displayDate(item.deadline)}</dd></div>
                  <div><dt>Financement</dt><dd>{fundingStatusLabel(item.funding_status)}{item.funding_type ? ` · ${item.funding_type}` : ''}</dd></div>
                  <div><dt>Éligibilité</dt><dd>{item.eligibility || 'Vérifier les nationalités admises, le pays de résidence, le diplôme et les conditions propres au programme.'}</dd></div>
                  <div><dt>Preuve de financement</dt><dd>{item.funding_evidence || 'Aucune preuve détaillée enregistrée ; consulter l’annonce originale.'}</dd></div>
                  <div><dt>Frais de scolarité</dt><dd>{item.tuition_status || 'Statut non précisé'}</dd></div>
                </dl>
                {item.description && <details className="immigration-description"><summary>Lire la description du programme</summary><p>{item.description}</p></details>}
                {item.url && <a className="immigration-source-link" href={item.url} target="_blank" rel="noreferrer">Consulter l’annonce et vérifier les conditions <ArrowUpRight size={16} /></a>}
              </article>
            ))}
          </div>
          {visibleFunding.length > 100 && <p className="immigration-count">100 programmes affichés pour préserver la fluidité. Affinez la recherche pour consulter les suivants.</p>}
        </>
      )}

      <div className="immigration-footer-note">
        <CheckCircle2 size={17} />
        <span>Les données proviennent des catalogues locaux existants. Une date limite absente n’est pas une preuve que l’offre est encore ouverte. Confirmez toujours l’éligibilité des candidats sénégalais, le financement, le visa et les frais auprès de la source officielle.</span>
      </div>
    </section>
  );
}
