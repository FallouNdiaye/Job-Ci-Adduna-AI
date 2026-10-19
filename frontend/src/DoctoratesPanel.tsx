import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  GraduationCap, Search, RefreshCw, Star, ExternalLink,
  Plus, CheckCircle2, ShieldCheck, Clock3
} from 'lucide-react';

type Doctorate = {
  id: number;
  title: string;
  institution: string;
  country: string;
  location?: string;
  field: string;
  description?: string;
  url?: string;
  source?: string;
  funding_status: string;
  funding_type?: string;
  salary_amount?: number | null;
  salary_currency?: string;
  salary_period?: string;
  duration_months?: number | null;
  tuition_status?: string;
  eligibility?: string;
  deadline?: string | null;
  published_at?: string | null;
  collected_at?: string;
  application_status: string;
  is_favorite: boolean | number;
  funding_evidence?: string;
  opportunity_type?: AcademicCategory;
};


type Props = { apiBase: string };

/** Convertit une description HTML externe en texte lisible, sans l'injecter dans le DOM. */
function cleanDescription(value?: string): string {
  if (!value) return '';

  let text = value;
  const decoder = document.createElement('textarea');

  // Gère aussi les flux qui encodent les entités HTML plusieurs fois.
  for (let i = 0; i < 4; i++) {
    const previous = text;

    text = text
      .replace(
        /<\s*(script|style)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi,
        ' '
      )
      .replace(
        /<\s*br\b[^>]*\/?>|<\s*\/\s*(p|div|li|h[1-6]|ul|ol|section|article|tr|blockquote)\s*>/gi,
        '\n'
      )
      .replace(/<[^>]*>/g, ' ');

    decoder.innerHTML = text;
    text = decoder.value;

    if (text === previous) break;
  }

  return text
    .replace(/\u00a0/g, ' ')
    .split(/\r?\n/)
    .map(line => line.replace(/[ \t\f\v]+/g, ' ').trim())
    .filter(Boolean)
    .join('\n')
    .trim();
}


const fundingLabels: Record<string, string> = {
  CONFIRMED_FULL: 'Financement intégral annoncé',
  PARTIAL: 'Financement partiel',
  UNCONFIRMED: 'Financement à vérifier',
  UNKNOWN: 'Financement inconnu',
};

type AcademicCategory = 'doctorats' | 'masters' | 'aides' | 'recherche' | 'uncategorized';

const academicCategories: { id: AcademicCategory; label: string }[] = [
  { id: 'doctorats', label: 'Doctorats' },
  { id: 'masters', label: 'Masters' },
  { id: 'aides', label: 'Aides générales' },
  { id: 'recherche', label: 'Recherche et postes académiques' },
  { id: 'uncategorized', label: 'À classifier' },
];

