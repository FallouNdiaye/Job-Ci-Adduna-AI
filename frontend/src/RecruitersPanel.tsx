import { useEffect, useMemo, useState } from 'react';
import {
  Users, Search, ExternalLink, Mail, Globe2, BriefcaseBusiness,
  MapPin, RefreshCw, X, Building2, Phone, Linkedin
} from 'lucide-react';

type Recruiter = {
  id: number;
  name: string;
  website_url: string;
  country: string;
  specialties: string[];
  contact_name: string;
  contact_role: string;
  contact_email: string;
  contact_phone: string;
  linkedin_url: string;
  contact_url: string;
  source_url: string;
  source_name: string;
  notes: string;
  verified_at?: string | null;
};

type RecruiterOffer = {
  id: number;
  recruiter_id: number;
  recruiter_name: string;
  title: string;
  company: string;
  location: string;
  country: string;
  work_mode: string;
  contract_type: string;
  description: string;
  url: string;
  source_url: string;
  published_at?: string | null;
  deadline?: string | null;
  skills: string[];
  visa_sponsorship_status?: 'confirmed' | 'mentioned' | 'not_offered' | 'unknown';
  relocation_support_status?: 'confirmed' | 'mentioned' | 'not_offered' | 'unknown';
  senegal_eligibility_status?: 'eligible' | 'ineligible' | 'unclear' | 'unknown';
  eligibility_notes?: string;
  evidence_url?: string;
  verification_status?: 'verified' | 'unverified' | 'needs_review';
  verified_at?: string | null;
};

type Props = { apiBase: string };

function safeDate(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString('fr-FR');
}

function externalLink(value?: string) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : undefined;
  } catch {
    return undefined;
  }
}

function mobilityLabel(value: string | undefined, labels: Record<string, string>) {
  return labels[value || 'unknown'] || 'Inconnu';
}

const visaLabels: Record<string, string> = {
  confirmed: 'Visa sponsorisé confirmé',
  mentioned: 'Visa mentionné',
  not_offered: 'Pas de sponsoring indiqué',
  unknown: 'Visa non vérifié',
};

const relocationLabels: Record<string, string> = {
  confirmed: 'Relocalisation confirmée',
  mentioned: 'Relocalisation mentionnée',
  not_offered: 'Aide à la relocalisation non indiquée',
  unknown: 'Relocalisation non vérifiée',
};

const eligibilityLabels: Record<string, string> = {
  eligible: 'Sénégal : éligibilité confirmée',
  ineligible: 'Sénégal : non éligible',
  unclear: 'Éligibilité à clarifier',
  unknown: 'Éligibilité non vérifiée',
};

const verificationLabels: Record<string, string> = {
  verified: 'Source vérifiée',
  unverified: 'Non vérifiée',
  needs_review: 'À vérifier',
};

