import './Card.css';

export default function Card({ children, className = '', hoverable = true, ...rest }) {
  return (
    <div className={`card ${hoverable ? 'card--hoverable' : ''} ${className}`} {...rest}>
      {children}
    </div>
  );
}
