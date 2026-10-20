import { useEffect, useMemo, useState } from 'react';
import {
  Search, GraduationCap, ExternalLink, Star, MapPin,
  Clock, Plus, X, RefreshCw
} from 'lucide-react';

type Training = {
  id: number;
  title: string;
  provider: string;
  category: string;
  country: string;
  location: string;
  delivery_mode: string;
  duration: string;
  eligibility: string;
  description: string;
  official_url: string;
  application_url: string;
  funding_status: string;
  funding_evidence: string;
  cost_details: string;
  deadline: string | null;
  opportunity_status: string;
  enrollment_status: string;
  application_status: string;
  is_favorite: boolean;
  source_name: string;
};

type Source = {
  id: string;
  name: string;
  country: string;
  url: string;
  category: string;
  collection_status: string;
};

type Props = { apiBase: string };

const fundingLabels: Record<string, string> = {
  CONFIRMED_FULL: 'Financement complet confirmé',
  PARTIAL: 'Financement partiel',
  UNCONFIRMED: 'Financement à confirmer',
  UNKNOWN: 'Financement non vérifié',
};

const applicationStatuses = [
  'À examiner', 'Favori', 'Candidature préparée',
  'Candidature envoyée', 'Acceptée', 'Refus', 'Abandonnée',
];

function safeDate(value?: string | null) {
  if (!value) return 'Non précisée';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString('fr-FR');
}