export default function RecruitersPanel({ apiBase }: Props) {
  const [recruiters, setRecruiters] = useState<Recruiter[]>([]);
  const [offers, setOffers] = useState<RecruiterOffer[]>([]);
  const [search, setSearch] = useState('');
  const [country, setCountry] = useState('');
  const [workMode, setWorkMode] = useState('');
  const [visaStatus, setVisaStatus] = useState('');
  const [relocationStatus, setRelocationStatus] = useState('');
  const [eligibilityStatus, setEligibilityStatus] = useState('');
  const [selectedRecruiter, setSelectedRecruiter] = useState<number | null>(null);
  const [view, setView] = useState<'offers' | 'recruiters'>('recruiters');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const [recruiterResponse, offerResponse] = await Promise.all([
        fetch(`${apiBase}/recruiters?limit=500`),
        fetch(`${apiBase}/recruiters/offers?limit=1000`)
      ]);
      if (!recruiterResponse.ok || !offerResponse.ok) {
        throw new Error('L’API des recruteurs a refusé la requête.');
      }
      const [recruiterData, offerData] = await Promise.all([
        recruiterResponse.json(),
        offerResponse.json()
      ]);
      if (!Array.isArray(recruiterData) || !Array.isArray(offerData)) {
        throw new Error('Format de réponse inattendu.');
      }
      setRecruiters(recruiterData);
      setOffers(offerData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Impossible de charger les données.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [apiBase]);

  const countries = useMemo(() => {
    const values = new Set<string>();
    offers.forEach(item => {
      if (item.country?.trim()) values.add(item.country.trim());
      else if (item.location?.trim()) values.add(item.location.trim());
    });
    recruiters.forEach(item => {
      if (item.country?.trim()) values.add(item.country.trim());
    });
    return [...values].sort((a, b) => a.localeCompare(b, 'fr'));
  }, [offers, recruiters]);

  const filteredRecruiters = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return recruiters.filter(item => {
      const matchesSearch = !term || [
        item.name, item.country, item.contact_name, item.contact_role,
        item.contact_email, ...(item.specialties || [])
      ].join(' ').toLocaleLowerCase().includes(term);
      const matchesCountry = !country || item.country.toLocaleLowerCase().includes(country.toLocaleLowerCase());
      return matchesSearch && matchesCountry;
    });
  }, [recruiters, search, country]);

  const filteredOffers = useMemo(() => {
    const term = search.trim().toLocaleLowerCase();
    return offers.filter(item => {
      const matchesSearch = !term || [
        item.title, item.company, item.recruiter_name, item.location,
        item.country, item.description, ...(item.skills || [])
      ].join(' ').toLocaleLowerCase().includes(term);
      const matchesCountry = !country ||
        `${item.country} ${item.location}`.toLocaleLowerCase().includes(country.toLocaleLowerCase());
      const matchesMode = !workMode ||
        item.work_mode.toLocaleLowerCase().includes(workMode.toLocaleLowerCase());
      const matchesRecruiter = selectedRecruiter === null || item.recruiter_id === selectedRecruiter;
      const matchesVisa = !visaStatus || (item.visa_sponsorship_status || 'unknown') === visaStatus;
      const matchesRelocation = !relocationStatus || (item.relocation_support_status || 'unknown') === relocationStatus;
      const matchesEligibility = !eligibilityStatus || (item.senegal_eligibility_status || 'unknown') === eligibilityStatus;
      return matchesSearch && matchesCountry && matchesMode && matchesRecruiter
        && matchesVisa && matchesRelocation && matchesEligibility;
    });
  }, [offers, search, country, workMode, visaStatus, relocationStatus, eligibilityStatus, selectedRecruiter]);

  const selected = recruiters.find(item => item.id === selectedRecruiter);
  const recruiterOfferCount = selectedRecruiter === null
    ? offers.length
    : offers.filter(item => item.recruiter_id === selectedRecruiter).length;

  return (
    <section className="recruiters-panel">
      <div className="recruiters-heading">
        <div className="recruiters-heading-icon"><Users size={23} /></div>
        <div>
          <h2>Recruteurs internationaux</h2>
          <p>Contacts professionnels publics et offres reliées à leurs sources officielles.</p>
        </div>
        <button className="btn btn-ghost recruiters-refresh" onClick={() => void loadData()} disabled={loading}>
          <RefreshCw size={15} className={loading ? 'spin' : ''} />
          Actualiser
        </button>
      </div>

      <div className="recruiters-stats">
        <div><Users size={18} /><span>Recruteurs référencés</span><strong>{recruiters.length}</strong></div>
        <div><BriefcaseBusiness size={18} /><span>Offres reliées</span><strong>{offers.length}</strong></div>
        <div><Globe2 size={18} /><span>Pays / destinations</span><strong>{countries.length}</strong></div>
      </div>

      {error && (
        <div className="error-banner" role="alert">
          <span>{error} Vérifie que le backend est accessible.</span>
          <button onClick={() => void loadData()} aria-label="Réessayer"><RefreshCw size={15} /></button>
        </div>
      )}

      <div className="recruiters-toolbar">
        <label className="searchbox">
          <Search size={16} />
          <input value={search} onChange={event => setSearch(event.target.value)}
            placeholder={view === 'offers' ? 'Métier, entreprise, technologie…' : 'Nom, spécialité, contact…'} />
          {search && <button className="recruiters-clear" onClick={() => setSearch('')} aria-label="Effacer la recherche"><X size={14} /></button>}
        </label>
        <select value={country} onChange={event => setCountry(event.target.value)} aria-label="Filtrer par pays">
          <option value="">Tous les pays</option>
          {countries.map(item => <option key={item} value={item}>{item}</option>)}
        </select>
        {view === 'offers' && (
          <>
            <select value={workMode} onChange={event => setWorkMode(event.target.value)} aria-label="Filtrer par mode de travail">
              <option value="">Tous les modes</option>
              <option value="remote">Télétravail / Remote</option>
              <option value="hybrid">Hybride</option>
              <option value="onsite">Sur site</option>
            </select>
            <select value={visaStatus} onChange={event => setVisaStatus(event.target.value)} aria-label="Filtrer par sponsoring du visa">
              <option value="">Tous les statuts de visa</option>
              <option value="confirmed">Visa confirmé</option>
              <option value="mentioned">Visa mentionné</option>
              <option value="not_offered">Pas de sponsoring indiqué</option>
              <option value="unknown">Visa non vérifié</option>
            </select>
            <select value={relocationStatus} onChange={event => setRelocationStatus(event.target.value)} aria-label="Filtrer par aide à la relocalisation">
              <option value="">Toute aide à la relocalisation</option>
              <option value="confirmed">Aide confirmée</option>
              <option value="mentioned">Aide mentionnée</option>
              <option value="not_offered">Aide non indiquée</option>
              <option value="unknown">Aide non vérifiée</option>
            </select>
            <select value={eligibilityStatus} onChange={event => setEligibilityStatus(event.target.value)} aria-label="Filtrer par éligibilité depuis le Sénégal">
              <option value="">Toute éligibilité Sénégal</option>
              <option value="eligible">Éligible</option>
              <option value="ineligible">Non éligible</option>
              <option value="unclear">À clarifier</option>
              <option value="unknown">Non vérifiée</option>
            </select>
          </>
        )}
        <button className={`btn ${view === 'offers' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setView('offers')}>Offres ({filteredOffers.length})</button>
        <button className={`btn ${view === 'recruiters' ? 'btn-primary' : 'btn-ghost'}`}
          onClick={() => setView('recruiters')}>Annuaire ({filteredRecruiters.length})</button>
      </div>

      {selectedRecruiter !== null && (
        <div className="recruiters-filter-note">
          <span>Offres de : <strong>{selected?.name || 'Recruteur sélectionné'}</strong></span>
          <button className="btn btn-ghost btn-small" onClick={() => setSelectedRecruiter(null)}>
            <X size={13} /> Tous les recruteurs
          </button>
        </div>
      )}

      {loading ? (
        <div className="empty-state"><div className="empty-icon"><RefreshCw className="spin" /></div><h3>Chargement des données…</h3><p>Lecture du répertoire et des offres enregistrées.</p></div>
      ) : view === 'offers' ? (
        filteredOffers.length ? (
          <div className="recruiters-offer-list">
            {filteredOffers.map(item => {
              const offerUrl = externalLink(item.url);
              const sourceUrl = externalLink(item.source_url);
              return (
                <article className="recruiter-offer-card" key={item.id}>
                  <div className="recruiter-offer-mark"><BriefcaseBusiness size={20} /></div>
                  <div className="recruiter-offer-body">
                    <div className="recruiter-offer-top">
                      <span className="recruiter-source">{item.recruiter_name || item.company || 'Source professionnelle'}</span>
                      {item.published_at && <span className="recruiter-date">Publiée : {safeDate(item.published_at)}</span>}
                    </div>
                    <h3>{item.title}</h3>
                    <div className="recruiter-offer-meta">
                      {item.company && <span><Building2 size={13} />{item.company}</span>}
                      {(item.location || item.country) && <span><MapPin size={13} />{[item.location, item.country].filter(Boolean).join(', ')}</span>}
                      {item.work_mode && <span>{item.work_mode}</span>}
                      {item.contract_type && <span>{item.contract_type}</span>}
                    </div>
                    <div className="recruiter-mobility">
                      <span className={`recruiter-mobility-tag status-${item.visa_sponsorship_status || 'unknown'}`}>
                        {mobilityLabel(item.visa_sponsorship_status, visaLabels)}
                      </span>
                      <span className={`recruiter-mobility-tag status-${item.relocation_support_status || 'unknown'}`}>
                        {mobilityLabel(item.relocation_support_status, relocationLabels)}
                      </span>
                      <span className={`recruiter-mobility-tag status-${item.senegal_eligibility_status || 'unknown'}`}>
                        {mobilityLabel(item.senegal_eligibility_status, eligibilityLabels)}
                      </span>
                      <span className={`recruiter-mobility-tag verification-${item.verification_status || 'unverified'}`}>
                        {mobilityLabel(item.verification_status, verificationLabels)}
                      </span>
                    </div>
                    {item.eligibility_notes && <p className="recruiter-eligibility-notes">{item.eligibility_notes}</p>}
                    {item.evidence_url && externalLink(item.evidence_url) && (
                      <p className="recruiter-evidence">
                        <a href={externalLink(item.evidence_url)} target="_blank" rel="noopener noreferrer">
                          Consulter la preuve d’éligibilité et de mobilité <ExternalLink size={12} />
                        </a>
                      </p>
                    )}
                    {item.description && <p className="recruiter-description">{item.description.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim()}</p>}
                    {!!item.skills?.length && <div className="recruiter-tags">{item.skills.map(skill => <span key={skill}>{skill}</span>)}</div>}
                    {item.deadline && <p className="recruiter-deadline">Date limite : {safeDate(item.deadline)}</p>}
                    <div className="recruiter-card-actions">
                      {offerUrl
                        ? <a className="btn btn-primary" href={offerUrl} target="_blank" rel="noopener noreferrer">Voir l’offre <ExternalLink size={14} /></a>
                        : <span className="recruiter-source">Lien d’offre indisponible</span>}
                      {sourceUrl && sourceUrl !== offerUrl && <a className="btn btn-ghost btn-small" href={sourceUrl} target="_blank" rel="noopener noreferrer">Source <ExternalLink size={13} /></a>}
                      <button className="btn btn-ghost btn-small" onClick={() => { setSelectedRecruiter(item.recruiter_id); setView('recruiters'); }}>
                        <Users size={13} /> Voir le recruteur
                      </button>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <div className="empty-state"><div className="empty-icon"><BriefcaseBusiness /></div><h3>Aucune offre correspondante</h3><p>Le répertoire ne contient pas encore d’offre correspondante, ou les filtres sont trop restrictifs. Les nouvelles offres apparaîtront après leur collecte.</p><button className="btn btn-ghost" onClick={() => { setSearch(''); setCountry(''); setWorkMode(''); setVisaStatus(''); setRelocationStatus(''); setEligibilityStatus(''); setSelectedRecruiter(null); }}>Réinitialiser les filtres</button></div>
        )
      ) : filteredRecruiters.length ? (
        <div className="recruiters-directory">
          {filteredRecruiters.map(item => {
            const website = externalLink(item.website_url);
            const contactUrl = externalLink(item.contact_url);
            const linkedinUrl = externalLink(item.linkedin_url);
            const source = externalLink(item.source_url);
            const phoneNumber = item.contact_phone?.trim();
            const phoneHref = phoneNumber?.replace(/[^\d+]/g, '');
            const count = offers.filter(offer => offer.recruiter_id === item.id).length;
            return (
              <article className="recruiter-directory-card" key={item.id}>
                <div className="recruiter-directory-top">
                  <div className="recruiter-offer-mark"><Building2 size={21} /></div>
                  <div className="recruiter-directory-name"><h3>{item.name}</h3><p>{item.country || 'Pays non précisé'}</p></div>
                  <span className="recruiter-count">{count} offre{count > 1 ? 's' : ''}</span>
                </div>
                {!!item.specialties?.length && <div className="recruiter-tags">{item.specialties.map(specialty => <span key={specialty}>{specialty}</span>)}</div>}
                {item.contact_name && <p className="recruiter-contact-name">{item.contact_name}{item.contact_role ? ` · ${item.contact_role}` : ''}</p>}
                {item.notes && <p className="recruiter-description">{item.notes}</p>}
                {item.verified_at && <p className="recruiter-date">Vérifié le {safeDate(item.verified_at)}</p>}
                <div className="recruiter-card-actions">
                  {website && <a className="btn btn-ghost btn-small" href={website} target="_blank" rel="noopener noreferrer"><Globe2 size={13} /> Site officiel <ExternalLink size={12} /></a>}
                  {item.contact_email && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(item.contact_email) && <a className="btn btn-ghost btn-small" href={`mailto:${item.contact_email}`}><Mail size={13} /> {item.contact_email}</a>}
                  {phoneNumber && phoneHref && <a className="btn btn-ghost btn-small" href={`tel:${phoneHref}`}><Phone size={13} /> {phoneNumber}</a>}
                  {linkedinUrl && <a className="btn btn-ghost btn-small" href={linkedinUrl} target="_blank" rel="noopener noreferrer"><Linkedin size={13} /> LinkedIn <ExternalLink size={12} /></a>}
                  {contactUrl && <a className="btn btn-ghost btn-small" href={contactUrl} target="_blank" rel="noopener noreferrer">Contacter <ExternalLink size={12} /></a>}
                  {source && <a className="btn btn-ghost btn-small" href={source} target="_blank" rel="noopener noreferrer">Source vérifiable <ExternalLink size={12} /></a>}
                  <button className="btn btn-primary btn-small" onClick={() => { setSelectedRecruiter(item.id); setView('offers'); }}>
                    Voir ses offres ({count})
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state"><div className="empty-icon"><Users /></div><h3>Annuaire encore vide</h3><p>Les contacts seront affichés lorsqu’ils auront été ajoutés depuis des sources publiques vérifiables. Aucun email personnel ne doit être deviné.</p><button className="btn btn-ghost" onClick={() => { setSearch(''); setCountry(''); }}>Effacer les filtres</button></div>
      )}
      <p className="recruiters-footnote">Les coordonnées et les offres doivent être publiques, vérifiables et accompagnées de leur source. Vérifie toujours les conditions d’éligibilité et de mobilité sur l’annonce officielle.</p>
    </section>
  );
}
