import './Badge.css';

/** tone: 'default' | 'primary' | 'success' | 'warning' | 'error' */
export default function Badge({ children, tone = 'default', dot = true, className = '' }) {
  return (
    <span className={`badge badge--${tone} ${className}`}>
      {dot && <span className="badge__dot" />}
      {children}
    </span>
  );
}
