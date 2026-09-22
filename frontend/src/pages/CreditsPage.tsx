import { useCategoryPhotos } from "../components/CategoryPhoto";
import { categoryLabel } from "../lib/categories";

/** Attribution for everything NavigIQ shows that it didn't create. */
export default function CreditsPage() {
  const photos = useCategoryPhotos();
  const entries = Object.entries(photos).sort(([a], [b]) => a.localeCompare(b));

  return (
    <div className="page-narrow credits">
      <h1>Credits</h1>
      <p className="muted">NavigIQ is built on open data. Thank you to everyone who contributes to it.</p>

      <section className="card">
        <h2 className="card-title">Data</h2>
        <ul>
          <li>Places, roads and maps © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>, ODbL</li>
          <li>Place photos from <a href="https://commons.wikimedia.org" target="_blank" rel="noreferrer">Wikimedia Commons</a>, matched through Wikidata — each credited on the photo itself</li>
          <li>Weather from <a href="https://open-meteo.com" target="_blank" rel="noreferrer">Open-Meteo</a></li>
        </ul>
      </section>

      <section className="card">
        <h2 className="card-title">Category photos</h2>
        {entries.length === 0 ? (
          <p className="muted">No category photos yet — run data/pipelines/category_photos.py.</p>
        ) : (
          <table className="credit-table">
            <thead><tr><th>Category</th><th>Shows</th><th>Photographer</th><th>Licence</th></tr></thead>
            <tbody>
              {entries.map(([key, m]) => (
                <tr key={key}>
                  <td>{categoryLabel(key)}</td>
                  <td><a href={m.source} target="_blank" rel="noreferrer">{m.subject}</a></td>
                  <td>{m.credit}</td>
                  <td>{m.license}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
