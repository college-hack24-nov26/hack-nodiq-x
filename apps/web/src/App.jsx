import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';
import LandingPage from './pages/LandingPage';
import LoginPage from './pages/LoginPage';
import SignupPage from './pages/SignupPage';
import VerifyOtpPage from './pages/VerifyOtpPage';
import AuthCallbackPage from './pages/AuthCallbackPage';
import ResetPasswordPage from './pages/ResetPasswordPage';
import Dashboard from './pages/Dashboard';
import DashboardLayout from './components/layout/DashboardLayout';
import RequireAuth from './components/auth/RequireAuth';
import Home from './pages/Home'
import Analysis from './pages/Analysis';
import SteelAnalysis from './pages/SteelAnalysis';
import WhiteCastIronAnalysis from './pages/WhiteCastIronAnalysis';
import GrayCastIronAnalysis from './pages/GrayCastIronAnalysis';
import MyAnalyses from './pages/MyAnalyses';
import ReviewCenter from './pages/ReviewCenter';
import Copilot from './pages/Copilot';
import Profile from './pages/Profile';
import Reports from './pages/Reports';
import ReportGenerator from './pages/ReportGenerator';
import ReportPreview from './pages/ReportPreview';
import Analytics from './pages/Analytics';
import Compare from './pages/Compare';
import Lots from './pages/Lots';
import Sessions from './pages/Sessions';
import Anomalies from './pages/Anomalies';
import Settings from './pages/Settings';
import BatchAnalysis from './pages/BatchAnalysis';
import NotFoundPage from './pages/NotFoundPage';
import { Privacy, Terms } from './pages/LegalPages';
import VerificationPortal from './pages/VerificationPortal';


function App() {
  return (
    <ThemeProvider>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<LandingPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/signup" element={<SignupPage />} />
            <Route path="/verify-otp" element={<VerifyOtpPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route path="/forgot-password" element={<ResetPasswordPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/privacy" element={<Privacy />} />
            <Route path="/terms" element={<Terms />} />
            <Route path="/verify" element={<VerificationPortal />} />
            <Route path="/verify/:hash" element={<VerificationPortal />} />
            <Route element={<DashboardLayout />}>
              <Route path="/home" element={<RequireAuth><Home /></RequireAuth>} />
              <Route path="/dashboard" element={<RequireAuth><Dashboard /></RequireAuth>} />
              <Route path='/new-analysis' element={<RequireAuth><Analysis /></RequireAuth>} />
              <Route path='/steel-analysis' element={<RequireAuth><SteelAnalysis /></RequireAuth>} />
              <Route path='/white-cast-iron' element={<RequireAuth><WhiteCastIronAnalysis /></RequireAuth>} />
              <Route path='/gray-cast-iron' element={<RequireAuth><GrayCastIronAnalysis /></RequireAuth>} />
              <Route path='/analyses' element={<RequireAuth><MyAnalyses /></RequireAuth>} />
              <Route path='/my-analyses' element={<RequireAuth><MyAnalyses /></RequireAuth>} />
              <Route path='/copilot' element={<RequireAuth><Copilot /></RequireAuth>} />
              <Route path='/reports' element={<RequireAuth><Reports /></RequireAuth>} />
              <Route path='/batch-analysis' element={<RequireAuth><BatchAnalysis /></RequireAuth>} />
              <Route path='/analytics' element={<RequireAuth><Analytics /></RequireAuth>} />
              <Route path='/compare' element={<RequireAuth><Compare /></RequireAuth>} />
              <Route path='/lots' element={<RequireAuth><Lots /></RequireAuth>} />
              <Route path='/sessions' element={<RequireAuth><Sessions /></RequireAuth>} />
              <Route path='/anomalies' element={<RequireAuth><Anomalies /></RequireAuth>} />
              <Route path='/review-center' element={<RequireAuth><ReviewCenter /></RequireAuth>} />
              <Route path='/settings' element={<RequireAuth><Settings /></RequireAuth>} />
              <Route path="/reports/generate" element={<RequireAuth><ReportGenerator /></RequireAuth>} />
              <Route path="/reports/:reportId" element={<RequireAuth><ReportPreview /></RequireAuth>} />
              <Route path='/profile' element={<RequireAuth><Profile /></RequireAuth>} />
            </Route>

            {/* Catch-all: unknown URLs get a real 404 page, never a blank screen */}
            <Route path="*" element={<NotFoundPage />} />

          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default App;
