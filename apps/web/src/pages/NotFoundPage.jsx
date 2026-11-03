import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './NotFoundPage.css';

export default function NotFoundPage() {
  const navigate = useNavigate();
  const { user } = useAuth();

  return (
    <main className="notfound-page">
      <div className="notfound-card">
        <div className="notfound-brand">
          <span className="notfound-mark" />
          NODIQ<span className="notfound-accent">-X</span>
        </div>

        <p className="notfound-code mono">ERROR 404 // ROUTE NOT FOUND</p>

        <h1>This page isn't in the pipeline.</h1>

        <p className="notfound-body">
          The route <code className="mono">{window.location.pathname}</code> doesn't
          exist in NODIQ-X. Nothing was analyzed, modified, or lost — the address
          is simply invalid.
        </p>

        <div className="notfound-actions">
          <button
            type="button"
            className="notfound-primary"
            onClick={() => navigate(user ? '/dashboard' : '/')}
          >
            {user ? 'Back to Dashboard' : 'Back to Home'}
          </button>
          {user && (
            <button
              type="button"
              className="notfound-secondary"
              onClick={() => navigate('/new-analysis')}
            >
              New Analysis
            </button>
          )}
        </div>
      </div>
    </main>
  );
}
