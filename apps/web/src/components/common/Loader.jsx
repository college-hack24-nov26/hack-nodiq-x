import './Loader.css';

export default function Loader({ label = 'Analyzing' }) {
  return (
    <div className="loader">
      <span className="loader__ring" />
      <span className="loader__label mono">{label}</span>
    </div>
  );
}