function classifyOpportunity(item: Doctorate): AcademicCategory {
  const savedCategory = item.opportunity_type;
  if (academicCategories.some((category) => category.id === savedCategory)) {
    return savedCategory as AcademicCategory;
  }

  const title = (item.title || '').toLocaleLowerCase();
  const description = (item.description || '').toLocaleLowerCase();
  const combined = `${title} ${description}`;

  // Les postes postdoctoraux et d'enseignement sont distincts des doctorats.
  if (/\b(postdoc|post-doc|postdoctoral|post-doctoral|assistant professor|associate professor|full professor|lecturer|faculty position|professor position)\b/i.test(title)) {
    return 'recherche';
  }

  // Le titre prime pour éviter de confondre une bourse de thèse avec une aide générale.
  if (/\b(master'?s?|msc|m\.sc\.?|ma degree|m\.a\.? degree|mba|graduate master)\b/i.test(title)) {
    return 'masters';
  }

  if (/\b(ph\.?d\.?|phd|doctoral|doctorate|doctorat|doctorant|doctorante|thesis|theses|thèse|thèses|studentship)\b/i.test(title)) {
    return 'doctorats';
  }

  // Si le titre est imprécis, la description peut apporter un indice explicite.
  if (/\b(postdoc|post-doc|postdoctoral|post-doctoral|assistant professor|associate professor|full professor|lecturer|faculty position|research fellow|researcher position|research scientist)\b/i.test(combined)) {
    return 'recherche';
  }

  if (/\b(master'?s?|msc|m\.sc\.?|ma degree|m\.a\.? degree|mba|graduate master)\b/i.test(combined)) {
    return 'masters';
  }

  if (/\b(ph\.?d\.?|phd|doctoral|doctorate|doctorat|doctorant|doctorante|thesis|theses|thèse|thèses|doctoral programme|doctoral program)\b/i.test(combined)) {
    return 'doctorats';
  }

  if (/\b(scholarship|scholarships|fellowship|fellowships|bourse|bourses|grant|grants|financial aid|financial support|mobility grant|travel grant|stipend|tuition waiver|student aid)\b/i.test(combined)) {
    return 'aides';
  }

  return 'uncategorized';
}

function categoryLabel(category: AcademicCategory): string {
  return academicCategories.find((item) => item.id === category)?.label ?? 'À classifier';
}

const applicationStatuses = [
  'À examiner',
  'Favori',
  'Candidature préparée',
  'Candidature envoyée',
  'Entretien',
  'Refus',
  'Acceptée',
];

const emptyForm = {
  title: '',
  institution: '',
  country: '',
  field: '',
  url: '',
  description: '',
  funding_status: 'UNKNOWN',
  funding_evidence: '',
  deadline: '',
};

function isRecent(item: Doctorate) {
  if (!item.collected_at) return false;
  const timestamp = Date.parse(item.collected_at);
  if (Number.isNaN(timestamp)) return false;
  const age = Date.now() - timestamp;
  return age >= 0 && age <= 7 * 24 * 60 * 60 * 1000;
}

function dateLabel(value?: string | null) {
  if (!value) return 'Non précisée';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric' });
}

export default function DoctoratesPanel({ apiBase }: Props) {
  const [items, setItems] = useState<Doctorate[]>([]);
  const [sources, setSources] = useState<{ name: string; url: string }[]>([]);
  const [query, setQuery] = useState('');
  const [country, setCountry] = useState('');
  const [field, setField] = useState('');
  const [funding, setFunding] = useState('');
  const [status, setStatus] = useState('');
  const [period, setPeriod] = useState<'recent' | 'old' | 'all'>('recent');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [academicView, setAcademicView] = useState<AcademicCategory>('doctorats');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const endpoint = `${apiBase}/doctorates`;

  const load = useCallback(async () => {
    setError('');
    try {
      const [offersResponse, sourcesResponse] = await Promise.all([
        fetch(endpoint),
        fetch(`${endpoint}/sources`),
      ]);
      if (!offersResponse.ok) throw new Error(`Chargement des doctorats : HTTP ${offersResponse.status}`);
      const offersData = await offersResponse.json();
      setItems(Array.isArray(offersData) ? offersData : []);
      if (sourcesResponse.ok) {
        const sourceData = await sourcesResponse.json();
        setSources(Array.isArray(sourceData) ? sourceData : []);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible de charger les doctorats.');
    }
  }, [endpoint]);

  useEffect(() => { void load(); }, [load]);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      if (classifyOpportunity(item) !== academicView) return false;
      const haystack = [
        item.title, item.institution, item.country, item.field,
        item.description, item.source,
      ].join(' ').toLocaleLowerCase();
      if (query && !haystack.includes(query.toLocaleLowerCase())) return false;
      if (country && !item.country.toLocaleLowerCase().includes(country.toLocaleLowerCase())) return false;
      if (field && !item.field.toLocaleLowerCase().includes(field.toLocaleLowerCase())) return false;
      if (funding && item.funding_status !== funding) return false;
      if (status && item.application_status !== status) return false;
      if (favoritesOnly && !Boolean(item.is_favorite)) return false;
      if (period === 'recent' && !isRecent(item)) return false;
      if (period === 'old' && isRecent(item)) return false;
      return true;
    });
  }, [items, query, country, field, funding, status, favoritesOnly, period, academicView]);

  const categoryCounts = useMemo(() => {
    const counts: Record<AcademicCategory, number> = {
      doctorats: 0, masters: 0, aides: 0, recherche: 0, uncategorized: 0,
    };
    for (const item of items) counts[classifyOpportunity(item)] += 1;
    return counts;
  }, [items]);

  const recentCount = items.filter(isRecent).length;
  const oldCount = items.length - recentCount;

  async function sync() {
    setBusy(true);
    setNotice('');
    setError('');
    try {
      const response = await fetch(`${endpoint}/sync`, { method: 'POST' });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `Synchronisation : HTTP ${response.status}`);
      const messages = [
        `${result.inserted ?? 0} nouvelle(s) offre(s)`,
        `${result.duplicates ?? 0} doublon(s)`,
      ];
      if (Array.isArray(result.errors) && result.errors.length) {
        messages.push(result.errors.join(' | '));
      }
      setNotice(messages.join(' — '));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Échec de la synchronisation.');
    } finally {
      setBusy(false);
    }
  }

  async function updateDoctorate(
    id: number,
    changes: {
      application_status?: string;
      is_favorite?: boolean;
      opportunity_type?: AcademicCategory;
    }
  ) {
    setError('');
    try {
      const response = await fetch(`${endpoint}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Mise à jour impossible.');
      setItems((previous) => previous.map((item) => item.id === id ? { ...item, ...result } : item));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Mise à jour impossible.');
    }
  }

  async function addDoctorate(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const payload = {
        ...form,
        institution: form.institution.trim() || 'Non précisée',
        country: form.country.trim() || 'Non précisé',
        location: '',
        field: form.field.trim() || 'Non précisé',
        url: form.url.trim(),
        source: 'Ajout manuel',
        funding_type: '',
        salary_amount: null,
        salary_currency: '',
        salary_period: '',
        duration_months: null,
        tuition_status: 'Inconnu',
        eligibility: '',
        deadline: form.deadline || null,
        published_at: null,
      };
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Ajout impossible.');
      if (result.inserted) {
        setNotice('Opportunité académique ajoutée avec succès.');
      } else {
        setNotice('Cette offre semble déjà enregistrée : aucun doublon ajouté.');
      }
      setForm(emptyForm);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Ajout impossible.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="doctoral-panel">
      <div className="doctoral-heading">
        <div className="doctoral-heading-icon"><GraduationCap size={24} /></div>
        <div>
          <h2>Opportunités académiques</h2>
          <p>Retrouvez doctorats, bourses, aides financières et opportunités de recherche. La catégorie ne garantit pas le financement : vérifiez toujours la source officielle.</p>
        </div>
      </div>

      <nav className="academic-subnav" aria-label="Catégories d'opportunités académiques">
        {academicCategories.map((category) => (
          <button
            key={category.id}
            type="button"
            className={`academic-tab ${academicView === category.id ? 'active' : ''}`}
            aria-current={academicView === category.id ? 'page' : undefined}
            onClick={() => setAcademicView(category.id)}
          >
            <span>{category.label}</span>
            <span className="academic-tab-count">{categoryCounts[category.id]}</span>
          </button>
        ))}
      </nav>

      <details className="doctoral-card funding-directory">
        <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
          Répertoire international — programmes, bourses et mobilité
        </summary>
        <p className="doctoral-description">
          Portails officiels à explorer en complément des offres collectées.
          Un programme répertorié n'est pas nécessairement ouvert aux candidatures.
          Vérifie les conditions, le financement et les dates sur chaque site.
        </p>

        <article className="doctoral-card">
          <span className="doctoral-funding funding-unconfirmed">Appels à vérifier</span>
          <h3>AI4D Africa — appels et initiatives en intelligence artificielle</h3>
          <p className="doctoral-description">
            Appels et réseaux autour de l'IA responsable. Les critères varient :
            certains appels concernent des équipes, des projets ou des publics spécifiques.
          </p>
          <a className="doctoral-source-link" href="https://www.ai4d.ai/calls"
            target="_blank" rel="noreferrer">
            Consulter les appels officiels <ExternalLink size={15} />
          </a>
        </article>

        <article className="doctoral-card">
          <span className="doctoral-funding funding-unconfirmed">Veille — critères spécifiques</span>
          <h3>ARISE — African Research Initiative for Scientific Excellence</h3>
          <p className="doctoral-description">
            Programme de recherche et de leadership scientifique en Afrique.
            Le pilote vise des chercheurs ayant déjà un doctorat et une expérience
            postdoctorale ; ce n'est donc pas une bourse d'entrée en doctorat adaptée
            au profil actuel. Vérifie les nouvelles initiatives et leurs critères.
          </p>
          <a className="doctoral-source-link" href="https://arise.aasciences.africa/"
            target="_blank" rel="noreferrer">
            Consulter le programme officiel <ExternalLink size={15} />
          </a>
        </article>

        <article className="doctoral-card">
          <span className="doctoral-funding funding-unknown">Édition 2026 clôturée</span>
          <h3>Dorcas Muthoni PhD Fellowship — UPF, Espagne</h3>
          <p className="doctoral-description">
            La date limite de l'édition 2026 était le 15 janvier 2026 et les critères
            publiés réservent cette bourse aux candidates africaines en informatique.
            Cette édition n'est pas une candidature disponible pour ton profil ;
            conserve le lien uniquement pour surveiller une éventuelle future édition.
          </p>
          <a className="doctoral-source-link"
            href="https://www.upf.edu/web/phd-engineering/dorcas-muthoni-phd"
            target="_blank" rel="noreferrer">
            Consulter la page officielle <ExternalLink size={15} />
          </a>
        </article>

        <article className="doctoral-card">
          <span className="doctoral-funding funding-unconfirmed">À filtrer selon le pays et le diplôme</span>
          <h3>DAAD — base de données des bourses</h3>
          <p className="doctoral-description">
            Recherche de financements pour diplômés, doctorants et chercheurs.
            L'éligibilité, la couverture financière et les échéances dépendent
            du programme et du pays d'origine.
          </p>
          <a className="doctoral-source-link"
            href="https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/"
            target="_blank" rel="noreferrer">
            Rechercher une bourse <ExternalLink size={15} />
          </a>
        </article>

        <article className="doctoral-card">
          <span className="doctoral-funding funding-unconfirmed">Offres à examiner individuellement</span>
          <h3>EURAXESS — emplois de recherche, doctorats et mobilité</h3>
          <p className="doctoral-description">
            Portail européen de postes de recherche, d'offres de financement et
            d'accueil de chercheurs. Filtre notamment par informatique, niveau
            doctoral, pays, financement et date limite.
          </p>
          <a className="doctoral-source-link" href="https://euraxess.ec.europa.eu/jobs/search"
            target="_blank" rel="noreferrer">
            Rechercher des opportunités <ExternalLink size={15} />
          </a>
        </article>
      </details>

      <div className="doctoral-stats">
        <div><span>Total collecté</span><strong>{items.length}</strong></div>
        <div><span>Collectées récemment</span><strong>{recentCount}</strong></div>
        <div><span>Anciennes</span><strong>{oldCount}</strong></div>
        <div><span>Sources configurées</span><strong>{sources.length}</strong></div>
      </div>

      {(notice || error) && (
        <div className={error ? 'doctoral-notice is-error' : 'doctoral-notice'}>
          {error ? error : <><CheckCircle2 size={16} /> {notice}</>}
        </div>
      )}

      <div className="doctoral-actions">
        <button className="btn btn-primary" onClick={() => setShowForm((value) => !value)}>
          <Plus size={16} /> {showForm ? 'Fermer le formulaire' : 'Ajouter une opportunité'}
        </button>
        <button className="btn btn-secondary" onClick={() => void sync()} disabled={busy}>
          <RefreshCw size={16} className={busy ? 'doctoral-spinning' : ''} />
          {busy ? 'Synchronisation…' : 'Collecter les nouvelles offres'}
        </button>
      </div>

      {showForm && (
        <form className="doctoral-form" onSubmit={addDoctorate}>
          <h3>Ajouter une opportunité académique</h3>
          <div className="doctoral-form-grid">
            <label>Titre de l’opportunité *
              <input required minLength={2} maxLength={500} value={form.title}
                onChange={(e) => setForm({ ...form, title: e.target.value })} />
            </label>
            <label>Université / laboratoire
              <input value={form.institution} onChange={(e) => setForm({ ...form, institution: e.target.value })} />
            </label>
            <label>Pays
              <input value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })} />
            </label>
            <label>Domaine
              <input value={form.field} onChange={(e) => setForm({ ...form, field: e.target.value })} />
            </label>
            <label>Lien officiel de l’offre
              <input type="url" placeholder="https://…" value={form.url}
                onChange={(e) => setForm({ ...form, url: e.target.value })} />
            </label>
            <label>Date limite
              <input type="date" value={form.deadline}
                onChange={(e) => setForm({ ...form, deadline: e.target.value })} />
            </label>
            <label>État du financement
              <select value={form.funding_status}
                onChange={(e) => setForm({ ...form, funding_status: e.target.value })}>
                <option value="UNKNOWN">Inconnu</option>
                <option value="UNCONFIRMED">À vérifier</option>
                <option value="PARTIAL">Partiel</option>
                <option value="CONFIRMED_FULL">Intégral annoncé</option>
              </select>
            </label>
            <label>Description et conditions
              <textarea rows={3} value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </label>
            <label>Preuve / extrait relatif au financement
              <textarea rows={3} value={form.funding_evidence}
                placeholder="Copie ici l’extrait de l’annonce qui décrit le financement."
                onChange={(e) => setForm({ ...form, funding_evidence: e.target.value })} />
            </label>
          </div>
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? 'Enregistrement…' : 'Enregistrer l’opportunité'}
          </button>
        </form>
      )}

      <div className="doctoral-period-tabs">
        <button className={period === 'recent' ? 'active' : ''} onClick={() => setPeriod('recent')}>
          <Clock3 size={15} /> Récentes (7 jours)
        </button>
        <button className={period === 'old' ? 'active' : ''} onClick={() => setPeriod('old')}>
          Anciennes
        </button>
        <button className={period === 'all' ? 'active' : ''} onClick={() => setPeriod('all')}>
          Toutes
        </button>
      </div>

      <div className="doctoral-filters">
        <label className="doctoral-search"><Search size={16} />
          <input placeholder="Sujet, université, pays…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </label>
        <input aria-label="Filtrer par pays" placeholder="Pays" value={country} onChange={(e) => setCountry(e.target.value)} />
        <input aria-label="Filtrer par domaine" placeholder="Domaine" value={field} onChange={(e) => setField(e.target.value)} />
        <select aria-label="Filtrer par financement" value={funding} onChange={(e) => setFunding(e.target.value)}>
          <option value="">Tous les financements</option>
          <option value="CONFIRMED_FULL">Intégral annoncé</option>
          <option value="PARTIAL">Partiel</option>
          <option value="UNCONFIRMED">À vérifier</option>
          <option value="UNKNOWN">Inconnu</option>
        </select>
        <select aria-label="Filtrer par candidature" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Tous les statuts</option>
          {applicationStatuses.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
        <label className="doctoral-favorite-filter">
          <input type="checkbox" checked={favoritesOnly} onChange={(e) => setFavoritesOnly(e.target.checked)} />
          Favoris uniquement
        </label>
      </div>

      <div className="doctoral-results-caption">
        {filtered.length} offre(s) affichée(s) sur {items.length}
      </div>

      {filtered.length === 0 ? (
        <div className="doctoral-empty">
          <GraduationCap size={34} />
          <h3>{items.length === 0 ? 'Aucune opportunité enregistrée pour le moment' : `Aucune opportunité dans « ${categoryLabel(academicView)} » avec ces filtres`}</h3>
          <p>{items.length === 0
            ? 'Ajoute une opportunité manuellement ou configure des flux RSS/Atom HTTPS autorisés avant de lancer la collecte automatique.'
            : 'Modifie les filtres ou affiche toutes les périodes.'}</p>
          {items.length === 0 && sources.length === 0 && (
            <p className="doctoral-source-warning"><ShieldCheck size={16} /> Aucune source de collecte n’est configurée actuellement.</p>
          )}
        </div>
      ) : (
        <div className="doctoral-list">
          {filtered.map((item) => (
            <article className="doctoral-card" key={item.id}>
              <div className="doctoral-card-top">
                <div>
                  <label className="doctoral-category-editor">
                    <span>Catégorie</span>
                    <select
                      aria-label={`Catégorie de ${item.title}`}
                      value={classifyOpportunity(item)}
                      onChange={(e) => {
                        const category = e.target.value as AcademicCategory;
                        void updateDoctorate(item.id, { opportunity_type: category });
                      }}
                    >
                      {academicCategories.map((category) => (
                        <option key={category.id} value={category.id}>{category.label}</option>
                      ))}
                    </select>
                  </label>
                  <span className={`doctoral-funding funding-${item.funding_status.toLowerCase()}`}>
                    {fundingLabels[item.funding_status] || item.funding_status}
                  </span>
                  <h3>{item.title}</h3>
                  <p className="doctoral-institution">{item.institution} · {item.country}</p>
                </div>
                <button className={`doctoral-star ${Boolean(item.is_favorite) ? 'selected' : ''}`}
                  aria-label={Boolean(item.is_favorite) ? 'Retirer des favoris' : 'Ajouter aux favoris'}
                  title="Favori"
                  onClick={() => void updateDoctorate(item.id, { is_favorite: !Boolean(item.is_favorite) })}>
                  <Star size={19} fill={Boolean(item.is_favorite) ? 'currentColor' : 'none'} />
                </button>
              </div>
              <div className="doctoral-meta">
                <span>{item.field || 'Domaine non précisé'}</span>
                {item.duration_months ? <span>{item.duration_months} mois</span> : null}
                {item.salary_amount != null ? <span>{item.salary_amount} {item.salary_currency || ''} {item.salary_period || ''}</span> : null}
                <span>Date limite : {dateLabel(item.deadline)}</span>
                <span>Collectée : {dateLabel(item.collected_at)}</span>
              </div>
              {item.description && cleanDescription(item.description) && <p className="doctoral-description" style={{ whiteSpace: "pre-line" }}>{cleanDescription(item.description)}</p>}
              {item.funding_evidence && (
                <p className="doctoral-evidence"><ShieldCheck size={15} /> <strong>Élément de financement :</strong> {item.funding_evidence}</p>
              )}
              <div className="doctoral-card-footer">
                <label>Suivi de candidature
                  <select value={item.application_status || 'À examiner'}
                    onChange={(e) => void updateDoctorate(item.id, { application_status: e.target.value })}>
                    {applicationStatuses.map((value) => <option key={value} value={value}>{value}</option>)}
                  </select>
                </label>
                {item.url && /^https?:\/\//i.test(item.url) && (
                  <a className="doctoral-source-link" href={item.url} target="_blank" rel="noreferrer">
                    Consulter l’offre <ExternalLink size={15} />
                  </a>
                )}
              </div>
              <p className="doctoral-disclaimer">
                Vérifie le financement, les frais de scolarité, le salaire et les critères d’éligibilité sur la source officielle.
              </p>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