function safeUrl(value?: string) {
  if (!value) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

export default function TrainingPanel({ apiBase }: Props) {
  const [items, setItems] = useState<Training[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [funding, setFunding] = useState('');
  const [applicationStatus, setApplicationStatus] = useState('');
  const [favoritesOnly, setFavoritesOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState('');
  const [form, setForm] = useState({
    title: '',
    provider: '',
    category: 'formation',
    official_url: '',
    application_url: '',
    funding_status: 'UNKNOWN',
    funding_evidence: '',
    deadline: '',
    description: '',
  });

  async function loadData() {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams();
      if (search.trim()) params.set('q', search.trim());
      if (category) params.set('category', category);
      if (funding) params.set('funding_status', funding);
      if (applicationStatus) params.set('application_status', applicationStatus);
      if (favoritesOnly) params.set('favorites_only', 'true');

      const [itemsResponse, sourcesResponse] = await Promise.all([
        fetch(`${apiBase}/trainings?${params.toString()}`),
        fetch(`${apiBase}/trainings/sources`),
      ]);

      if (!itemsResponse.ok || !sourcesResponse.ok) {
        throw new Error('Impossible de charger les formations depuis l’API.');
      }

      const [itemsData, sourcesData] = await Promise.all([
        itemsResponse.json(),
        sourcesResponse.json(),
      ]);

      setItems(Array.isArray(itemsData.items) ? itemsData.items : []);
      setSources(Array.isArray(sourcesData.sources) ? sourcesData.sources : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de chargement.');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [apiBase, search, category, funding, applicationStatus, favoritesOnly]);

  const counts = useMemo(() => ({
    total: items.length,
    full: items.filter(item => item.funding_status === 'CONFIRMED_FULL').length,
    favorites: items.filter(item => item.is_favorite).length,
  }), [items]);

  async function updateItem(item: Training, changes: {
    is_favorite?: boolean;
    application_status?: string;
  }) {
    setError('');
    try {
      const response = await fetch(`${apiBase}/trainings/${item.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      });
      if (!response.ok) throw new Error('La modification n’a pas été enregistrée.');
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erreur de mise à jour.');
    }
  }

  async function createItem(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setFormError('');
    try {
      const payload = {
        ...form,
        provider: form.provider.trim() || 'Non précisé',
        source_name: 'Ajout manuel',
        deadline: form.deadline || null,
      };
      const response = await fetch(`${apiBase}/trainings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data.detail || 'Impossible d’ajouter cette opportunité.');
      }
      setShowAdd(false);
      setForm({
        title: '', provider: '', category: 'formation',
        official_url: '', application_url: '',
        funding_status: 'UNKNOWN', funding_evidence: '',
        deadline: '', description: '',
      });
      await loadData();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Erreur lors de l’ajout.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="training-panel">
      <div className="training-heading">
        <div>
          <h2><GraduationCap size={23} /> Formations & financements</h2>
          <p>Formations numériques, certifications, bourses et aides accessibles aux candidats au Sénégal.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          <Plus size={16} /> Ajouter
        </button>
      </div>

      <div className="training-stats">
        <div><strong>{counts.total}</strong><span>Opportunités affichées</span></div>
        <div><strong>{counts.full}</strong><span>Financements complets confirmés</span></div>
        <div><strong>{counts.favorites}</strong><span>Favoris affichés</span></div>
      </div>

      <div className="training-filters">
        <label className="training-search">
          <Search size={17} />
          <input
            value={search}
            onChange={event => setSearch(event.target.value)}
            placeholder="Rechercher une formation, un organisme…"
          />
        </label>
        <select value={category} onChange={event => setCategory(event.target.value)}>
          <option value="">Toutes les catégories</option>
          <option value="formation">Formations</option>
          <option value="certification">Certifications</option>
          <option value="bourse">Bourses</option>
          <option value="financement">Financements</option>
          <option value="autre">Autres</option>
        </select>
        <select value={funding} onChange={event => setFunding(event.target.value)}>
          <option value="">Tous les financements</option>
          <option value="CONFIRMED_FULL">Complet confirmé</option>
          <option value="PARTIAL">Partiel</option>
          <option value="UNCONFIRMED">À confirmer</option>
          <option value="UNKNOWN">Non vérifié</option>
        </select>
        <select value={applicationStatus} onChange={event => setApplicationStatus(event.target.value)}>
          <option value="">Tous les suivis</option>
          {applicationStatuses.map(status =>
            <option key={status} value={status}>{status}</option>
          )}
        </select>
        <label className="training-favorites-filter">
          <input
            type="checkbox"
            checked={favoritesOnly}
            onChange={event => setFavoritesOnly(event.target.checked)}
          />
          Favoris uniquement
        </label>
        <button className="btn-small" onClick={() => void loadData()} title="Actualiser">
          <RefreshCw size={15} /> Actualiser
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {showAdd && (
        <form className="training-form" onSubmit={createItem}>
          <div className="training-form-heading">
            <h3>Ajouter une opportunité</h3>
            <button type="button" className="btn-small" onClick={() => setShowAdd(false)}>
              <X size={16} /> Fermer
            </button>
          </div>
          <label>Titre *
            <input required minLength={2} maxLength={400} value={form.title}
              onChange={event => setForm({ ...form, title: event.target.value })} />
          </label>
          <label>Organisme
            <input value={form.provider}
              onChange={event => setForm({ ...form, provider: event.target.value })} />
          </label>
          <label>Catégorie
            <select value={form.category}
              onChange={event => setForm({ ...form, category: event.target.value })}>
              <option value="formation">Formation</option>
              <option value="certification">Certification</option>
              <option value="bourse">Bourse</option>
              <option value="financement">Financement</option>
              <option value="autre">Autre</option>
            </select>
          </label>
          <label>Page officielle (HTTPS)
            <input type="url" value={form.official_url}
              onChange={event => setForm({ ...form, official_url: event.target.value })}
              placeholder="https://…" />
          </label>
          <label>Page de candidature (HTTPS)
            <input type="url" value={form.application_url}
              onChange={event => setForm({ ...form, application_url: event.target.value })}
              placeholder="https://…" />
          </label>
          <label>Financement
            <select value={form.funding_status}
              onChange={event => setForm({ ...form, funding_status: event.target.value })}>
              <option value="UNKNOWN">Non vérifié</option>
              <option value="UNCONFIRMED">À confirmer</option>
              <option value="PARTIAL">Partiel</option>
              <option value="CONFIRMED_FULL">Complet confirmé</option>
            </select>
          </label>
          <label>Preuve officielle du financement
            <textarea value={form.funding_evidence}
              onChange={event => setForm({ ...form, funding_evidence: event.target.value })} />
          </label>
          <label>Date limite
            <input type="date" value={form.deadline}
              onChange={event => setForm({ ...form, deadline: event.target.value })} />
          </label>
          <label className="training-description-field">Description
            <textarea value={form.description}
              onChange={event => setForm({ ...form, description: event.target.value })} />
          </label>
          {formError && <div className="error-banner">{formError}</div>}
          <button className="btn btn-primary" type="submit" disabled={saving}>
            {saving ? 'Enregistrement…' : 'Enregistrer'}
          </button>
        </form>
      )}

      {loading ? (
        <div className="empty-state">Chargement des formations…</div>
      ) : items.length === 0 ? (
        <div className="empty-state">
          Aucune opportunité ne correspond à ces filtres. Les nouvelles formations apparaîtront ici lorsqu’elles seront ajoutées.
        </div>
      ) : (
        <div className="training-list">
          {items.map(item => {
            const officialUrl = safeUrl(item.official_url);
            const applicationUrl = safeUrl(item.application_url);
            return (
              <article className="training-card" key={item.id}>
                <div className="training-card-top">
                  <div>
                    <span className="training-category">{item.category}</span>
                    <h3>{item.title}</h3>
                    <p className="training-provider">{item.provider || item.source_name}</p>
                  </div>
                  <button
                    className={`training-star${item.is_favorite ? ' is-favorite' : ''}`}
                    onClick={() => void updateItem(item, { is_favorite: !item.is_favorite })}
                    title={item.is_favorite ? 'Retirer des favoris' : 'Ajouter aux favoris'}
                    aria-label={item.is_favorite ? 'Retirer des favoris' : 'Ajouter aux favoris'}
                  >
                    <Star size={19} fill={item.is_favorite ? 'currentColor' : 'none'} />
                  </button>
                </div>

                <p className="training-funding">
                  {fundingLabels[item.funding_status] || fundingLabels.UNKNOWN}
                </p>
                {item.funding_evidence && <p>{item.funding_evidence}</p>}
                {item.cost_details && <p>{item.cost_details}</p>}
                {item.description && <p className="training-description">{item.description}</p>}

                <div className="training-meta">
                  {(item.location || item.country) && (
                    <span><MapPin size={14} /> {[item.location, item.country].filter(Boolean).join(' · ')}</span>
                  )}
                  {item.duration && <span><Clock size={14} /> {item.duration}</span>}
                  <span>Échéance : {safeDate(item.deadline)}</span>
                  <span>{item.opportunity_status}</span>
                  <span>Inscriptions : {item.enrollment_status}</span>
                </div>

                {item.eligibility && <p><strong>Éligibilité :</strong> {item.eligibility}</p>}

                <div className="training-card-bottom">
                  <label>Suivi
                    <select
                      value={item.application_status}
                      onChange={event => void updateItem(item, { application_status: event.target.value })}
                    >
                      {applicationStatuses.map(status =>
                        <option key={status} value={status}>{status}</option>
                      )}
                    </select>
                  </label>
                  <div className="training-links">
                    {officialUrl && <a href={officialUrl} target="_blank" rel="noopener noreferrer">
                      Source officielle <ExternalLink size={14} />
                    </a>}
                    {applicationUrl && <a href={applicationUrl} target="_blank" rel="noopener noreferrer">
                      Candidater <ExternalLink size={14} />
                    </a>}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}

      <div className="training-sources">
        <h3>Sources de référence</h3>
        {sources.map(source => {
          const url = safeUrl(source.url);
          return (
            <div key={source.id}>
              <span><strong>{source.name}</strong> · {source.collection_status}</span>
              {url && <a href={url} target="_blank" rel="noopener noreferrer">
                Consulter <ExternalLink size={13} />
              </a>}
            </div>
          );
        })}
        <p>La présence d’une source dans cette liste ne signifie pas que ses offres ont été collectées ou que leur financement a été vérifié.</p>
      </div>
    </section>
  );
}
