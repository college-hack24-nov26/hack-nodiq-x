import Navbar from '../components/landing/Navbar';
import Hero from '../components/landing/Hero';
import ProblemSection from '../components/landing/ProblemSection';
import HowItWorks from '../components/landing/HowItWorks';
import Features from '../components/landing/Features';
import ProductShowcase from '../components/landing/ProductShowcase';
import UseCases from '../components/landing/UseCases';
import TrustSection from '../components/landing/TrustSection';
import CopilotPreview from '../components/landing/CopilotPreview';
import Testimonials from '../components/landing/Testimonials';
import FAQ from '../components/landing/FAQ';
import Contact from '../components/landing/Contact';
import FinalCTA from '../components/landing/FinalCTA';
import Footer from '../components/landing/Footer';
import './LandingPage.css';

export default function LandingPage() {
  return (
    <div className="landing-page">
      <Navbar />
      <Hero />
      <ProblemSection />
      <HowItWorks />
      <Features />
      <ProductShowcase />
      <UseCases />
      <TrustSection />
      <CopilotPreview />
      <Testimonials />
      <FAQ />
      <Contact />
      <FinalCTA />
      <Footer />
    </div>
  );
}
