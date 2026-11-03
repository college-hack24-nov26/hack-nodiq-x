import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Loader from '../components/common/Loader';
import './AuthCallbackPage.css';

export default function AuthCallbackPage() {
  const navigate = useNavigate();

  useEffect(() => {
    const t = setTimeout(() => navigate('/dashboard'), 1200);
    return () => clearTimeout(t);
  }, [navigate]);

  return (
    <div className="auth-callback">
      <Loader label="Signing you in" />
    </div>
  );
}
